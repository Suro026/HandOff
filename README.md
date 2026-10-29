<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Handoff logo" width="96" height="96">
  </picture>
</p>

<h1 align="center">Handoff</h1>

Give your client your finished work, straight from your own computer.

Add your files, click **Create share link**, and send the link on WhatsApp, email or anywhere else. Your client opens it in a browser and previews or downloads the **original files**: nothing compressed, resized or watermarked.

- **Your computer is the host.** Files stay on your disk. Nothing is uploaded to a Handoff cloud, and there is no Handoff server.
- **Free, no account, no domain, no subscription.**
- **Private, revocable links.** Add a password, an expiry or a download limit. Stop a link, or all sharing, at any time.
- **Payment is between you and your client.** Handoff doesn't take, check or enforce payment.

> **Status: early development (v0.1).** Only the Windows app has been built and tested. See [what works](#what-works-and-what-is-still-untested).

## Download (Windows)

You don't need any technical knowledge. About 2 minutes.

1. Open the **[Releases page](https://github.com/Suro026/HandOff/releases/latest)**.
2. Under **Assets**, click **`Handoff-0.1.0-windows-x86_64.zip`**. It downloads (about 30 MB).
3. Open your Downloads folder, right-click the zip and choose **Extract All**. When it asks where, type a **short folder** such as `C:\Handoff`. Don't extract into a deep folder: Windows can then say "Failed to load Python DLL ... filename or extension is too long".
4. Open `C:\Handoff\Handoff` and double-click **`Handoff.exe`**.
5. Windows may show a blue **"Windows protected your PC"** box, because this app is not signed (see [Unsigned downloads](#unsigned-downloads)). Click **More info**, then **Run anyway**.
6. Handoff opens in your browser and adds an icon near the clock. The first time, create a username and password for this computer.

That's it. To close Handoff, click **Quit Handoff** in the dashboard or use the icon near the clock.

**macOS and Linux:** builds are prepared but **not tested yet**, so they are not listed as supported. You can run Handoff from source on any system, see [For developers](#for-developers).

## Share your work

1. **Create a project** and give it a name.
2. **Add the finished files.** Drag them in or choose them.
3. Choose **Access**: "View and download originals" or "View only" (see the limits below). Add a password or an expiry if you like.
4. Click **Create share link.**
   - The first time, Handoff asks how your client will reach you. Pick one (next section).
   - The bar at the top shows **Sharing online** only once Handoff has proven the link works.
5. **Copy the link** (the copy icon) and send it. Your client opens it in a browser, with nothing to install.

To change your mind: **Revoke** kills one link, **Stop sharing** closes everything at once, **Quit Handoff** shuts it all down.

## What you need to know first

- **Your computer has to be on, awake and online** while your client opens the link. If it's off, asleep or disconnected, the link doesn't work until it's back. That is by design: your computer is the host.
- **Handoff copies your files** into its own storage folder. Your originals stay where they are, so a 40 GB project uses about 40 GB of extra disk. Handoff tells you before it copies large files.
- **Quick Share links are temporary.** See the next section.

## Choosing how clients reach you

| Method | Setup | Good for | Honest limits |
|---|---|---|---|
| **Quick Share** | None, one click | Handing something over soon | Temporary address that changes when Handoff restarts or reconnects. It uses Cloudflare's free quick tunnel, which Cloudflare describes as for testing and development with no uptime guarantee. Traffic passes through Cloudflare, which can in principle see it. Limits may change. |
| **Same Wi-Fi** | None | Someone in the same office or home | Only people on the same network. Not encrypted (plain HTTP). Your firewall may ask to allow Handoff. |
| **Your own address** | You supply it | A stable link, if you already have a web address or server | You keep that address and its HTTPS certificate working. |
| **Tailscale Funnel** (advanced) | Tailscale installed, one command | A stable address if you already use Tailscale | Bandwidth limits Tailscale doesn't publish. Handoff only reads its status; you run the one command it shows. |

**Why Cloudflare?** Your computer sits behind your home router, so a client's phone can't reach it directly. Quick Share starts a small helper (`cloudflared`) that connects *out* from your computer to Cloudflare and gives you an `https://…trycloudflare.com` address. It needs no account, domain or router setting, and costs nothing. The helper is downloaded **once, after you agree**, and Handoff refuses to run it unless its SHA-256 matches the value pinned in `handoff/sharing/cloudflared_pins.json`. That check protects against a corrupted download; it doesn't mean this project vouches for `cloudflared`.

When Quick Share's address changes, open the project and click **Copy link** for the new address. Earlier copies you sent stop working. Tell your client to open links in a normal browser; very large downloads can be unreliable inside some chat apps' built-in browsers.

## View-only links: what they do and don't do

A view-only link hides the Download button and refuses the download address. It is a courtesy, **not protection**: the browser still receives the file to show it, so anyone determined can save it or record the screen. Use it to avoid casual saving, never for something that must not be copied.

## What clients can preview

The browser shows the file itself, never a converted copy. If it can't show a file, the client downloads it.

| Type | In the browser | Otherwise |
|---|---|---|
| Images | PNG, JPEG, GIF, WebP, AVIF | HEIC, RAW, PSD and others: download |
| Video | MP4 or WebM the browser can play, with seeking | Other formats and codecs: download |
| Audio | MP3, AAC/M4A, Ogg, WAV, FLAC the browser supports | Download |
| PDF | The browser's own viewer (drawn page by page on view-only links) | Download |
| Text | Up to 2 MB | Download |
| Everything else (archives, documents, design files, software projects) | Not previewed | Download |

Handoff never runs uploaded code. HTML and SVG files are shown as plain text.

## Your data, backup and restore

Everything is in one place: `%LOCALAPPDATA%\Handoff` on Windows (`~/Library/Application Support/Handoff` on macOS, `~/.local/share/handoff` on Linux).

- `data/` holds the database and your original files. Original files never change once stored.
- `keys/` holds the keys that let Handoff show an old link again. **Keys are never included in backups.**
- `logs/` holds a log for troubleshooting.

Back up with `python -m handoff backup <folder>` (add `--db-only` if you copy `data/files/` yourself), restore with `python -m handoff restore <folder>` (add `--force` to replace an existing database), and check with `python -m handoff verify`. Each backup has a `MANIFEST.sha256`. After restoring on a new computer, links you already sent keep working, but Handoff can't show their text again; create a new link when you need to copy one.

## Unsigned downloads

The builds are **not code-signed or notarized**: signing needs a paid certificate, which this project doesn't have. "Unsigned" means nobody has verified the app, and Handoff doesn't claim otherwise. Clicking through Windows' warning means you trust this project and the page you downloaded from.

To check your download, compare its SHA-256 with the `.sha256` file next to it on the Releases page. In PowerShell: `Get-FileHash .\Handoff-0.1.0-windows-x86_64.zip`. A match shows the file wasn't damaged or swapped on the way; it doesn't prove the build is safe. For that, read the source or build it yourself (`python packaging/build.py`). Some antivirus programs are cautious about unsigned programs that open network connections; Handoff does (that is its purpose), only the ones described here.

## What works and what is still untested

| Feature | State |
|---|---|
| Upload, storage as uploaded, SHA-256, preview, direct download, range requests | **Working and tested** (automated tests, plus a live 1 GiB upload and download) |
| Private links: revoke, password, expiry, download limit, view-only | **Working and tested** |
| Recoverable links (copy a link again), keys kept out of backups | **Working and tested** |
| Desktop launcher: starts everything, dashboard, status bar, Stop sharing, Quit, one copy at a time | **Working and tested on Windows**, including the packaged `Handoff.exe` |
| Same-Wi-Fi sharing | **Working** on Windows through this computer's own network address. **Not tested from a different device.** |
| Quick Share (temporary tunnel) | **Tested live on Windows:** helper downloaded and checked, public address came up, page loaded and a file downloaded through it. A phone opening a view-only link over it was seen working. Not tested across many networks or over time. |
| Your own address | **Simulated check only.** Needs testing with a real address. |
| Tailscale Funnel | **Simulated only.** Not tested against a real Tailscale. |
| System tray icon | Starts without errors on Windows; its menu clicks have **not** been tested by a person. |
| macOS and Linux | **Build prepared, not built or tested.** |
| Signed or notarized builds | **No.** |

## FAQ

**Do my clients need an account or to install anything?** No. They open the link in a browser.

**Is it free?** Yes: no subscription, domain or paid service is required. The code is MIT licensed.

**Can my client download huge files?** Yes, as long as your computer stays on and online. Speed depends on your home internet's upload speed, and a tunnel service may add its own limits.

**Can I use it on a server instead?** Yes, with `python -m handoff`. See "For developers".

## For developers

```bash
git clone https://github.com/Suro026/HandOff.git
cd HandOff
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
python -m handoff desktop     # the desktop launcher, from source
python -m handoff             # server mode: two ports, set PUBLIC_BASE_URL yourself
python packaging/build.py     # build the desktop app for this operating system
```

Needs Python 3.12 or newer. macOS and Linux builds come from the **Build desktop apps** workflow (on a `v*` tag it attaches each build to the release); none has been tested.

- Layout: `handoff/` (backend, launcher, sharing manager), `handoff/sharing/` (connection methods), `packaging/` (PyInstaller), `tests/`, `site/` (the landing page).
- Server mode has no connection manager. Expose only the share port, through a tunnel or proxy you run. All settings are optional environment variables: `PUBLIC_BASE_URL` (the address clients open; empty means this computer only), `OWNER_PORT` and `SHARE_PORT` (8080 and 8081; the dashboard is always `127.0.0.1`), `MIN_FREE_BYTES` (default: larger of 2 GiB or 5% of the disk), `MAX_UPLOAD_BYTES` (no cap), `MAX_CONCURRENT_UPLOADS` (2), `TRUST_PROXY_HEADERS` (only behind a proxy you control), `OWNER_ALLOWED_HOSTS`.
- Security notes: [SECURITY.md](SECURITY.md).

## Support

Handoff is free and stays free. If it saved you time, you can [buy me a coffee](https://buymeacoffee.com/surajitsadu). It is optional and changes nothing in the app.

## License

[MIT](LICENSE). Copyright (c) 2026 Surajit Sadhukhan.
