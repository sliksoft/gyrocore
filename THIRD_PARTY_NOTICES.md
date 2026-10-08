# Third-Party Notices

GyroCore incorporates and adapts open-source components from the Betaflight ecosystem.

Exact import provenance (paths, commits, copied/adapted status):
`docs/upstream/PROVENANCE_MANIFEST.md`.

Vendored trees: `third_party/betaflight/`.

## Betaflight Configurator

Upstream: https://github.com/betaflight/betaflight-configurator

Pinned commit (WU5): `a38c4a797a86a580106162653db92af7e14be787`

License: GNU General Public License version 3.

GyroCore vendors Autotune / CHIRP / Bode / coherence / system-identification sources
under `third_party/betaflight/configurator/`. Existing copyright, license and SPDX
notices are retained in copied source files.

## Betaflight Blackbox Viewer / Blackbox Explorer

Upstream: https://github.com/betaflight/blackbox-log-viewer

Pinned commit (WU5): `a84755c5e897c1a3a580424b64c0df066c12c6b4`

License: GNU General Public License version 3.

GyroCore vendors Blackbox Viewer sources under
`third_party/betaflight/blackbox-log-viewer/`. Existing copyright, license and SPDX
notices are retained in copied source files.

## Betaflight blackbox-tools

Upstream: https://github.com/betaflight/blackbox-tools

Pinned commit (WU5): `f832acf9cd9dbe5ad8220de1a5f4eb4021523d72`

License: GNU General Public License version 3.

GyroCore vendors decoding/parsing C sources under
`third_party/betaflight/blackbox-tools/` (platform `lib/` binaries and cairo render
sources excluded — see that tree’s `IMPORT_NOTES.md`). Runtime decode continues to
use GyroCore’s `gyrocore.decode` wrapper around an installed `blackbox_decode`
binary.

## GyroCore modifications

GyroCore contains original analysis, tuning, safety, desktop integration and workflow code in addition to code adapted from upstream open-source projects.

Modified upstream components will retain their applicable upstream notices.

Local modifications of vendored files are listed in `docs/upstream/PATCHES.md` (currently:
blackbox-tools FLIGHTMODE/DISARM event payload parsing).
