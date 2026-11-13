"""Prepare an official NVDA Add-on Store submission without publishing anything."""

import argparse
import hashlib
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "matalvernaz/alex-nvda"


def prepare(package, publisher="Matthew Alvernaz", channel="beta"):
	package = Path(package)
	if channel not in ("stable", "beta", "dev"):
		raise ValueError("Choose an NVDA Store channel: stable, beta or dev.")
	with zipfile.ZipFile(package) as archive:
		if archive.getinfo("manifest.ini").file_size > 65536:
			raise ValueError("Unexpectedly large add-on manifest.")
		manifest = archive.read("manifest.ini").decode("utf-8")
	name = re.search(r"^name\s*=\s*([A-Za-z0-9_-]+)\s*$", manifest, re.MULTILINE)
	version = re.search(r"^version\s*=\s*(\d+\.\d+(?:\.\d+)?)\s*$", manifest, re.MULTILINE)
	if name is None or name[1] != "alex" or version is None:
		raise ValueError("The submission must be a versioned Alex add-on.")
	if package.name != f"alex-{version[1]}.nvda-addon":
		raise ValueError("Package filename and manifest version do not match.")
	base = f"https://github.com/{REPOSITORY}"
	fields = {
		"download-url": ("Download URL", f"{base}/releases/download/v{version[1]}/{package.name}"),
		"source-url": ("Source URL", f"{base}/tree/v{version[1]}"),
		"publisher": ("Publisher", publisher),
		"channel": ("Channel", channel),
		"license-name": ("License Name", "MIT; bundled third-party notices included"),
		"license-url": ("License URL", f"{base}/blob/v{version[1]}/LICENSE"),
	}
	body = "\n\n".join(f"### {label}\n\n{value}" for label, value in fields.values()) + "\n"
	query = {"template": "registerAddon.yml", "title": f"[Submit add-on]: Alex {version[1]}"}
	query.update({key: value for key, (label, value) in fields.items()})
	url = "https://github.com/nvaccess/addon-datastore/issues/new?" + urllib.parse.urlencode(query)
	digest = hashlib.sha256()
	with package.open("rb") as source:
		while chunk := source.read(1024 * 1024):
			digest.update(chunk)
	return body, url, fields["download-url"][1], digest.hexdigest()


def verify_public(url, digest):
	"""Use no GitHub token: the Store must be able to download exactly this file anonymously."""
	result = hashlib.sha256()
	with urllib.request.urlopen(url, timeout=30) as source:
		total = 0
		while chunk := source.read(1024 * 1024):
			total += len(chunk)
			if total > 16 * 1024 * 1024:
				raise ValueError("The public add-on download exceeded its expected size.")
			result.update(chunk)
	if result.hexdigest() != digest:
		raise ValueError("The public download does not match the verified local add-on.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("package", type=Path)
	parser.add_argument("--channel", choices=("stable", "beta", "dev"), default="beta")
	parser.add_argument("--publisher", default="Matthew Alvernaz")
	parser.add_argument("--verify-public", action="store_true")
	arguments = parser.parse_args()
	body, form, download, digest = prepare(arguments.package, arguments.publisher, arguments.channel)
	output = arguments.package.with_name(arguments.package.stem + "-store-submission.md")
	output.write_text(body, encoding="utf-8")
	print("Prepared submission: " + str(output))
	print("SHA-256: " + digest)
	print("Official registration form: " + form)
	if arguments.verify_public:
		verify_public(download, digest)
		print("Public download verified. Submission still requires NV Access's approval.")
