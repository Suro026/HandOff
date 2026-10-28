# PyInstaller spec. Build from the project root:  python packaging/build.py
# One-folder build, no console window. The same spec is used for Windows, macOS and Linux; only Windows has been tested.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
icon = root / "packaging" / ("handoff.ico" if sys.platform == "win32" else "handoff.png")

hidden = collect_submodules("uvicorn") + collect_submodules("pystray") + ["h11"]
datas = [
    (str(root / "handoff" / "templates"), "handoff/templates"),
    (str(root / "handoff" / "static"), "handoff/static"),
    (str(root / "handoff" / "sharing" / "cloudflared_pins.json"), "handoff/sharing"),
]

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "httpx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Handoff",
    console=False,  # a normal desktop app: no terminal window
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Handoff")
