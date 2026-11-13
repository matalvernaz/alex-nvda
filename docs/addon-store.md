# Native NVDA add-on updates

Alex uses the normal NVDA add-on identity, `alex`, and a numeric version. NVDA's built-in updater matches that identity against its Add-on Store catalog. It does not poll this repository's GitHub releases. The existing `updateChannel = None` manifest entry is not a switch for the native updater; NVDA's Store settings choose the channel.

## Register this add-on

The current repository is private. The Add-on Store needs a publicly downloadable add-on and accessible source for review. Making the repository public and submitting the registration are separate publication steps. Preparing the submission below does neither.

### Submission review, 2026-11-13

Registration has not been submitted. The existing 0.2.1 preparation output is a draft, not a compliance check. Its MIT license field reflects the current package; do not relabel that immutable release as GPL without correcting the actual distribution.

Two licensing questions need separate treatment:

- [NVDA's plugin and driver exception](https://github.com/nvaccess/nvda/blob/master/copying.txt#non-gpl-components-in-plugins-and-drivers) requires GPL version 2 or later for the NVDA integration, while allowing separately licensed synthesizer components. Our current root license and packaged project notice are MIT only. A corrected distribution can retain the upstream MIT notices and license independent native components separately.
- [Apple's Sonoma license](https://www.apple.com/legal/sla/docs/macOSSonoma.pdf), sections 2F and 2J, restricts voice use and use of the software on non-Apple computers. Apple-only downloads avoid our redistribution of those files; they do not themselves establish permission to run the extracted engine on Windows. No separate permission has been established in this review. This is not a determination of enforceability or an NV Access rejection.

Comparable projects exist. [ClassicVoices for NVDA](https://github.com/Levi-Gobin/classicvoices/blob/main/nvda/README.md) downloads Apple firmware and voices after installation. [Panthera Speech](https://github.com/tgeczy/panthera-speech) runs Apple's older MacinTalk engines, including Alex, on Windows and excludes Apple data. [outspoken-nvda](https://github.com/tgeczy/outspoken-nvda) similarly requires users to supply old Macintosh speech engines. These projects establish technical and distribution precedent, not permission from Apple.

The Store's 616 add-on IDs, `submitters.json`, and issue searches contained no registration for those three projects when checked. Therefore Store acceptance of this Apple-engine approach remains unconfirmed. [Tiflotecnia Voices](https://github.com/nvaccess/addon-datastore/blob/master/addons/tiflotecniaVoices/4.2.1.json) is an accepted proprietary-synthesizer example, but explicitly requires a voice license and does not establish permission for Apple's engines.

The ID `alex` and version `0.2.1` meet the published format rules; `2024.1.0` and `2026.1.0` are recognized, nonexperimental API versions in the current catalog. Public anonymous downloads cannot be verified while the repository remains private. First-time publisher approval, automatic validation and the Store's malware scan remain outstanding. No assumption about the outcome of manual review is made.

After publishing a checked release, run:

```sh
python3 tools/store_submission.py dist/alex-0.2.1.nvda-addon --channel beta
```

This writes the exact issue-form fields to `dist/alex-0.2.1-store-submission.md` and prints a prefilled official registration-form link. The download and source URLs are pinned to the release tag. The submission contains no Apple components or locally generated bindings.

Once the source and release are public, verify that an anonymous download returns the same add-on:

```sh
python3 tools/store_submission.py dist/alex-0.2.1.nvda-addon --channel beta --verify-public
```

Submit the prepared form to `nvaccess/addon-datastore`. A first submission requires approval from NV Access's review team, which can take up to two weeks. Future versions also need a Store submission; publishing a GitHub release alone does not update the catalog. Use the same ID, `alex`, and an increasing version for each release. Keep experimental releases in the beta channel until Windows testing supports a stable release.

## Existing manual installations

After the Store accepts Alex, a manually installed copy may still have its update channel set to Same, meaning External. In NVDA's Add-on Store, choose the appropriate update channel for Alex, such as Beta or Any, or install the Store version once. NVDA then handles checks, notifications, verified downloads and installation using its normal update preference. Do not change the user's global Store settings or write NVDA's private metadata files from this add-on.

Downloaded Apple engine and voice files remain in the shared NVDA configuration directory, outside the add-on. Native add-on updates preserve them and do not repeat engine setup.

## Official references

- [NV Access submission guide](https://github.com/nvaccess/addon-datastore/blob/master/docs/submitters/submissionGuide.md)
- [Official registration form](https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml)
- [NVDA update-channel implementation](https://github.com/nvaccess/nvda/blob/master/source/addonStore/models/channel.py)
