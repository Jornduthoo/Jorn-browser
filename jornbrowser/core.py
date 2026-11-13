"""Kernlogica van Jorn Browser (geen GUI, zodat het los te testen is).

Een "identiteit" = een Chromium-proces met een gloednieuw, tijdelijk profiel
(geen cookies, cache, geschiedenis) en optioneel een eigen proxy (= ander IP).
"Nieuwe identiteit" sluit alles, wist de profielen en start opnieuw.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "JornBrowser"


# --------------------------------------------------------------------------- paden

def app_dir() -> Path:
    """Map naast de .exe (of naast de broncode). Hier staan config en extensies."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def extensions_dir() -> Path:
    d = data_dir() / "extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_root() -> Path:
    """Tijdelijke profielen. Alles hieronder wordt gewist."""
    d = Path(tempfile.gettempdir()) / APP_NAME / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- config

DEFAULT_CONFIG = {
    "chromium_path": "",
    # "none"  = geen proxy; je systeem-VPN (bv. VPN Unlimited) bepaalt het IP
    # "list"  = elke identiteit krijgt een proxy uit proxies.txt
    "proxy_mode": "none",
    "proxy_order": "random",  # of "sequential"
    "start_url": "about:blank",
    "check_url": "https://am.i.mullvad.net/",
    "block_webrtc_leak": True,
}


def config_path() -> Path:
    return data_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- chromium zoeken

def candidate_chromium_paths() -> list[Path]:
    env = os.environ
    cands: list[Path] = [
        app_dir() / "chromium" / "chrome.exe",  # portable naast de app
    ]
    for base in (env.get("LOCALAPPDATA"), env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)")):
        if base:
            cands.append(Path(base) / "Chromium" / "Application" / "chrome.exe")
    # Linux/macOS (handig om te testen)
    cands += [Path(p) for p in (
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )]
    return cands


def find_chromium(cfg: dict) -> Path | None:
    p = cfg.get("chromium_path")
    if p and Path(p).is_file():
        return Path(p)
    for c in candidate_chromium_paths():
        if c.is_file():
            return c
    return None


# --------------------------------------------------------------------------- proxies

def proxies_path() -> Path:
    return data_dir() / "proxies.txt"


PROXIES_TEMPLATE = """\
# Eén proxy per regel. Alles na # is commentaar (handig als label).
# Formaten:  socks5://host:poort   http://host:poort   https://host:poort
# Let op: Chromium ondersteunt GEEN gebruikersnaam/wachtwoord in de proxy.
#
# Tip (Mullvad): verbind met Mullvad (WireGuard) en klik in de app op
# "Mullvad-lijst ophalen". Dan krijgt elke identiteit een ander uitgangs-IP
# zonder dat je de VPN opnieuw moet verbinden.
#
# socks5://se-got-wg-socks5-001.relays.mullvad.net:1080   # Zweden
"""


@dataclass
class Proxy:
    url: str
    label: str = ""

    def display(self) -> str:
        return f"{self.label} ({self.url})" if self.label else self.url


PROXY_RE = re.compile(r"^(socks5|socks4|http|https)://[^\s/:@]+:\d{1,5}$", re.I)


def parse_proxies(text: str) -> list[Proxy]:
    out: list[Proxy] = []
    for raw in text.splitlines():
        line, _, comment = raw.partition("#")
        line = line.strip()
        if not line:
            continue
        if "://" not in line:
            line = "socks5://" + line
        if PROXY_RE.match(line):
            out.append(Proxy(line, comment.strip()))
    return out


def load_proxies() -> list[Proxy]:
    p = proxies_path()
    if not p.exists():
        p.write_text(PROXIES_TEMPLATE, encoding="utf-8")
    return parse_proxies(p.read_text(encoding="utf-8"))


MULLVAD_RELAYS_URL = "https://api.mullvad.net/www/relays/wireguard/"


def mullvad_socks_from_relays(relays: list[dict]) -> list[Proxy]:
    out = []
    for r in relays:
        if not r.get("active", True):
            continue
        host = r.get("socks_name")
        if not host:
            hn = r.get("hostname", "")
            m = re.match(r"^([a-z]{2}-[a-z]{3})-wg-(\d+)$", hn)
            if not m:
                continue
            host = f"{m.group(1)}-wg-socks5-{m.group(2)}.relays.mullvad.net"
        port = r.get("socks_port") or 1080
        label = ", ".join(x for x in (r.get("country_name"), r.get("city_name")) if x)
        out.append(Proxy(f"socks5://{host}:{port}", label))
    return out


