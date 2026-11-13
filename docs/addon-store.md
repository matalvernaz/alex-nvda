# Native NVDA add-on updates

Alex uses the normal NVDA add-on identity, `alex`, and a numeric version. NVDA's built-in updater matches that identity against its Add-on Store catalog. It does not poll this repository's GitHub releases. The existing `updateChannel = None` manifest entry is not a switch for the native updater; NVDA's Store settings choose the channel.

## Register this add-on

The current repository is private. The Add-on Store needs a publicly downloadable add-on and accessible source for review. Making the repository public and submitting the registration are separate publication steps. Preparing the submission below does neither.

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
