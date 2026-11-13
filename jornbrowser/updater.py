"""Updates via GitHub Releases: controleren, downloaden, checksum nakijken, vervangen."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    from ._version import VERSION
except ImportError:  # gestart als los script / PyInstaller
    from _version import VERSION  # type: ignore

REPO = "Jornduthoo/Jorn-browser"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE_NAME = "JornBrowser.exe"


def current_version() -> str:
    return VERSION


def build_number(version: str) -> int:
    """'1.0.17' of 'v1.0.17' -> 17. Ontwikkelversies -> 0."""
    m = re.fullmatch(r"v?\d+\.\d+\.(\d+)", version.strip())
    return int(m.group(1)) if m else 0


def is_installed_exe() -> bool:
    """Alleen de gebouwde .exe kan zichzelf bijwerken (niet de broncode)."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def check_latest(timeout: float = 10) -> dict | None:
    """Geeft info over een nieuwere versie, of None als je al de nieuwste hebt."""
    req = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "JornBrowser-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        rel = json.loads(resp.read().decode("utf-8"))
    tag = rel.get("tag_name", "")
    if build_number(tag) <= build_number(VERSION):
        return None
    asset = next((a for a in rel.get("assets", []) if a.get("name") == EXE_NAME), None)
    if not asset:
        return None
    digest = asset.get("digest") or ""
    notes = rel.get("body") or ""
    return {
        "version": tag.lstrip("v"),
        "url": asset["browser_download_url"],
        "size": asset.get("size", 0),
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
        "notes": notes.strip(),
    }


def download(info: dict, progress=None, timeout: float = 60) -> Path:
    """Download naar JornBrowser.new.exe naast de huidige exe en controleer de checksum."""
    target = exe_path().with_name("JornBrowser.new.exe")
    part = target.with_suffix(".part")
    h = hashlib.sha256()
    req = urllib.request.Request(info["url"], headers={"User-Agent": "JornBrowser-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or info.get("size") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if info.get("sha256") and h.hexdigest() != info["sha256"]:
        part.unlink(missing_ok=True)
        raise ValueError("Checksum klopt niet: de download is beschadigd of gewijzigd. Update afgebroken.")
    if part.stat().st_size < 1_000_000:
        part.unlink(missing_ok=True)
        raise ValueError("Download is onvolledig. Probeer later opnieuw.")
    os.replace(part, target)
    return target


def install_and_restart(new_exe: Path) -> None:
    """Huidige exe wegzetten als .old (mag op Windows terwijl ze draait), nieuwe
    op haar plaats zetten en starten. De oude wordt bij de volgende start gewist."""
    exe = exe_path()
    old = exe.with_name("JornBrowser.old.exe")
    old.unlink(missing_ok=True)
    os.replace(exe, old)
    try:
        os.replace(new_exe, exe)
    except OSError:
        os.replace(old, exe)  # terugdraaien
        raise
    subprocess.Popen([str(exe)], cwd=str(exe.parent),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def cleanup_after_update() -> None:
    if not is_installed_exe():
        return
    for name in ("JornBrowser.old.exe", "JornBrowser.new.part"):
        try:
            (exe_path().parent / name).unlink(missing_ok=True)
        except OSError:
            pass
