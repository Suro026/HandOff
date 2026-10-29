"""Build the desktop app for the current operating system.

    pip install -r requirements-desktop.txt
    python packaging/build.py

Output goes to build-out/release: an archive plus its .sha256 file. The builds are NOT signed or notarized (see the
README). Build each operating system on that operating system.
"""
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from handoff import __version__  # noqa: E402

import os  # noqa: E402

out = root / "build-out"
release = out / "release"
# HANDOFF_DIST_NAME lets you build next to a copy that is currently running (which Windows keeps locked).
dist_name = os.environ.get("HANDOFF_DIST_NAME", "dist")


def main() -> None:
    subprocess.run([sys.executable, str(root / "packaging" / "make_icon.py")], check=True, cwd=root)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(root / "packaging" / "handoff.spec"), "--noconfirm",
         "--distpath", str(out / dist_name), "--workpath", str(out / "work")],
        check=True, cwd=root,
    )
    release.mkdir(parents=True, exist_ok=True)
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    arch = platform.machine().lower().replace("amd64", "x86_64")
    name = f"Handoff-{__version__}-{system}-{arch}"
    folder = out / dist_name / "Handoff"
    if system == "windows":
        archive = release / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob("*"):
                z.write(p, Path("Handoff") / p.relative_to(folder))
    else:
        archive = release / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            t.add(folder, arcname="Handoff")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Built {archive} ({archive.stat().st_size / 1e6:.1f} MB)\nSHA-256 {digest}")


if __name__ == "__main__":
    main()
