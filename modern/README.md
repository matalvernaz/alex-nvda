# Modern engine prototype

This branch runs Apple's Intel 64-bit MacinTalk 9.2.22 with its matching SpeechDictionary 9.0.4 outside macOS. Both components were extracted locally from Apple's macOS Sonoma 14.8.9 installer. The voice bank is the same downloadable Alex 2.0.36 used by the released add-on.

The prototype currently runs on Linux x86_64, including under QEMU on an ARM Linux host. It is separate from the released NVDA add-on. There is no modern Windows host, modern NVDA backend, or automatic modern-component setup yet. The existing add-on continues to use Lion's engine.

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

- Comparisons accept ASCII text only. Unsupported Unicode is refused. CoreEmoji has not been ported; this build does not advertise emoji support.
- The private MacinTalk plug-in API and cache layouts can change between macOS releases.
- Windows x64 uses a different calling convention. The Linux prototype does not establish Windows compatibility.
- Cancellation, sustained NVDA navigation and audio-device playback have not been tested with the new backend.
- The current preparation process uses a Mac to expand the Intel system-image patch and extract the cached dictionary. That process has not been implemented as an unattended Windows installer.
- ICU, libc++, libc++abi, libunwind and SQLite are local Linux prototype dependencies. They are not downloaded by the released add-on.

Do not package this backend into an NVDA release until those gaps are addressed and tested.

## Building without Apple files

Use the same pinned Glint source checkout accepted by the main builder:

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

The Intel cryptex system-image patch is separate from those payload files. `reference_image.py` invokes Apple's image patcher on macOS with one worker. Mount only the resulting local image, read-only. Extract SpeechDictionary from its Intel dyld cache with a cache extraction tool. Do not replace or modify system libraries on the Mac.

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
