"""Fetch resumable, integrity-checked setup files exclusively from Apple's HTTPS servers."""

from dataclasses import dataclass
import http.client
from pathlib import Path
import plistlib
import re
import urllib.error
import urllib.parse
import urllib.request

from .apple import check_cancelled, hash_file

CATALOG_URL = "https://mesu.apple.com/assets/macos/com_apple_MobileAsset_MacinTalkVoiceAssets/com_apple_MobileAsset_MacinTalkVoiceAssets.xml"
LION_URL = "https://updates.cdn-apple.com/2021/macos/041-7683-20210614-E610947E-C7CE-46EB-8860-D26D71F0D3EA/InstallMacOSX.dmg"
LION_SIZE = 4720237409
LION_SHA256 = "db0b2300de719fa3e4ee132b55afd4e689211ad5332760fe5fe7a30351c9e75c"
MAX_VOICE_SIZE = 2 * 1024 * 1024 * 1024


def apple_url(url):
	parts = urllib.parse.urlsplit(url)
	hostname = (parts.hostname or "").lower()
	allowed = hostname.endswith(".apple.com") or hostname.endswith(".cdn-apple.com")
	if parts.scheme != "https" or not allowed or parts.username or parts.password or parts.port not in (None, 443):
		raise ValueError("Setup refused a download address outside Apple's HTTPS servers.")
	return url


class AppleRedirects(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, request, response, code, message, headers, new_url):
		apple_url(new_url)
		return super().redirect_request(request, response, code, message, headers, new_url)


def open_apple(url, headers=None):
	request = urllib.request.Request(apple_url(url), headers=headers or {})
	opener = urllib.request.build_opener(AppleRedirects())
	response = opener.open(request, timeout=20)
	apple_url(response.geturl())
	return response


@dataclass(frozen=True)
class Download:
	url: str
	size: int
	algorithm: str
	digest: str
	filename: str


LION = Download(LION_URL, LION_SIZE, "sha256", LION_SHA256, "lion.dmg")


def find_alex(cancel):
	check_cancelled(cancel)
	with open_apple(CATALOG_URL) as response:
		catalog = response.read(2 * 1024 * 1024 + 1)
	if len(catalog) > 2 * 1024 * 1024:
		raise ValueError("Apple's voice catalog is unexpectedly large.")
	assets = plistlib.loads(catalog).get("Assets", [])
	candidates = []
	for asset in assets:
		if asset.get("VoiceId") != "com.apple.speech.synthesis.voice.Alex" or asset.get("Platform") != "macOS":
			continue
		if asset.get("_MeasurementAlgorithm") not in ("SHA-1", "SHA-256"):
			continue
		algorithm = "sha1" if asset["_MeasurementAlgorithm"] == "SHA-1" else "sha256"
		measurement = asset.get("_Measurement")
		length = 20 if algorithm == "sha1" else 32
		if not isinstance(measurement, bytes) or len(measurement) != length:
			continue
		size = asset.get("_DownloadSize", 0)
		if not isinstance(size, int) or not 0 < size <= MAX_VOICE_SIZE:
			continue
		url = apple_url(asset["__BaseURL"] + asset["__RelativePath"])
		digest = measurement.hex()
		filename = "alex-" + digest + ".zip"
		download = Download(url, size, algorithm, digest, filename)
		candidates.append((int(asset.get("_ContentVersion", 0)), download))
	if not candidates:
		raise ValueError("Apple's macOS catalog has no supported Alex download. Please try again later.")
	return max(candidates, key=lambda candidate: candidate[0])[1]


def fetch(download, cache, progress, cancel, opener=open_apple):
	"""Resume a partial file only when the server returns the exact requested byte range."""

	cache = Path(cache)
	cache.mkdir(parents=True, exist_ok=True)
	destination = cache / download.filename
	partial = cache / (download.filename + ".partial")
	def verification_progress(stage, percent, detail):
		name = "the speech engine" if download == LION else "Alex"
		progress("Checking " + name, percent, "Verifying the downloaded file")
	if destination.exists():
		if destination.stat().st_size == download.size and hash_file(destination, download.algorithm, cancel, verification_progress) == download.digest:
			return destination
		destination.unlink()
	if partial.exists() and partial.stat().st_size > download.size:
		partial.unlink()

	for attempt in range(3):
		check_cancelled(cancel)
		completed = partial.stat().st_size if partial.exists() else 0
		try:
			if completed < download.size:
				headers = {"Accept-Encoding": "identity"}
				if completed:
					headers["Range"] = "bytes=" + str(completed) + "-"
				with opener(download.url, headers) as response:
					status = response.status
					if status == 206:
						expected = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
						if expected is None or tuple(map(int, expected.groups())) != (completed, download.size - 1, download.size):
							raise ValueError("Apple returned an unexpected download range. Please retry setup.")
					elif status == 200:
						completed = 0
					else:
						raise ValueError("Apple returned an unexpected download response.")
					mode = "ab" if completed else "wb"
					with partial.open(mode) as target:
						while chunk := response.read(1024 * 1024):
							check_cancelled(cancel)
							if completed + len(chunk) > download.size:
								raise ValueError("Apple's download exceeded its advertised size.")
							target.write(chunk)
							completed += len(chunk)
							message = f"{completed / 1024 / 1024:.0f} of {download.size / 1024 / 1024:.0f} MB"
							progress("Downloading " + ("the speech engine" if download == LION else "Alex"), completed * 100 // download.size, message)
			if partial.stat().st_size != download.size:
				raise OSError("Apple's download ended before the file was complete.")
			if hash_file(partial, download.algorithm, cancel, verification_progress) != download.digest:
				partial.unlink()
				raise OSError("The downloaded file failed its integrity check. Setup will download it again.")
			partial.replace(destination)
			return destination
		except (OSError, urllib.error.URLError, http.client.IncompleteRead) as error:
			if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429) and error.code < 500:
				raise
			if attempt == 2:
				raise OSError("The Apple download could not finish. Check your connection and retry; partial downloads are kept.") from error
			progress("Waiting to retry the download", 0, str(error))
			cancel.wait(2 ** attempt)
	raise RuntimeError("Download ended without a result")
