# Security

## Reporting a problem

Please report vulnerabilities privately to the maintainer rather than in a public issue. (Contact address to be added when the repository is published.)

## What Handoff does

- **Links:** 256-bit random tokens. Visitors are looked up by SHA-256 hash, and every request checks the database, so revoking works immediately. Unknown, revoked and expired links show the same page.
- **Recoverable links:** so you can copy a link again after a temporary address changes, each link's secret is also stored encrypted (Fernet, from the `cryptography` package). The key lives in a separate `keys` folder that is never included in backups. This protects a copied database or backup. It does **not** protect a computer that is already compromised, because the key and database are on the same machine.
- **Desktop mode:** the dashboard and share service run in one program. The share service listens on this computer only unless you choose Same Wi-Fi or Your own address; direct connections from other computers are refused otherwise. While sharing is stopped, visitors get a "paused" page.
- **Tunnels:** only the share service is ever given to a tunnel, never the dashboard. The `cloudflared` helper is downloaded only after you agree and is refused unless it matches a pinned SHA-256. Pages ask search engines not to index them, because temporary public addresses have been reported appearing in search results.
- **Forwarded addresses:** a tunnel's client-address header is trusted only when it comes from the local tunnel process itself.
- **Passwords:** scrypt (standard library). Wrong-password attempts are rate limited.
- **Two ports:** the owner dashboard is published on `127.0.0.1` only. The share service has no owner routes and no upload routes.
- **Owner dashboard:** sign-in required, `SameSite=Strict` session cookie, CSRF token on every change, and the `Host` and `Origin` headers are checked, which blocks a malicious web page from driving a dashboard running on your computer.
- **Files:** stored under random ids; the uploaded filename is only a label and never part of a path. Content type is sniffed from the bytes. Only a short allowlist (images, MP4/WebM, audio, PDF, plain text) is shown inline. HTML and SVG are served as text with `nosniff` and a sandboxing policy, never rendered.
- **Code:** Handoff never executes uploaded files.

## What it does not do

- It is **not code-signed or notarized**. See "Unsigned downloads" in the README; "unsigned" means nobody has verified the app, and the project makes no such claim.
- It cannot stop a client from keeping, sharing or re-uploading what they download. **View-only links are not protection**; the browser receives the file.
- It does not scan uploads for malware.
- It does not verify who opens a link. Anyone who has the link (and the password, if set) can open it.
- It does not provide end-to-end encryption. A tunnel provider that ends HTTPS can see traffic.

## Limits of hosting from a laptop

Availability depends on your computer and network. Your upload speed limits every download. Anything you expose is exposed from your home or office network, so keep the system updated and expose only the share port. Plain-HTTP links on a shared network can be read by others on it.

## Hardening checklist

- Keep `OWNER_PORT` bound to `127.0.0.1` (the default).
- Use HTTPS for any link that leaves your network.
- Add a password and an expiry to links that matter; revoke links when the work is delivered.
- Back up `./data` and test a restore.
