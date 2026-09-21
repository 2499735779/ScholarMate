"""Run using the project Python 3.11 virtual environment, on each target OS."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
triple = subprocess.check_output(["rustc", "--print", "host-tuple"], text=True).strip()
subprocess.run(
    [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "scholarmate-backend",
        "--paths",
        str(root / "src-tauri/python"),
        "--collect-all",
        "keyring",
        "--hidden-import",
        "keyring.backends.Windows" if os.name == "nt" else "keyring.backends.macOS",
        "--collect-all",
        "reportlab",
        "--distpath",
        str(root / "build/sidecar"),
        "--workpath",
        str(root / "build/pyinstaller"),
        str(root / "src-tauri/python/main.py"),
    ],
    cwd=root,
    check=True,
)
extension = ".exe" if os.name == "nt" else ""
destination = root / "src-tauri/binaries" / f"scholarmate-backend-{triple}{extension}"
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / "build/sidecar" / ("scholarmate-backend" + extension), destination)
print("Sidecar ready:", destination)

