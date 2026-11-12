# Alex for NVDA

Use Apple's downloadable macOS Alex voice in NVDA. The add-on downloads and prepares the required files directly from Apple, with progress and cancellation. You do not need a Mac, an installer image, Python, or an Apple account.

This is an experimental build. It uses Alex 2.0.36 from Apple's macOS voice catalog with the Mac OS X Lion engine and a compatibility layer derived from [Panthera Speech](https://github.com/tgeczy/panthera-speech). It does not run the current macOS speech engine, and identical pronunciation and timing to current macOS have not been established.

## Install and set up

1. Install the `.nvda-addon` file and restart NVDA.
2. Open NVDA Settings and choose **Alex**, or open **Tools → Alex setup**.
3. Press **Download and set up Alex**. Setup downloads the engine installer and the voice directly from Apple's servers, verifies them, extracts the required files, and tests that Alex produces audio.
4. When the status says **Ready**, press **Use Alex**. You can also select **Alex (Apple download)** in NVDA's Synthesizer dialog.

Setup downloads about 5.6 GB and needs about 8 GB free while working. The installed speech data takes about 1 GB. The large downloads are removed after successful setup. No installer scripts or Apple executables are launched during extraction.

Setup runs in the background. You can close Settings and reopen it to check progress. The status, progress bar and buttons are standard Windows controls. NVDA announces setup phases and download milestones.

Cancel keeps partial downloads, so pressing Download again continues them. A failed download or speech test leaves an existing installation in place. To repair Alex, switch to another synthesizer first, then run setup again.

## Where files live

Apple's files are stored in the `alex` folder inside your NVDA user configuration, outside the add-on. Updating the add-on preserves them. Temporary downloads are stored there too. Setup diagnostics are in `alex/logs/setup-test.log`.

No Apple engines, voice recordings, installers, dictionaries, generated Apple machine code, or test audio belong in this repository, its Git history, CI artifacts, or releases. The add-on contains only original/MIT code, the native host compiled from that code, and license notices. The packaging tool rejects unapproved files and Apple binary formats. CI builds without downloading any Apple components.

## Validation status

- The actual Apple Alex download and installer have been downloaded and extracted locally.
- Real synthesis has been exercised through the i386 Linux build of the same host under QEMU, including the silent-start regression that was fixed during development.
- The packaged Windows host is cross-compiled with MinGW and includes the Glint AAC decoder.
- Windows/NVDA playback, accessible control behavior and rapid navigation still require testing on Windows. Linux tests and NVDA API test doubles cannot establish those behaviors.

The first release is a test build, not a claim that those Windows checks have passed. The add-on targets NVDA 2024.1 and later on Windows 10/11. Sign-in and secure-desktop use are not included in this build.

## Build

On Debian/Ubuntu with Python 3, Git and the i686 MinGW C/C++ toolchain:

```
git clone https://github.com/CrispStrobe/glint.git build-glint
python3 tools/build_host.py --glint-source build-glint
python3 -m unittest discover -s tests -v
python3 tools/package.py
```

The builder exports a pinned Glint commit and applies Panthera's decoder patches. The package is written to `dist/alex-0.1.0.nvda-addon`. Building never needs an Apple component. A separate `--target linux` build is available for local synthesis validation with an i686 Linux cross-compiler.

## Credits and changes to Panthera

The Mach-O loader, macOS API compatibility code, speech pipeline, markers, text handling and disk-image reader come from Tamas Geczy's MIT-licensed Panthera Speech, pinned at `7b93500091924b779f9d6f8b482563096b0b705a`. Its license is preserved under `vendor/panthera/LICENSE` and in the add-on.

The setup interface, Apple-only downloader, nested installer reader, transactional installation, speech health check and separate Alex driver are additions here. Native changes make the host compile with MinGW, preserve thread-local state, and wait for Lion's completion signal instead of treating a cold voice's startup silence as completed speech.

Glint is by CrispStrobe, pinned at `77738f3ed9b15f627196cc5bbd7f6406814ba2fb`, MIT licensed. Its code is fetched only while building and compiled into the host. Its notice and the compiler runtime notices accompany the add-on. Apple's files are not covered by these projects' licenses.
