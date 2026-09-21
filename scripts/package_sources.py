"""Create a reviewable source archive, excluding tools, credentials and build output."""

import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
release = root / "releases"
release.mkdir(exist_ok=True)
version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
archive = release / f"ScholarMate-source-{version}.zip"
excluded = {"__pycache__", "target", "binaries", "gen", ".pytest_cache", ".ruff_cache"}
files = []
for folder in ["src", "src-tauri", "scripts", "docs", ".github"]:
    files.extend(
        p
        for p in (root / folder).rglob("*")
        if p.is_file() and not excluded.intersection(p.relative_to(root).parts)
    )
for filename in [
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.ts",
    "index.html",
    "components.json",
    "pyproject.toml",
    "README.md",
    ".gitignore",
    ".python-version",
]:
    files.append(root / filename)
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
    for file in sorted(set(files)):
        output.write(file, Path("ScholarMate") / file.relative_to(root))
checksums = []
for file in sorted(release.iterdir()):
    if file.suffix in (".zip", ".msi"):
        checksums.append(hashlib.sha256(file.read_bytes()).hexdigest() + "  " + file.name)
(release / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
print(f"Created {archive.name}: {len(files)} source files")

