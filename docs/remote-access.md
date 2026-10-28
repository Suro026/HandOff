# Letting clients reach your links

Handoff runs on your computer. **When your computer is off, asleep or offline, nobody can open your links**, and they work again when Handoff is running and online. That is intended: your computer is the host, and Handoff doesn't run any server of its own that could keep your files online for you.

Only the **sharing port** ever needs to be reachable. Handoff never exposes the owner dashboard, and the desktop app picks and manages its own ports.

## The four methods

In the desktop app, open **Sharing settings** and choose one. The status bar shows **Sharing online** only after Handoff has fetched its own link through the public address and confirmed it reaches this very running copy.

### 1. Quick Share (temporary)

Handoff downloads Cloudflare's `cloudflared` (once, after you agree, checked against a pinned SHA-256) and opens a free "quick tunnel". That gives an `https://something.trycloudflare.com` address with no account, domain or router setup. Your computer connects *out* to Cloudflare, so it works behind home routers, NAT and most firewalls without opening any ports.

What Cloudflare's own documentation says (checked 2026-10-27, [source](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)):

- "Quick Tunnels are for testing and development."
- "Quick Tunnels have no uptime guarantee."
- Each quick tunnel supports up to 200 in-flight requests; extras get an error (429).
- Quick tunnels don't support Server-Sent Events. (Handoff doesn't use them.)
- The address is temporary and the hostname changes each time a new tunnel is created.

What that means for you:

- **The address changes** whenever Handoff restarts or has to reconnect. Handoff keeps your links' secret parts, so open the project and click **Copy link** to get the new address for the same link. Earlier copies you sent stop working.
- **Don't rely on it** for a delivery that must stay available. For that, use your own address.
- **Privacy:** traffic passes through Cloudflare, which ends HTTPS there and can in principle see it.
- **Bandwidth and usage limits** may apply and can change. I found no published bandwidth figure and make no promise.
- **I could not verify** whether Cloudflare's rules about serving large video or other non-web files through its network apply to tunnel traffic. The relevant restriction was [moved in 2023](https://blog.cloudflare.com/updated-tos/) and I couldn't read the current text. Check Cloudflare's current terms before delivering large media this way.
- **When your computer is off**, your client sees Cloudflare's error page, not a Handoff page. Handoff can't change that without running a relay, which would cost the maintainer money.

**Testing status:** the code is tested against a simulated tunnel only. The real download and a real public address have **not** been tried yet.

### 2. Same Wi-Fi

Handoff uses your computer's address on the local network, for example `http://192.168.1.20:8081`. Only people on that network can open it, and it is **not encrypted** (plain HTTP). While this method is on, Handoff listens on the network; it goes back to listening on this computer only when you stop sharing. Your firewall may ask you to allow it.

### 3. Your own address

If you have a web address, or a server, that forwards to this computer's sharing port, enter it. Handoff checks it before reporting online. You keep the address, HTTPS certificate and any port forwarding working. Some internet providers don't allow incoming connections (carrier-grade NAT), and a home address can change, so this works best with a server or a service you already manage.

### 4. Tailscale Funnel (advanced, optional)

If you already use Tailscale, Funnel can give a stable address like `your-computer.your-tailnet.ts.net`. Per Tailscale's [documentation](https://tailscale.com/docs/features/tailscale-funnel) (checked 2026-10-27):

- Visitors don't need Tailscale.
- You need Tailscale on this computer, with MagicDNS, HTTPS and the `funnel` policy attribute enabled for your tailnet.
- Funnel listens only on ports 443, 8443 and 10000.
- Traffic is subject to "non-configurable bandwidth limits", and no figures are published.

Handoff **only reads Tailscale's status** and shows you the command to run once (`tailscale funnel --bg <port>`). It never changes your Tailscale settings, because that could affect other things you share. I believe TLS ends on your computer with Funnel, but I haven't confirmed that.

**Testing status:** simulated only, not tested against a real Tailscale.

## Methods I looked at and don't ship

- **ngrok free plan:** its documentation lists [1 GB of outgoing data per month](https://ngrok.com/docs/pricing-limits/free-plan-limits) and a warning page shown to browser visitors, which is unsuitable for client downloads.
- **Opening a port on your router:** fails behind carrier-grade NAT, has no HTTPS without a domain, and exposes your network.
- **Cloudflare named tunnels:** stable, but they need a Cloudflare account and a domain on Cloudflare, which conflicts with "no domain required".

I did not research other tunnel services, so none are included or recommended.

## Things to tell your client

- Open the link in a normal browser app. Very large downloads can be unreliable inside some chat apps' built-in browsers.
- If it stops working, your computer may be off or offline. They can ask you.
- A big file takes as long as your home internet's upload speed allows.

## Server mode

Running `python -m handoff` (instead of the desktop app) has no connection manager. Put your address in `PUBLIC_BASE_URL` and expose only the share port, using a tunnel or proxy you run yourself. With a proxy you control, set `TRUST_PROXY_HEADERS=true` so rate limits and logs see real client addresses. Don't set it otherwise.
