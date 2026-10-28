"""Writes packaging/handoff.ico and handoff.png from the same drawing the tray icon uses.

The 16 and 32 px frames are drawn on whole pixels (see handoff.desktop.make_icon_image), not shrunk from the big one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from handoff.desktop import make_icon_image  # noqa: E402

here = Path(__file__).parent
sizes = [16, 32, 48, 64, 128, 256]
frames = [make_icon_image(s) for s in sizes]
frames[-1].save(here / "handoff.png")
frames[-1].save(here / "handoff.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
print("wrote", here / "handoff.ico")
