# Alex updates through NVDA

Alex is being submitted to the beta channel of NVDA's Add-on Store. Submission does not mean it has been accepted. You can check the [submission and any replies](https://github.com/nvaccess/addon-datastore/issues?q=is%3Aissue+author%3Amatalvernaz+Alex).

## Getting updates

Once Alex is accepted, NVDA can check for updates and install them through the Add-on Store. A GitHub release on its own does not make an update appear there.

If you installed Alex from a downloaded file, open the Add-on Store and set Alex's update channel to Beta or Any. You can also install the Store copy once it is available. Your chosen NVDA update settings still apply.

Voice and speech engine files are kept outside the add-on. Updating Alex preserves them, so you do not need to run the large downloads again.

## Licensing

Version 0.2.2 includes the GNU General Public License, version 2 or later, for the NVDA add-on code. The separate compatibility programs and build tools keep their MIT license. The original Panthera Speech and other component notices are included too. Earlier releases have not been changed.

[NVDA's license](https://github.com/nvaccess/nvda/blob/master/copying.txt#non-gpl-components-in-plugins-and-drivers) allows a driver to use a separately licensed speech engine. That permission does not change the speech engine's own terms.

Apple's engine and voice are not included in the add-on or its GitHub repository. Setup downloads them directly from Apple. [Apple's Sonoma license](https://www.apple.com/legal/sla/docs/macOSSonoma.pdf), sections 2F and 2J, restricts voice use and use on non-Apple computers. Direct downloads do not themselves establish permission to run the extracted engine on Windows. No separate permission has been established in this review.

## Similar projects

[ClassicVoices for NVDA](https://github.com/Levi-Gobin/classicvoices/blob/main/nvda/README.md) also downloads Apple firmware and voices after installation. [Panthera Speech](https://github.com/tgeczy/panthera-speech) runs older MacinTalk engines, including Alex, on Windows without distributing Apple's files. [outspoken-nvda](https://github.com/tgeczy/outspoken-nvda) uses speech engines supplied by the user.

No Store registration for those projects was found when checked on November 13, 2026. Their existence does not establish Store acceptance or permission from Apple. The Store does list [Tiflotecnia Voices](https://github.com/nvaccess/addon-datastore/blob/master/addons/tiflotecniaVoices/4.2.1.json), which uses a proprietary speech engine and explicitly requires a voice license.

## Preparing future submissions

This section is for maintainers. Use the same add-on ID, `alex`, and a higher version number for each update. The Store needs a public HTTPS download and a link to the matching source. Each submitted download must continue to return the same file.

After publishing a checked release, run:

```sh
python3 tools/store_submission.py dist/alex-0.2.2.nvda-addon --channel beta --verify-public
```

The tool checks the package's identity and license notice, writes the registration fields to `dist/alex-0.2.2-store-submission.md`, and prints the official form link. It also downloads the release without a GitHub token and compares its checksum. It does not publish or submit anything, and it cannot decide whether the downloaded Apple components may be used.

Submit the form to `nvaccess/addon-datastore`. First-time publisher approval can take up to two weeks. The Store also validates the metadata and scans the add-on for malware. Keep experimental releases in the beta channel.

Do not change the user's global Store settings or NVDA's private metadata files from this add-on.

## Official references

- [Submission guide](https://github.com/nvaccess/addon-datastore/blob/master/docs/submitters/submissionGuide.md)
- [Registration form](https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml)
- [NVDA update channels](https://github.com/nvaccess/nvda/blob/master/source/addonStore/models/channel.py)
