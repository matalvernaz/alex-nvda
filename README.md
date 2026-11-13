# Alex for NVDA

Use Apple's Alex voice with NVDA. After installing the add-on, open NVDA Settings, Alex, or Tools, Alex setup, to download the voice and set it up. The files come directly from Apple. The setup window shows progress, and you can cancel or retry a download.

You can use the newer Sonoma speech engine or the older Lion engine. Keep both if you want to switch between them, or remove the one you do not use. This is a beta release.

## Install or update

Version 0.2.2 is prepared for the first Add-on Store submission. It includes the fix from 0.2.1 for Alex going silent when switching back from another synthesizer or configuration profile. Your existing voices and speech engines are kept.

1. Install the `.nvda-addon` file and restart NVDA. It updates the existing Alex add-on; downloaded voices are kept.
2. Open NVDA Settings, Alex, or Tools, Alex setup.
3. Choose Modern or Legacy (Lion). Existing version 0.1.0 data is recognized as Legacy.
4. Switch to another synthesizer while running setup. Press Download and set up Alex. Setup verifies the downloads, extracts the components, and tests actual speech before selecting the installation.
5. When the status says Ready, press Use Alex.

Modern requires 64-bit Windows 10/11 with working Windows ICU and SQLite services. NVDA itself can be 32-bit. Setup checks these services before starting the large download. Legacy remains available on systems that cannot run the modern host. NVDA 2024.1 or later is required. Secure desktop and Windows sign-in speech are not included.

Modern setup downloads about 14.5 GB and needs about 22 GB of temporary free space. Legacy downloads about 5.6 GB and needs about 8 GB temporarily. Each installation uses about 1 GB afterward, mostly Alex's recordings. Setup shares identical recordings through a hard link when the filesystem supports it; deleting either engine keeps the other's copy working.

Setup runs in the background. Close Settings and reopen it to check progress. Standard Windows controls show status and progress; NVDA announces phases and download milestones. Cancel keeps partial downloads. Retry resumes them. Failed setup leaves the current installation in place.

## Manage downloaded data

The engine selector shows which engines are installed and which one Alex uses. Choose an installed engine and press Use Alex to switch. Merely changing the selector does not change speech.

Remove selected engine's data deletes that engine and keeps the other installation. Switch to another synthesizer first. Deleting the active installation selects the remaining engine for the next time Alex starts. Repairs replace the selected engine's older data after the new installation passes its test.

Successful setup removes its installer archives and temporary extracted files. Check Keep downloads after successful setup to retain them for repairs. Delete saved downloads removes the setup cache, including partial downloads, while keeping installed engines. No cleanup starts automatically when updating the add-on.

## Modern text handling

The modern path preserves UTF-8 text and uses UTF-16 for CoreFoundation strings rather than folding input into MacRoman. Alex remains an English voice; preserving characters does not make it multilingual.

Emoji sequences, including joined emoji and country flags, are expanded into English names from Unicode CLDR 46 before synthesis. Apple's private CoreEmoji framework is not ported. Native macOS emoji descriptions may differ.

## Files and diagnostics

Apple's data lives in `alex` inside the NVDA user configuration, outside the add-on. Updates preserve it. `alex/logs/setup-test.log` records the installation speech test, and `alex/logs/modern-setup.log` records runtime and dictionary preparation errors. Setup failures and host errors also go into NVDA's log. Nothing is uploaded automatically.

No Apple engines, installers, dictionaries, cache files, voice recordings, generated bindings or test audio may be stored in Git history, releases, CI artifacts, or hosted CI. The add-on includes our compiled compatibility hosts, open-source runtimes, Unicode data, Python code and license notices. Packaging explicitly allows only the legacy executable, modern executable, and its two open-source C++ runtime DLLs. It refuses other binaries and Apple Mach-O formats. CI never downloads Apple components.

## Validation

The modern Windows executable has produced speech under isolated Wine/QEMU with components extracted by the add-on's own preparation code. Local checks cover accented input, emoji names, modern dictionary extraction, version 0.1.0 migration, switching engines, shared recordings and download cleanup. Streaming tests check complete long passages, reading markers, rate, volume and interrupted speech through the real driver with NVDA API doubles. These checks use local Apple downloads that are never uploaded.

The [modern engine notes](modern/README.md) record comparisons against native macOS. Speech timing and pronunciation differ for some passages. Windows speech has been tested by a user; the latest profile-switching fix still needs more testing in everyday use.

Hosted CI builds both Windows executables and runs data-free runtime checks on Windows. Python setup and archive tests use small, original synthetic fixtures.

## Build

On Debian/Ubuntu, install Python 3.11 or later, Git, Make, and the i686 and x86_64 MinGW GCC toolchains. The legacy host also needs i686 MinGW G++.

```sh
git clone --no-checkout https://github.com/CrispStrobe/glint.git build-glint
python3 tools/build_host.py --glint-source build-glint
python3 tools/build_modern.py --glint-source build-glint
python3 -m unittest discover -s tests -v
python3 tools/package.py
```

The modern builder downloads SHA-256-pinned LLVM-MinGW and a pinned Capstone checkout. All compilation is sequential. On Windows, run the legacy builder from an MSYS2 MINGW32 environment and the modern builder from MINGW64; see `.github/workflows/build.yml` for compiler options. Build output goes to `dist/alex-0.2.2.nvda-addon`. No Apple component is needed for building or packaging.

## License

The NVDA add-on code is available under the [GNU General Public License, version 2 or later](LICENSE). The separate compatibility programs and build tools retain their [MIT license](licenses/Alex-MIT.txt). The add-on includes the license notices for its other components.

These licenses cover this project's code, not Apple's files. Apple licenses its speech engine and voice separately. Downloading them from Apple does not change Apple's terms. See [the license information checked before submission](docs/addon-store.md#licensing).

## Credits

The compatibility layer and speech driver derive from Tamas Geczy's MIT-licensed [Panthera Speech](https://github.com/tgeczy/panthera-speech), pinned at `7b93500091924b779f9d6f8b482563096b0b705a`. Glint's AAC decoder by CrispStrobe is pinned at `77738f3ed9b15f627196cc5bbd7f6406814ba2fb` and compiled into both hosts.

The modern host uses LLVM-MinGW's libc++ and libunwind, plus statically linked Capstone 5.0.6 for local instruction decoding during setup. Emoji labels come from the English annotations in [Unicode CLDR 46](https://github.com/unicode-org/cldr/tree/release-46/common), revision `e1d37acce5dae468c414172be53b666d58d45be8`, under the Unicode License v3. Corresponding license notices accompany the add-on. Apple's files are not covered by these licenses.
