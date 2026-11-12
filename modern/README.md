# Modern engine port

The modern backend runs Apple's Intel 64-bit MacinTalk 9.2.22 with its matching SpeechDictionary 9.0.4 outside macOS. Both components come directly from Apple's macOS Sonoma 14.8.9 installer. The voice bank is the same downloadable Alex 2.0.36 used by the legacy backend.

Version 0.2.0 includes a separate Windows x64 host, a UTF-8 NVDA path and automatic component preparation. The legacy host and data remain available. The Linux x86_64 host is retained for local comparisons.

## What was tested

Five passages were rendered with the released Lion host, this prototype, and the native MacinTalk plug-in on a Mac. Text, voice data and rates were matched. These are local tests with actual Apple components; hosted CI must use synthetic fixtures only.

| Passage | Rate | Lion frames | Modern prototype frames | Native Mac frames |
| --- | ---: | ---: | ---: | ---: |
| Greeting | 180 | 99,757 | 99,757 | 99,751 |
| Fast reading | 450 | 50,305 | 50,305 | 50,305 |
| Abbreviations and pronunciation | 180 | 144,534 | 140,667 | 140,667 |
| Sentence phrasing | 180 | 151,832 | 151,188 | 151,188 |
| Numbers, date and version | 240 | 202,178 | 202,069 | 202,412 |

Audio is mono PCM16 at 22,050 Hz. The greeting and fast-reading recordings are sample-identical between the old and new portable engines. For fast reading, pronunciation and phrasing, the modern prototype's RMS error against native macOS is below one PCM unit. Greeting and number handling still have timing differences against native output and need investigation. Different output is not, by itself, evidence of better sound.

The old host was also tested with a working SQLite runtime. This did not change its frame counts. A 64-bit Lion build with both SQLite and the newly implemented XML property-list reader still produced the old pronunciation result. The observed differences therefore survive those two compatibility-layer checks.

The newer prototype rendered a complete greeting with a measured peak resident memory of about 79 MiB, including QEMU. Cache address space is reserved sparsely; only component segments and required import pages are committed. A large virtual address range does not require an equally large allocation of RAM.

## Current limits

- The comparison table below was measured with ASCII passages on the Linux host. The Windows host has also rendered accented UTF-8 input and English emoji names. This does not establish pronunciation for every Unicode character.
- CoreFoundation text is preserved as UTF-16. The NVDA frontend expands emoji using Unicode CLDR 46 English labels, rather than loading Apple's private CoreEmoji framework.
- The private MacinTalk plug-in API and cache layouts can change between macOS releases.
- Windows x64 adapters translate Darwin calls into the Windows CRT, libc++, ICU and SQLite conventions. ICU and SQLite come from Windows. Two open-source LLVM-MinGW runtime DLLs accompany the host.
- Cancellation, sustained NVDA navigation and audio-device playback have not been tested with the new backend.
- C++ exception propagation through loaded Darwin machine code is unsupported. Those exceptional paths terminate the isolated host with diagnostics instead of attempting incompatible unwinding; NVDA can restart the host.
- The full-image extraction path is pinned to the tested installer digest. Differential RIDIFF patches are refused.

Actual NVDA listening and audio-device tests remain necessary on Windows. Wine synthesis and tests with NVDA API doubles are narrower checks.

## Building without Apple files

For the packaged Windows host, use the same pinned Glint source checkout accepted by the legacy builder:

```sh
python3 tools/build_modern.py --glint-source /path/to/glint
```

This fetches SHA-256-pinned LLVM-MinGW 20261104 and Capstone 5.0.6 revision `accf4df62f1fba6f92cae692985d27063552601c`, builds serially, and copies only the host and its two C++ runtime DLLs into the add-on. GCC compiles the C calling-convention adapters, while LLVM-MinGW compiles and links the libc++ adapter. No Apple files are read while building. On Windows, use MINGW64; the legacy builder uses MINGW32.

For the Linux comparison host:

```sh
python3 modern/build.py --glint-source /path/to/glint
python3 modern/build.py --checks --glint-source /path/to/glint
qemu-x86_64 -L /usr/x86_64-linux-gnu build/modern/checks
python3 -m unittest discover -s tests -v
```

The defaults use the Linux x86_64 cross-compilers. On an x86_64 Linux machine, pass `--cc gcc --cxx g++` and run the resulting executable directly. Builds are sequential and do not read Apple components. The output is under `build/modern`, outside the add-on.

## Local component preparation

Apple's software-update catalog supplies the full InstallAssistant package. Its stored SharedSupport image contains a MacSoftwareUpdate ZIP. `extract_payloads.py` reads selected speech files from that ZIP, one payload at a time:

```sh
python3 modern/extract_payloads.py /local/update.zip /local/extracted
```

The PBZX reader limits compressed and decompressed chunks to 64 MiB and uses an LZMA workspace limit. The disk reader reads raw and zero-filled spans in requested windows instead of materializing multi-gigabyte spans. During development, the full payload scan ran with a 512 MiB cgroup limit, swapping disabled and one CPU. The Python process used about 34 MiB of resident memory.

The automatic installer reads the Intel cryptex full-image RIDIFF stream directly. Its variant stream contains the uncompressed file forks, so the add-on extracts the six cache files without reconstructing an APFS image. All six extracted files were byte-identical to a separate read-only extraction on a Mac. The direct extraction used about 33 MiB of resident memory locally. `reference_image.py` is retained only as a macOS research comparison helper, not used by setup.

The original Python Mach-O exporter copies the dictionary's needed segments, removes cache slide pointers, compacts its symbol strings and reconstructs the link-edit tables. The bundled host's statically linked Capstone scanner finds RIP-relative imports. Python resolves those imports against the downloaded cache and writes fingerprinted bindings locally. Setup needs no external extraction programs or Python packages.

An extracted cached library still contains references to the cache's shared import table. The following tools generate build-specific binding metadata locally:

```sh
# Requires Capstone for instruction decoding.
python3 modern/prepare_cached.py /local/SpeechDictionary

# Run where the original Intel cache and its subcaches are readable.
python3 modern/cache_symbols.py /local/dyld_shared_cache_x86_64h \
  /local/SpeechDictionary.references.json /local/SpeechDictionary.queries.json \
  /local/resolved-slots.json --symbols-output /local/resolved-symbols.json

python3 modern/prepare_cached.py /local/SpeechDictionary \
  --resolved /local/resolved-slots.json --symbols /local/resolved-symbols.json
```

The generated `.bindings` file belongs beside the extracted dictionary. Its component fingerprint prevents accidental use with a different binary. It is derived from Apple components and must stay local, together with all intermediate query and symbol files.

The runtime tree has the same `Speech/Synthesizers`, `Speech/Voices` and `SpeechDictionary.framework/Versions/A` structure used by the old host. With the prototype's Linux dependencies available in its loader path:

```sh
build/modern/alex_modern_host --render --tree /local/runtime \
  --voice Alex --rate 180 --numbers off --text 'Hello Matt.' \
  --output /local/comparison.wav
```

`native_reference.c` renders the supplied voice bundle through the native Mac plug-in. It redirects output before speaking and does not install a voice or change the Mac's default synthesizer.

## File restrictions

Apple components, generated bindings and symbol addresses, installer packages, caches, voice files and recordings stay outside Git history, releases and hosted CI. This directory contains original compatibility and research-tool source only. The released add-on never downloads an Apple component from GitHub.
