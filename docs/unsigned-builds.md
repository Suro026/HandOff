# Unsigned builds: what the warnings mean

The Handoff builds are **not code-signed and not notarized**. Signing needs a paid certificate or developer membership, which this project doesn't have. That has consequences you should understand before you run it.

**An unsigned app is not "officially verified".** Windows and macOS warn about unsigned apps because they can't tell who made them. Clicking through those warnings means you are choosing to trust this project and the place you downloaded the file from. Handoff doesn't claim to be verified by Microsoft, Apple or anyone else.

## Check the download first

Each release has a `SHA256SUMS` file. Compare it with your download:

- **Windows (PowerShell):** `Get-FileHash .\Handoff-0.1.0-windows-x86_64.zip -Algorithm SHA256`
- **macOS / Linux:** `shasum -a 256 Handoff-0.1.0-*.tar.gz`

If the numbers match, the file is the one the project published. That shows the file wasn't damaged or swapped on the way to you. It does **not** prove the project's build is safe; for that, read the source or build it yourself (`python packaging/build.py`).

## Windows

Windows SmartScreen may show **"Windows protected your PC"**. If you decided to trust the download, choose **More info**, then **Run anyway**. Some antivirus programs are cautious about unsigned programs that open network connections; Handoff does open them (that is its purpose), but only the ones described in the README.

## macOS (not yet built or tested)

Gatekeeper blocks unsigned, un-notarized apps. If you trust the download, open **System Settings > Privacy & Security** after the first blocked attempt and choose **Open Anyway**. Notarization needs a paid Apple Developer membership, which this project doesn't have.

## Linux (not yet built or tested)

Archives are not signed. Unpack, then run `Handoff/Handoff`. Some desktops (for example default GNOME) don't show tray icons; Handoff still works, and the dashboard has Stop sharing and Quit buttons.

## The sharing helper download

Quick Share downloads Cloudflare's `cloudflared` the first time you use it. Handoff only runs it if its SHA-256 matches the value pinned in `handoff/sharing/cloudflared_pins.json`. That check protects you from a corrupted or swapped download; it does not make `cloudflared` something this project vouches for.

## For maintainers

To reduce these warnings later, sign Windows builds with a code-signing certificate and notarize macOS builds. Some programs offer signing to open-source projects at no cost; I have not checked their current terms. Until then, publish `SHA256SUMS` with every release and keep this page accurate.
