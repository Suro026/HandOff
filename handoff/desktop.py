"""Desktop launcher: one program that starts everything, opens the dashboard and shows the sharing status.

No terminals, no port settings. It picks free ports itself, keeps one copy running, and offers Stop sharing and Quit
from the tray icon (when the desktop has one) and from the dashboard.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .config import Settings
from .context import Context, build_context

log = logging.getLogger("handoff.desktop")
LOCK_PORT = int(os.environ.get("HANDOFF_LOCK_PORT", "47831"))


# --------------------------------------------------------------------- locations
def app_home() -> Path:
    """Where Handoff keeps its data, keys, helper download and log. Override with HANDOFF_HOME."""
    override = os.environ.get("HANDOFF_HOME", "").strip()
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Handoff"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Handoff"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "handoff"


def desktop_settings(home: Path, owner_port: int, share_port: int) -> Settings:
    return Settings(
        data_dir=home / "data",
        owner_bind="127.0.0.1",
        owner_port=owner_port,
        share_bind="127.0.0.1",
        share_port=share_port,
        key_dir_override=home / "keys",  # outside the data folder, so copying or backing up data never carries keys
    )


def pick_port(preferred: int) -> int:
    for candidate in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", candidate))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("No free network port found.")


class InstanceLock:
    """Only one Handoff per user. Holding a local port is the lock; it vanishes if the program is killed."""

    def __init__(self, port: int = LOCK_PORT):
        self.port = port
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(1)
        except OSError:
            s.close()
            return False
        self._sock = s
        return True

    def release(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None


# --------------------------------------------------------------------- services
class ServiceRunner:
    """Runs the owner dashboard and the share service in one background thread, in this one process."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self._stop: asyncio.Event | None = None
        self._share = None  # (server, task)
        self.share_bind = ctx.settings.share_bind

    def start(self, timeout: float = 20) -> None:
        self.thread = threading.Thread(target=self._thread_main, daemon=True, name="handoff-services")
        self.thread.start()
        if not self.ready.wait(timeout) or self.error:
            raise RuntimeError(f"The sharing service did not start: {self.error!r}")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as e:  # noqa: BLE001
            self.error = e
            log.exception("service thread failed")
            self.ready.set()

    @staticmethod
    def _make_server(app, host: str, port: int):
        import uvicorn

        # proxy_headers=False: uvicorn would otherwise replace the client address with X-Forwarded-For whenever the
        # request comes from 127.0.0.1, which is exactly how a local tunnel connects. Handoff then could not tell a
        # tunnel from another computer. Handoff reads forwarded addresses itself, only where it trusts them.
        return uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False,
                                             proxy_headers=False))

    async def _start_server(self, server) -> asyncio.Task:
        server.install_signal_handlers = lambda: None
        task = asyncio.create_task(server.serve())
        for _ in range(200):
            if server.started:
                return task
            if task.done():
                task.result()
            await asyncio.sleep(0.05)
        raise RuntimeError("A server did not start in time.")

    async def _main(self) -> None:
        from .owner_app import create_owner_app
        from .share_app import create_share_app

        s = self.ctx.settings
        self._stop = asyncio.Event()
        self._share_app = create_share_app(self.ctx)
        owner = self._make_server(create_owner_app(self.ctx), s.owner_bind, s.owner_port)
        owner_task = await self._start_server(owner)
        await self._start_share(self.share_bind)
        self.loop = asyncio.get_running_loop()
        self.ready.set()
        await self._stop.wait()
        await self._stop_share()
        owner.should_exit = True
        await owner_task

    async def _start_share(self, bind: str) -> None:
        server = self._make_server(self._share_app, bind, self.ctx.settings.share_port)
        task = await self._start_server(server)
        self._share, self.share_bind = (server, task), bind

    async def _stop_share(self) -> None:
        if self._share:
            server, task = self._share
            server.should_exit = True
            await task
            self._share = None

    async def _rebind(self, bind: str) -> None:
        if bind == self.share_bind and self._share:
            return
        await self._stop_share()
        await self._start_share(bind)
        log.info("share service now listens on %s:%s", bind, self.ctx.settings.share_port)

    def set_share_bind(self, bind: str) -> None:
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._rebind(bind), self.loop).result(15)

    def stop(self) -> None:
        if self.loop and self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
        if self.thread:
            self.thread.join(timeout=15)


# --------------------------------------------------------------------- tray
def status_line(ctx: Context) -> str:
    st = ctx.manager.status()
    names = {"online": "Sharing online", "connecting": "Connecting…", "reconnecting": "Reconnecting…",
             "offline": "Sharing offline", "failed": "Sharing problem"}
    line = names.get(st["state"], st["state"])
    if st["state"] == "online" and st["temporary"]:
        line += " (temporary address)"
    return f"Handoff: {line}"


_MARK_LIGHT = ((214, 58, 6, 255), (15, 139, 141, 255))     # #D63A06, #0F8B8D
_MARK_DARK = ((255, 138, 91, 255), (63, 208, 201, 255))    # #FF8A5B, #3FD0C9


