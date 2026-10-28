# Handoff

Give your client your finished work, straight from your own computer.

Add your files, click **Create share link**, and send the link on WhatsApp, email or anywhere else. Your client opens it in a browser and previews or downloads the **original files**: nothing compressed, resized or watermarked.

- **Your computer is the host.** Files stay on your disk. Nothing is uploaded to a Handoff cloud, and there is no Handoff server.
- **Free, and no account, domain or subscription.** The project has no hosting costs to pass on.
- **Private, revocable links.** Add a password, an expiry or a download limit. Stop a link, or all sharing, at any time.
- **Payment is between you and your client.** Handoff doesn't take, check or enforce payment.

> **Status: early development (v0.1, not an official release).** See [What works and what is still untested](#what-works-and-what-is-still-untested) before relying on it.

## What you need to know first

- **Your computer has to be on, awake and online** while your client opens the link. If it's off, asleep or disconnected, the link simply doesn't work until it's back. That's by design: your computer is the host.
- **Handoff copies your files** into its own storage folder. Your originals stay where they are, so a 40 GB project uses about 40 GB of extra disk space. Handoff tells you before it copies large files.
- **Quick Share links are temporary.** The easiest way to share over the internet uses a free tunnel service whose address changes whenever Handoff restarts or reconnects. See [Choosing how clients reach you](#choosing-how-clients-reach-you).

## Download and install

Get the file for your system from the project's **Releases** page, plus `SHA256SUMS` to check it. Builds are **unsigned** ([what that means](docs/unsigned-builds.md)).

| System | File | Status |
|---|---|---|
| Windows 10/11, 64-bit | `Handoff-<version>-windows-x86_64.zip` | **Built and tested** |
| Linux, 64-bit Intel/AMD | `Handoff-<version>-linux-x86_64.tar.gz` | Build prepared, **untested** |
| Linux, 64-bit ARM | `Handoff-<version>-linux-aarch64.tar.gz` | Build prepared, **untested** |
| macOS, Intel | `Handoff-<version>-macos-x86_64.tar.gz` | Build prepared, **untested** |
| macOS, Apple Silicon | `Handoff-<version>-macos-arm64.tar.gz` | Build prepared, **untested** |

**Windows**

1. Unzip into a **short path** such as `C:\Handoff`. A long path can fail with "Failed to load Python DLL ... filename or extension is too long".
2. Double-click `Handoff\Handoff.exe`. If Windows shows "Windows protected your PC", choose More info, then Run anyway, after checking the SHA-256.
3. Check the file first (PowerShell): `Get-FileHash .\Handoff-<version>-windows-x86_64.zip` and compare with `SHA256SUMS`.

**Linux**

```bash
sha256sum -c SHA256SUMS --ignore-missing
tar xzf Handoff-<version>-linux-x86_64.tar.gz
./Handoff/Handoff
```

The tray icon needs a desktop with tray support (on GNOME, the AppIndicator extension). Without one, the dashboard still opens in the browser.

**macOS**

```bash
shasum -a 256 -c SHA256SUMS --ignore-missing
tar xzf Handoff-<version>-macos-arm64.tar.gz
xattr -dr com.apple.quarantine Handoff
./Handoff/Handoff
```

The `xattr` line removes the "unidentified developer" block that macOS puts on unsigned downloads. Only run it on a file whose checksum you checked.

**From source (any system, Python 3.12 or newer)**

```bash
git clone https://github.com/Suro026/HandOff.git
cd HandOff
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-desktop.txt
python -m handoff desktop
```

First run: Handoff opens its dashboard in your browser and puts an icon in the system tray. Create a username and password for this computer.

## Share your work

1. **Create a project** and give it a name.
2. **Add the finished files.** Drag them in or choose them.
3. Choose **Access**: "View and download originals" or "View only" (see the limits below). Add a password or an expiry if you like.
4. Click **Create share link.**
   - The first time, Handoff asks how your client will reach you. Pick one (next section).
   - Handoff starts the connection and checks it. The bar at the top shows **Sharing online** only once it has proven the link works.
5. **Copy the link** and send it. Your client opens it in a browser, with nothing to install.

To change your mind: click **Revoke** to kill one link, **Stop sharing** to close everything at once, or **Quit Handoff** to shut it all down. The tray icon has the same buttons.

## Choosing how clients reach you

| Method | Setup | Good for | Honest limits |
|---|---|---|---|
| **Quick Share** | None, one click | Handing something over soon | Temporary address that changes on restart or reconnect. It uses a free tunnel whose provider calls it a testing service with no uptime guarantee. Traffic passes through that provider. Usage limits may apply and can change. |
| **Same Wi-Fi** | None | Someone in the same office or home | Only people on the same network can open it. Not encrypted (plain HTTP). Your firewall may ask to allow Handoff. |
| **Your own address** | You supply it | A stable link, if you already have a web address or server | You must keep that address and its HTTPS certificate working. |
| **Tailscale Funnel** (advanced) | Tailscale installed and signed in, one command | A stable address if you already use Tailscale | Bandwidth limits that Tailscale doesn't publish. Handoff only reads its status; you run the one command. |

The details, with the sources I checked and what I could not verify, are in [docs/remote-access.md](docs/remote-access.md).

## View-only links: what they do and don't do

A view-only link hides the Download button and refuses the download address. It is a courtesy, **not protection**: the browser still receives the file to show it, so anyone determined can save it or record the screen. Use it to avoid casual saving, never for something that must not be copied.

## What clients can preview

The browser shows the file itself, never a converted copy. If the browser can't show a file, the client downloads it.

| Type | In the browser | Otherwise |
|---|---|---|
| Images | PNG, JPEG, GIF, WebP, AVIF | HEIC, RAW, PSD and others: download |
| Video | MP4 or WebM the browser can play, with seeking | Other formats and codecs: download |
| Audio | MP3, AAC/M4A, Ogg, WAV, FLAC the browser supports | Download |
| PDF | The browser's own viewer (drawn page by page on view-only links) | Download |
| Text | Up to 2 MB | Download |
| Everything else (archives, documents, design files, software projects) | Not previewed | Download |

Handoff never runs uploaded code. HTML and SVG files are shown as plain text.

## Your data

Everything is in one place: `%LOCALAPPDATA%\Handoff` on Windows (`~/Library/Application Support/Handoff` on macOS, `~/.local/share/handoff` on Linux).

- `data/` holds the database and your original files.
- `keys/` holds the keys that let Handoff show an old link again. **Keys are kept outside `data/` and are never included in backups.**
- `logs/` holds a log for troubleshooting.

Backups and restores are in [docs/backup-restore.md](docs/backup-restore.md). After restoring on a new computer, links you already sent keep working, but Handoff can't show their text again; create a new link when you need to copy one.

## What works and what is still untested

| Feature | State |
|---|---|
| Upload, storage as uploaded, SHA-256, preview, direct download, range requests | **Working and tested** (automated tests, plus a live 1 GiB upload and download earlier in development) |
| Private links: revoke, password, expiry, download limit, view-only | **Working and tested** |
| Recoverable links (copy a link again), keys kept out of backups | **Working and tested** |
| Desktop launcher: starts everything, dashboard, status bar, Stop sharing, Quit, one copy at a time | **Working and tested on Windows**, including the packaged `Handoff.exe` |
| Same-Wi-Fi sharing | **Working** on Windows: the link opened and downloaded through this computer's own network address. **Not tested from a different device.** |
| Quick Share (temporary tunnel) | **Tested live on Windows:** the helper was downloaded and checked, a public address came up, and the page loaded and a file downloaded through it. A phone opening a view-only link over it was also seen working. Not tested across many networks or over time. |
| Your own address | **Tested with a simulated check only.** Needs manual testing with a real address. |
| Tailscale Funnel | **Simulated only.** Not tested against a real Tailscale. |
| System tray icon | Starts without errors on Windows; clicking its menu has **not** been tested by a person. |
| macOS and Linux | **Packaging is prepared, not built or tested.** |
| Signed or notarized builds | **No.** Builds are unsigned; see [docs/unsigned-builds.md](docs/unsigned-builds.md). |

## FAQ

**Do my clients need an account or to install anything?** No. They open the link in a browser.

**Is it free?** Yes: no subscription, domain or paid service is required. A license has not been chosen yet, so for now the code isn't licensed for reuse.

**Can my client download huge files?** Yes, as long as your computer stays on and online. Speed depends on your home internet's upload speed, and a tunnel service may add its own limits.

**Can I use it on a server instead?** Yes, with `python -m handoff` (no Docker files are shipped). See "For developers".

## For developers

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
python -m handoff desktop     # the desktop launcher, from source
python -m handoff             # server mode: two ports, set PUBLIC_BASE_URL yourself
python packaging/build.py     # build the desktop app for this operating system
```

- Layout: `handoff/` (backend, launcher, sharing manager), `handoff/sharing/` (connection methods), `packaging/` (PyInstaller), `tests/`, `site/` (the project's landing page).
- Server mode keeps the two-port design: the owner dashboard on `127.0.0.1`, the share service on its own port. Settings are in [.env.example](.env.example).
- Security notes: [SECURITY.md](SECURITY.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

**Not chosen yet.** Until a license file is added, the code is not licensed for reuse.