def fetch_mullvad_proxies(timeout: float = 15) -> list[Proxy]:
    req = urllib.request.Request(MULLVAD_RELAYS_URL, headers={"User-Agent": APP_NAME})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        relays = json.loads(resp.read().decode("utf-8"))
    return mullvad_socks_from_relays(relays)


def write_proxies(proxies: list[Proxy]) -> None:
    lines = [PROXIES_TEMPLATE.rstrip(), ""]
    lines += [f"{p.url}   # {p.label}" if p.label else p.url for p in proxies]
    proxies_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


class ProxyPicker:
    def __init__(self, order: str = "random"):
        self.order = order
        self._i = 0
        self._last: str | None = None

    def pick(self, proxies: list[Proxy]) -> Proxy | None:
        if not proxies:
            return None
        if self.order == "sequential":
            p = proxies[self._i % len(proxies)]
            self._i += 1
        else:
            choices = [p for p in proxies if p.url != self._last] or proxies
            p = random.choice(choices)
        self._last = p.url
        return p


# --------------------------------------------------------------------------- extensies

WEBSTORE_ID_RE = re.compile(r"\b([a-p]{32})\b")


def extract_extension_id(text: str) -> str | None:
    """Haalt de ID uit een Chrome Web Store-link of een losse ID."""
    m = WEBSTORE_ID_RE.search(text.strip())
    return m.group(1) if m else None


def crx_download_url(ext_id: str, prodversion: str = "131.0.0.0") -> str:
    return (
        "https://clients2.google.com/service/update2/crx?response=redirect"
        f"&prodversion={prodversion}&acceptformat=crx2,crx3"
        f"&x=id%3D{ext_id}%26uc"
    )


def crx_to_zip_bytes(data: bytes) -> bytes:
    """Strip de CRX-header (v2 of v3) en geef de zip terug."""
    if data[:4] == b"PK\x03\x04":
        return data
    if data[:4] != b"Cr24":
        raise ValueError("Geen geldig CRX-bestand ontvangen.")
    version = struct.unpack("<I", data[4:8])[0]
    if version == 3:
        header_len = struct.unpack("<I", data[8:12])[0]
        return data[12 + header_len:]
    if version == 2:
        pk_len, sig_len = struct.unpack("<II", data[8:16])
        return data[16 + pk_len + sig_len:]
    raise ValueError(f"Onbekende CRX-versie {version}.")


def install_extension_from_crx(data: bytes, ext_id: str) -> Path:
    """Pakt een CRX uit in data/extensions/<id> (uitgepakt = laadbaar met --load-extension)."""
    target = extensions_dir() / ext_id
    tmp = extensions_dir() / f".{ext_id}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(crx_to_zip_bytes(data))) as zf:
        for member in zf.namelist():  # bescherming tegen ../ in zip-paden
            dest = (tmp / member).resolve()
            if not str(dest).startswith(str(tmp.resolve())):
                raise ValueError("Onveilig pad in extensie-archief.")
        zf.extractall(tmp)
    # Mappen die met _ beginnen (bv. _metadata) weigert Chromium bij uitgepakte extensies.
    for child in tmp.iterdir():
        if child.name.startswith("_") and child.name != "_locales":
            shutil.rmtree(child, ignore_errors=True)
    if not (tmp / "manifest.json").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("Geen manifest.json in de extensie.")
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return target