def make_icon_image(size: int = 64, dark: bool = False):
    """The Handoff mark (two bars and a file, an H) on a transparent square.

    Drawn on a 64-unit grid: bars 14 wide and 52 tall, file 16, gaps 4, 6 units of room around it. At 32 and 16 px the
    mark is redrawn on whole pixels with 1 px gaps, so it stays sharp instead of being a blurred shrink of the big one.
    """
    from PIL import Image, ImageDraw

    a, b = _MARK_DARK if dark else _MARK_LIGHT
    if size in (16, 32):
        # (bar width, gap, file size, margin, corner radius)
        bw, gap, fs, margin, r = (3, 1, 4, 2, 0) if size == 16 else (6, 2, 8, 4, 1)
        top, height = margin, size - 2 * margin
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x2 = margin + bw + gap + fs + gap
        fy = top + (height - fs) // 2
        for box, colour in (((margin, top, margin + bw - 1, top + height - 1), a),
                            ((margin + bw + gap, fy, margin + bw + gap + fs - 1, fy + fs - 1), a),
                            ((x2, top, x2 + bw - 1, top + height - 1), b)):
            d.rounded_rectangle(box, radius=r, fill=colour) if r else d.rectangle(box, fill=colour)
        return img
    scale = 8
    big = size * scale
    k = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6 * k, 6 * k, 20 * k - 1, 58 * k - 1), radius=5 * k, fill=a)
    d.rounded_rectangle((24 * k, 24 * k, 40 * k - 1, 40 * k - 1), radius=2.5 * k, fill=a)
    d.rounded_rectangle((44 * k, 6 * k, 58 * k - 1, 58 * k - 1), radius=5 * k, fill=b)
    return img.resize((size, size), Image.LANCZOS)


def _taskbar_is_dark() -> bool:
    """Windows taskbar theme; assume dark where it can't be read (macOS and most Linux panels are dark or neutral)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 0
    except Exception:
        return True


class Tray:
    """A system tray icon, if this computer has pystray available. Otherwise the dashboard's Quit button is used."""

    def __init__(self, ctx: Context, open_dashboard, quit_app):
        import pystray

        self.ctx, self.stopped = ctx, threading.Event()
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: status_line(ctx), None, enabled=False),
            pystray.MenuItem("Open dashboard", lambda icon, item: open_dashboard(), default=True),
            pystray.MenuItem("Stop sharing", lambda icon, item: ctx.manager.stop(),
                             enabled=lambda item: ctx.manager.accepting()),
            pystray.MenuItem("Quit Handoff", lambda icon, item: quit_app()),
        )
        self.icon = pystray.Icon("handoff", make_icon_image(64, dark=_taskbar_is_dark()), status_line(ctx), menu)

    def run(self) -> None:
        def refresh():
            while not self.stopped.wait(2):
                try:
                    self.icon.title = status_line(self.ctx)[:120]
                    self.icon.update_menu()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=refresh, daemon=True).start()
        self.icon.run()

    def stop(self) -> None:
        self.stopped.set()
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------- main
def _setup_logging(home: Path) -> None:
    (home / "logs").mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(home / "logs" / "handoff.log", encoding="utf-8")]
    if sys.stderr is not None:  # a windowed Windows build has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _wait_for_dashboard(port: int, timeout: float = 20) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/session", timeout=2):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handoff-desktop")
    parser.add_argument("--no-browser", action="store_true", help="don't open the dashboard automatically")
    parser.add_argument("--no-tray", action="store_true", help="don't show a tray icon")
    args = parser.parse_args(argv)

    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    _setup_logging(home)
    lock = InstanceLock()
    run_file = home / "run.json"
    if not lock.acquire():
        # Already running: just bring the dashboard up instead of starting a second copy.
        try:
            port = json.loads(run_file.read_text())["owner_port"]
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{port}")
            print(f"Handoff is already running. Dashboard: http://localhost:{port}")
        except (OSError, ValueError, KeyError):
            print("Handoff seems to be running already.")
        return 0

    settings = desktop_settings(home, pick_port(8080), pick_port(8081))
    ctx = build_context(settings, gate_sharing=True)
    runner = ServiceRunner(ctx)
    quit_event = threading.Event()
    tray: Tray | None = None

    def request_quit() -> None:
        log.info("quit requested")
        quit_event.set()
        if tray:
            tray.stop()

    def open_dashboard() -> None:
        webbrowser.open(f"http://localhost:{settings.owner_port}")

    ctx.on_quit = request_quit
    ctx.share_bind_hook = runner.set_share_bind
    # Start listening beyond this computer only if the method used last time needs it.
    if ctx.manager.wants_network_listener(ctx.manager.saved_provider()):
        runner.share_bind = "0.0.0.0"
    try:
        runner.start()
        run_file.write_text(json.dumps({"owner_port": settings.owner_port, "share_port": settings.share_port,
                                        "pid": os.getpid(), "version": __version__}))
        if not _wait_for_dashboard(settings.owner_port):
            raise RuntimeError("The dashboard did not start.")
        ctx.manager.resume_saved()
        log.info("Handoff %s running: dashboard on port %s, share service on port %s",
                 __version__, settings.owner_port, settings.share_port)
        if not args.no_browser:
            open_dashboard()
        if not args.no_tray:
            try:
                tray = Tray(ctx, open_dashboard, request_quit)
            except Exception as e:  # noqa: BLE001 - no tray library or no tray on this desktop
                log.info("no tray icon (%s); use the dashboard's Quit button", type(e).__name__)
        if tray:
            tray.run()  # blocks until Quit
            quit_event.set()
        else:
            while not quit_event.wait(0.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        log.info("shutting down")
        try:
            ctx.manager.stop()
        finally:
            runner.stop()
            run_file.unlink(missing_ok=True)
            lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