def download_extension(ext_id: str, timeout: float = 30) -> Path:
    req = urllib.request.Request(crx_download_url(ext_id), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise ValueError("Lege download: bestaat de extensie nog in de Web Store?")
    return install_extension_from_crx(data, ext_id)


@dataclass
class Extension:
    path: Path
    name: str
    enabled: bool


def _manifest_name(ext_path: Path) -> str:
    try:
        m = json.loads((ext_path / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ext_path.name
    name = m.get("name", ext_path.name)
    if name.startswith("__MSG_") and name.endswith("__"):
        key = name[6:-2]
        loc = m.get("default_locale", "en")
        try:
            msgs = json.loads((ext_path / "_locales" / loc / "messages.json").read_text(encoding="utf-8-sig"))
            for k, v in msgs.items():
                if k.lower() == key.lower():
                    return v.get("message", name)
        except (OSError, ValueError):
            pass
    return name


def list_extensions() -> list[Extension]:
    out = []
    for d in sorted(extensions_dir().iterdir()):
        if d.is_dir() and not d.name.startswith(".") and (d / "manifest.json").is_file():
            out.append(Extension(d, _manifest_name(d), not (d / ".disabled").exists()))
    return out


def set_extension_enabled(ext: Extension, enabled: bool) -> None:
    flag = ext.path / ".disabled"
    if enabled:
        flag.unlink(missing_ok=True)
    else:
        flag.write_text("", encoding="utf-8")


def remove_extension(ext: Extension) -> None:
    shutil.rmtree(ext.path, ignore_errors=True)


# --------------------------------------------------------------------------- identiteiten

def build_args(chromium: Path, profile: Path, proxy: Proxy | None,
               extensions: list[Path], cfg: dict) -> list[str]:
    args = [
        str(chromium),
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--new-window",
    ]
    disable_features = []
    if extensions:
        args.append("--load-extension=" + ",".join(str(e) for e in extensions))
        # Nodig in nieuwere Chromium-versies om --load-extension toe te laten.
        disable_features.append("DisableLoadExtensionCommandLineSwitch")
    if disable_features:
        args.append("--disable-features=" + ",".join(disable_features))
    if proxy:
        args.append(f"--proxy-server={proxy.url}")
        # Lokale adressen niet via de proxy; DNS gaat bij socks5 via de proxy.
        args.append("--proxy-bypass-list=<-loopback>")
    if cfg.get("block_webrtc_leak", True):
        # Voorkomt dat WebRTC je echte IP lekt buiten de proxy/VPN om.
        args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
        args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")
    args.append(cfg.get("start_url") or "about:blank")
    return args


def wipe_dir(path: Path, attempts: int = 20) -> bool:
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.15)  # Windows houdt bestanden even vast na het sluiten
    return False


@dataclass
class Identity:
    number: int
    profile: Path
    proxy: Proxy | None
    process: subprocess.Popen

    def alive(self) -> bool:
        return self.process.poll() is None

    def describe(self) -> str:
        via = self.proxy.display() if self.proxy else "systeem-VPN / directe verbinding"
        return f"Identiteit #{self.number} via {via}"


@dataclass
class IdentityManager:
    cfg: dict
    identities: list[Identity] = field(default_factory=list)
    counter: int = 0

    def __post_init__(self):
        self.picker = ProxyPicker(self.cfg.get("proxy_order", "random"))
        self.cleanup_leftovers()

    def cleanup_leftovers(self) -> None:
        """Wis profielen die een vorige sessie (bv. na een crash) achterliet."""
        active = {i.profile for i in self.identities}
        for d in profiles_root().iterdir():
            if d not in active:
                wipe_dir(d, attempts=1)

    def spawn(self, url: str | None = None) -> Identity:
        chromium = find_chromium(self.cfg)
        if not chromium:
            raise FileNotFoundError("Chromium niet gevonden. Kies chrome.exe via Instellingen.")
        proxy = None
        if self.cfg.get("proxy_mode") == "list":
            self.picker.order = self.cfg.get("proxy_order", "random")
            proxy = self.picker.pick(load_proxies())
            if proxy is None:
                raise ValueError("Proxy-modus staat aan, maar proxies.txt is leeg.")
        self.counter += 1
        profile = Path(tempfile.mkdtemp(prefix=f"id{self.counter}-", dir=profiles_root()))
        exts = [e.path for e in list_extensions() if e.enabled]
        args = build_args(chromium, profile, proxy, exts, self.cfg)
        if url:
            args[-1] = url
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        ident = Identity(self.counter, profile, proxy, proc)
        self.identities.append(ident)
        return ident

    def close(self, ident: Identity) -> None:
        if ident.alive():
            if os.name == "nt":
                # Hele procesboom van Chromium afsluiten.
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(ident.process.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                ident.process.terminate()
            try:
                ident.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ident.process.kill()
        wipe_dir(ident.profile)
        if ident in self.identities:
            self.identities.remove(ident)

    def close_all(self) -> None:
        for ident in list(self.identities):
            self.close(ident)

    def new_identity(self, url: str | None = None) -> Identity:
        """Alles sluiten en wissen, dan één verse identiteit starten."""
        self.close_all()
        return self.spawn(url)

    def reap(self) -> list[Identity]:
        """Ruim identiteiten op waarvan de gebruiker het venster zelf sloot."""
        gone = [i for i in self.identities if not i.alive()]
        for i in gone:
            self.close(i)
        return gone
