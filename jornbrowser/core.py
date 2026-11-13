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
    # "vpn"   = ingebouwde VPN: elke identiteit een eigen WireGuard-tunnel (data/vpn/*.conf)
    "proxy_mode": "vpn",
    "proxy_order": "random",  # of "sequential"
    "start_url": "https://duckduckgo.com/",
    "check_url": "https://am.i.mullvad.net/",
    "block_webrtc_leak": True,
    # Zoekmachine voor de adresbalk (via een ingebouwde extensie, zoals Tor Browser)
    "search_engine": "DuckDuckGo",
    # Bij het opstarten kijken of er een nieuwe versie op GitHub staat
    "auto_update_check": True,
    # Plakken in de DevTools-console zonder eerst "allow pasting" te typen
    "devtools_allow_paste": True,
}


# Zoekmachines die met een VPN (bijna) nooit captchas tonen.
START_PAGES = {
    "DuckDuckGo": "https://duckduckgo.com/",
    "Startpage (Google-resultaten, privé)": "https://www.startpage.com/",
    "Brave Search": "https://search.brave.com/",
    "Leeg (about:blank)": "about:blank",
}


# Zoekmachine in de adresbalk. "Google" = Chromium-standaard (geen override).
SEARCH_ENGINES = {
    "DuckDuckGo": {
        "keyword": "ddg",
        "search_url": "https://duckduckgo.com/?q={searchTerms}",
        "suggest_url": "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
        "favicon_url": "https://duckduckgo.com/favicon.ico",
    },
    "Startpage": {
        "keyword": "sp",
        "search_url": "https://www.startpage.com/sp/search?query={searchTerms}",
        "favicon_url": "https://www.startpage.com/favicon.ico",
    },
    "Brave Search": {
        "keyword": "brave",
        "search_url": "https://search.brave.com/search?q={searchTerms}",
        "favicon_url": "https://search.brave.com/favicon.ico",
    },
    "Google": None,
}


def config_path() -> Path:
    return data_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if cfg.get("config_version", 1) < 2:
        # v2: standaard-startpagina wordt DuckDuckGo i.p.v. een lege pagina
        if cfg.get("start_url") in ("", "about:blank"):
            cfg["start_url"] = DEFAULT_CONFIG["start_url"]
        cfg["config_version"] = 2
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


# --------------------------------------------------------------------------- ingebouwde VPN
#
# Elke identiteit krijgt een eigen WireGuard-tunnel, gedraaid door wireproxy
# (een kleine WireGuard-client zonder installatie of adminrechten). wireproxy
# biedt de tunnel lokaal aan als SOCKS5-proxy en alleen Chromium gaat erdoor.
# Valt de tunnel weg, dan kan Chromium nergens meer heen: je echte IP lekt niet.

def vpn_dir() -> Path:
    d = data_dir() / "vpn"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_vpn_configs() -> list[Path]:
    return sorted(p for p in vpn_dir().glob("*.conf") if p.is_file())


def import_vpn_configs(paths: list[str | Path]) -> int:
    """Kopieert .conf-bestanden (of .conf's uit een .zip) naar data/vpn."""
    n = 0
    for src in map(Path, paths):
        if src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".conf") and not name.endswith("/"):
                        text = zf.read(name).decode("utf-8-sig", errors="replace")
                        sanitize_wg_config(text)  # gooit een fout als het geen WireGuard is
                        (vpn_dir() / Path(name).name).write_text(text, encoding="utf-8")
                        n += 1
        elif src.suffix.lower() == ".conf":
            text = src.read_text(encoding="utf-8-sig", errors="replace")
            sanitize_wg_config(text)
            (vpn_dir() / src.name).write_text(text, encoding="utf-8")
            n += 1
    return n


WG_ALLOWED_KEYS = {
    "interface": {"privatekey", "address", "dns", "mtu", "listenport"},
    "peer": {"publickey", "presharedkey", "endpoint", "allowedips", "persistentkeepalive"},
}
WG_KEY_CASE = {
    "privatekey": "PrivateKey", "address": "Address", "dns": "DNS", "mtu": "MTU",
    "listenport": "ListenPort", "publickey": "PublicKey", "presharedkey": "PresharedKey",
    "endpoint": "Endpoint", "allowedips": "AllowedIPs", "persistentkeepalive": "PersistentKeepalive",
}


def sanitize_wg_config(text: str) -> str:
    """Houdt alleen de WireGuard-velden over die wireproxy begrijpt."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(\w+)\]$", line)
        if m:
            sections.append((m.group(1).lower(), []))
            continue
        if "=" in line and sections:
            k, v = line.split("=", 1)
            k = k.strip().lower()
            if k in WG_ALLOWED_KEYS.get(sections[-1][0], set()):
                sections[-1][1].append((WG_KEY_CASE[k], v.strip()))
    iface = [kv for name, kv in sections if name == "interface"]
    peers = [kv for name, kv in sections if name == "peer"]
    if len(iface) != 1 or not peers:
        raise ValueError("Geen geldig WireGuard-bestand ([Interface] en [Peer] nodig).")
    ikeys = {k for k, _ in iface[0]}
    if not {"PrivateKey", "Address"} <= ikeys:
        raise ValueError("WireGuard-bestand mist PrivateKey of Address.")
    for peer in peers:
        if not {"PublicKey", "Endpoint"} <= {k for k, _ in peer}:
            raise ValueError("WireGuard-bestand mist PublicKey of Endpoint bij [Peer].")
    if "DNS" not in ikeys:
        iface[0].append(("DNS", "1.1.1.1"))  # DNS gaat ook door de tunnel
    out = ["[Interface]"] + [f"{k} = {v}" for k, v in iface[0]]
    for peer in peers:
        out += ["", "[Peer]"] + [f"{k} = {v}" for k, v in peer]
    return "\n".join(out) + "\n"


def wireproxy_config(wg_text: str, port: int) -> str:
    return sanitize_wg_config(wg_text) + f"\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n"


def _stable_wireproxy(bundled: Path) -> Path:
    """Kopieer de meegebundelde wireproxy naar een VASTE plek (data/bin).
    De bundel staat elke start in een andere tijdelijke map (_MEIxxxx), waardoor
    Windows Firewall telkens opnieuw toestemming zou vragen."""
    import hashlib
    target = data_dir() / "bin" / bundled.name
    try:
        want = hashlib.sha256(bundled.read_bytes()).hexdigest()
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != want:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            shutil.copy2(bundled, tmp)
            os.replace(tmp, target)
        return target
    except OSError:
        # bv. bestand in gebruik door een open tunnel: gebruik wat er al staat
        return target if target.is_file() else bundled


def find_wireproxy() -> Path | None:
    exe = "wireproxy.exe" if os.name == "nt" else "wireproxy"
    cands = []
    if getattr(sys, "_MEIPASS", None):  # meegebundeld in JornBrowser.exe
        bundled = Path(sys._MEIPASS) / exe
        if bundled.is_file():
            return _stable_wireproxy(bundled)
    # Vangnet: de vaste kopie van een vorige start (data/bin)
    cands += [data_dir() / "bin" / exe, app_dir() / exe, app_dir() / "bin" / exe]
    for c in cands:
        if c.is_file():
            return c
    w = shutil.which("wireproxy")
    return Path(w) if w else None


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def socks5_probe(port: int, host: str = "1.1.1.1", dst_port: int = 443, timeout: float = 4) -> bool:
    """True als we via de lokale SOCKS5-proxy echt een verbinding naar buiten krijgen."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"\x05\x01\x00")
            if s.recv(2) != b"\x05\x00":
                return False
            s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(host) + struct.pack(">H", dst_port))
            reply = s.recv(10)
            return len(reply) >= 2 and reply[1] == 0
    except OSError:
        return False


class VpnTunnel:
    def __init__(self, conf: Path, workdir: Path):
        self.conf = conf
        self.name = conf.stem
        self.workdir = workdir
        self.port = 0
        self.process: subprocess.Popen | None = None

    def start(self, timeout: float = 12) -> None:
        exe = find_wireproxy()
        if not exe:
            raise FileNotFoundError("wireproxy niet gevonden (hoort naast/in JornBrowser.exe).")
        self.port = free_port()
        cfg_file = self.workdir / "tunnel.conf"
        cfg_file.write_text(wireproxy_config(self.conf.read_text(encoding="utf-8-sig"), self.port),
                            encoding="utf-8")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen([str(exe), "-s", "-c", str(cfg_file)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if socks5_probe(self.port):
                cfg_file.unlink(missing_ok=True)  # privésleutel niet laten rondslingeren
                return
            time.sleep(0.2)
        self.stop()
        raise ConnectionError(f"VPN-server '{self.name}' reageert niet.")

    @property
    def proxy(self) -> Proxy:
        return Proxy(f"socks5://127.0.0.1:{self.port}", f"VPN {self.name}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        (self.workdir / "tunnel.conf").unlink(missing_ok=True)


# --------------------------------------------------------------------------- ingebouwde zoek-extensie

def builtin_dir() -> Path:
    d = data_dir() / "builtin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def search_extension(cfg: dict) -> Path | None:
    """Maakt (of werkt bij) een mini-extensie die de zoekmachine van de adresbalk
    instelt. Geeft None bij "Google" (dan blijft Chromium standaard)."""
    name = cfg.get("search_engine", "DuckDuckGo")
    engine = SEARCH_ENGINES.get(name)
    target = builtin_dir() / "search"
    if not engine:
        shutil.rmtree(target, ignore_errors=True)
        return None
    provider = {"name": name, "encoding": "UTF-8", "is_default": True, **engine}
    manifest = {
        "manifest_version": 3,
        "name": f"Jorn Browser: zoeken via {name}",
        "version": "1.0",
        "description": "Laat de adresbalk zoeken via een privacyvriendelijke zoekmachine.",
        "chrome_settings_overrides": {"search_provider": provider},
    }
    text = json.dumps(manifest, indent=2)
    target.mkdir(parents=True, exist_ok=True)
    mf = target / "manifest.json"
    if not mf.exists() or mf.read_text(encoding="utf-8") != text:
        mf.write_text(text, encoding="utf-8")
    return target


# --------------------------------------------------------------------------- bladwijzers
#
# Eén centrale bladwijzerlijst (data/bookmarks/Bookmarks) voor alle identiteiten.
# Bij de start krijgt elk profiel een kopie; bij het sluiten gaan wijzigingen terug.

def bookmarks_master() -> Path:
    d = data_dir() / "bookmarks"
    d.mkdir(parents=True, exist_ok=True)
    return d / "Bookmarks"


def _digest(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def seed_profile(profile: Path) -> str:
    """Zet centrale bladwijzers in het profiel en toon de bladwijzerbalk altijd.
    Geeft een vingerafdruk van de bladwijzers bij de start terug."""
    default = profile / "Default"
    default.mkdir(parents=True, exist_ok=True)
    master = bookmarks_master()
    digest = ""
    if master.is_file():
        data = master.read_bytes()
        (default / "Bookmarks").write_bytes(data)
        digest = _digest(data)
    prefs_path = default / "Preferences"
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prefs = {}
    changed = False
    if prefs.get("bookmark_bar", {}).get("show_on_all_tabs") is not True:
        prefs.setdefault("bookmark_bar", {})["show_on_all_tabs"] = True
        changed = True
    pinned = load_pinned_extensions()
    if pinned and prefs.get("extensions", {}).get("pinned_extensions") != pinned:
        prefs.setdefault("extensions", {})["pinned_extensions"] = pinned
        changed = True
    if changed:
        prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
    return digest


# Vastgezette extensies (werkbalk) worden centraal onthouden, zoals bladwijzers.

def pinned_path() -> Path:
    return data_dir() / "pinned_extensions.json"


def load_pinned_extensions() -> list[str]:
    try:
        data = json.loads(pinned_path().read_text(encoding="utf-8"))
        return [x for x in data if isinstance(x, str)]
    except (OSError, ValueError, TypeError):
        return []


def sync_pinned_back(profile: Path) -> bool:
    """Lees na het sluiten welke extensies vastgezet waren en onthoud dat."""
    try:
        prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pinned = prefs.get("extensions", {}).get("pinned_extensions")
    if not isinstance(pinned, list) or pinned == load_pinned_extensions():
        return False
    pinned_path().write_text(json.dumps(pinned), encoding="utf-8")
    return True


def sync_bookmarks_back(profile: Path, start_digest: str) -> bool:
    """Schrijf gewijzigde bladwijzers van een (gesloten) profiel terug naar de centrale lijst."""
    f = profile / "Default" / "Bookmarks"
    try:
        data = f.read_bytes()
        json.loads(data)  # alleen geldige bestanden overnemen
    except (OSError, ValueError):
        return False
    if _digest(data) == start_digest:
        return False
    master = bookmarks_master()
    try:
        master_data = master.read_bytes()
    except OSError:
        master_data = b""
    if master_data and _digest(master_data) != start_digest:
        # Een ander venster schreef intussen ook bladwijzers weg: samenvoegen
        # (nieuwe adressen van dit venster toevoegen) i.p.v. overschrijven.
        try:
            data = _merge_bookmarks(json.loads(master_data), json.loads(data))
        except (ValueError, KeyError, TypeError):
            pass
    tmp = master.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, master)
    return True


def _iter_urls(node: dict):
    for child in node.get("children", []):
        if child.get("type") == "url":
            yield child.get("url")
        else:
            yield from _iter_urls(child)


def _merge_bookmarks(master: dict, mine: dict) -> bytes:
    known = {u for root in master["roots"].values() if isinstance(root, dict) for u in _iter_urls(root)}
    max_id = [0]

    def scan(node):
        try:
            max_id[0] = max(max_id[0], int(node.get("id", 0)))
        except ValueError:
            pass
        for c in node.get("children", []):
            scan(c)
    for root in master["roots"].values():
        if isinstance(root, dict):
            scan(root)

    def renumber(node):
        max_id[0] += 1
        node["id"] = str(max_id[0])
        for c in node.get("children", []):
            renumber(c)

    for key, root in mine["roots"].items():
        if not isinstance(root, dict) or key not in master["roots"]:
            continue
        for child in root.get("children", []):
            urls = set(_iter_urls(child)) if child.get("type") != "url" else {child.get("url")}
            if urls and not urls & known:
                renumber(child)
                master["roots"][key].setdefault("children", []).append(child)
                known |= urls
    master["checksum"] = ""  # Chromium berekent dit opnieuw
    return json.dumps(master, indent=3).encode("utf-8")


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
        # Lokale besturingspoort (willekeurig) zodat we netjes kunnen sluiten
        # bij "Bewaren"; webpagina's kunnen hier niet bij.
        "--remote-debugging-port=0",
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
    if cfg.get("devtools_allow_paste", True):
        args.append("--unsafely-disable-devtools-self-xss-warnings")
    if cfg.get("block_webrtc_leak", True):
        # Voorkomt dat WebRTC je echte IP lekt buiten de proxy/VPN om.
        args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
        args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")
    args.append(cfg.get("start_url") or "about:blank")
    return args


def cdp_browser_close(profile: Path, timeout: float = 3) -> bool:
    """Vraag Chromium netjes te sluiten (Browser.close via DevTools), zodat het
    cookies/logins naar schijf schrijft. De poort is alleen lokaal en willekeurig
    (--remote-debugging-port=0); webpagina's kunnen er niet bij (origin-check)."""
    import base64
    import socket
    try:
        port_s, path = (profile / "DevToolsActivePort").read_text(encoding="utf-8").split()[:2]
        port = int(port_s)
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            key = base64.b64encode(os.urandom(16)).decode()
            s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                       "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            if b" 101 " not in s.recv(4096).split(b"\r\n", 1)[0]:
                return False
            msg = json.dumps({"id": 1, "method": "Browser.close"}).encode()
            mask = os.urandom(4)
            s.sendall(bytes([0x81, 0x80 | len(msg)]) + mask
                      + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))
            try:
                s.recv(4096)
            except OSError:
                pass
        return True
    except (OSError, ValueError):
        return False


def wipe_dir(path: Path, attempts: int = 20) -> bool:
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.15)  # Windows houdt bestanden even vast na het sluiten
    return False


# --------------------------------------------------------------------------- bewaarde identiteiten
#
# Een bewaarde identiteit = een profiel dat NIET gewist wordt (logins, cookies,
# instellingen blijven) + de VPN-server/proxy die ze gebruikte (zelfde IP).

SAFE_NAME_RE = re.compile(r"^[\w\- .]{1,40}$")


def identities_dir() -> Path:
    d = data_dir() / "identities"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class SavedIdentity:
    name: str
    path: Path
    vpn: str = ""     # bestandsnaam in data/vpn (bv. "Belgie.conf")
    proxy: str = ""   # proxy-URL bij proxylijst-modus

    @property
    def profile(self) -> Path:
        return self.path / "profile"

    def describe(self) -> str:
        via = f"VPN {Path(self.vpn).stem}" if self.vpn else (self.proxy or "geen VPN")
        return f"{self.name}  ({via})"


def _write_meta(si: SavedIdentity) -> None:
    (si.path / "identity.json").write_text(
        json.dumps({"name": si.name, "vpn": si.vpn, "proxy": si.proxy}, indent=2), encoding="utf-8")


def list_saved_identities() -> list[SavedIdentity]:
    out = []
    for d in sorted(identities_dir().iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        try:
            meta = json.loads((d / "identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        out.append(SavedIdentity(meta.get("name", d.name), d, meta.get("vpn", ""), meta.get("proxy", "")))
    return out


def get_saved_identity(name: str) -> SavedIdentity | None:
    return next((s for s in list_saved_identities() if s.name == name), None)


def delete_saved_identity(si: SavedIdentity) -> None:
    wipe_dir(si.path)


# --------------------------------------------------------------------------- identiteiten

@dataclass
class Identity:
    number: int
    profile: Path
    proxy: Proxy | None
    process: subprocess.Popen
    tunnel: "VpnTunnel | None" = None
    saved: SavedIdentity | None = None
    bookmarks_digest: str = ""

    def alive(self) -> bool:
        return self.process.poll() is None

    def describe(self) -> str:
        if self.tunnel:
            via = f"VPN {self.tunnel.name}"
        else:
            via = self.proxy.display() if self.proxy else "systeem-VPN / directe verbinding"
        who = f"★ {self.saved.name}" if self.saved else f"Identiteit #{self.number}"
        return f"{who} via {via}"


@dataclass
class IdentityManager:
    cfg: dict
    identities: list[Identity] = field(default_factory=list)
    counter: int = 0

    def __post_init__(self):
        self.picker = ProxyPicker(self.cfg.get("proxy_order", "random"))
        self.cleanup_leftovers()

    def cleanup_leftovers(self) -> None:
        """Wis tijdelijke profielen die een vorige sessie (bv. na een crash) achterliet."""
        active = {i.profile for i in self.identities}
        for d in profiles_root().iterdir():
            if d not in active:
                wipe_dir(d, attempts=1)

    def spawn(self, url: str | None = None, saved: SavedIdentity | None = None) -> Identity:
        chromium = find_chromium(self.cfg)
        if not chromium:
            raise FileNotFoundError("Chromium niet gevonden. Kies chrome.exe via Instellingen.")
        if saved and any(i.saved and i.saved.path == saved.path for i in self.identities):
            raise ValueError(f"'{saved.name}' is al open.")
        self.counter += 1
        if saved:
            profile = saved.profile
            profile.mkdir(parents=True, exist_ok=True)
        else:
            profile = Path(tempfile.mkdtemp(prefix=f"id{self.counter}-", dir=profiles_root()))

        def cleanup():
            if not saved:
                wipe_dir(profile)

        proxy = None
        tunnel = None
        mode = self.cfg.get("proxy_mode")
        if saved and saved.vpn:
            mode = "vpn"
        elif saved and saved.proxy:
            mode = "list"
        if mode == "vpn":
            try:
                tunnel = self._start_tunnel(profile, prefer=saved.vpn if saved else "")
            except Exception:
                cleanup()
                raise
            proxy = tunnel.proxy
        elif mode == "list":
            proxies = load_proxies()
            proxy = next((p for p in proxies if saved and p.url == saved.proxy), None)
            if proxy is None:
                self.picker.order = self.cfg.get("proxy_order", "random")
                proxy = self.picker.pick(proxies)
            if proxy is None:
                cleanup()
                raise ValueError("Proxy-modus staat aan, maar proxies.txt is leeg.")
        try:
            bm_digest = seed_profile(profile)
        except OSError:
            bm_digest = ""
        exts = [e.path for e in list_extensions() if e.enabled]
        search_ext = search_extension(self.cfg)
        if search_ext:
            exts.append(search_ext)
        args = build_args(chromium, profile, proxy, exts, self.cfg)
        if url:
            args[-1] = url
        elif saved:
            args.pop()  # bewaarde identiteit: Chromium herstelt zelf haar tabbladen/startpagina
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        except Exception:
            if tunnel:
                tunnel.stop()
            cleanup()
            raise
        ident = Identity(self.counter, profile, proxy, proc, tunnel, saved, bm_digest)
        self.identities.append(ident)
        return ident

    def _start_tunnel(self, profile: Path, prefer: str = "") -> VpnTunnel:
        configs = list_vpn_configs()
        if not configs:
            raise ValueError("Nog geen VPN-servers. Voeg WireGuard-bestanden (.conf) toe "
                             "via het tabblad Netwerk.")
        in_use = {i.tunnel.conf for i in self.identities if i.tunnel}
        free = [c for c in configs if c not in in_use]
        if not free:
            raise ValueError("Alle VPN-servers zijn al in gebruik door een open identiteit. "
                             "Voeg meer .conf-bestanden toe of sluit een identiteit.")
        tried: list[str] = []
        preferred = next((c for c in free if c.name == prefer), None) if prefer else None
        if preferred:  # bewaarde identiteit: eerst haar eigen server (= zelfde IP)
            tried.append(str(preferred))
            tunnel = VpnTunnel(preferred, profile)
            try:
                tunnel.start()
                return tunnel
            except ConnectionError:
                pass
        self.picker.order = self.cfg.get("proxy_order", "random")
        for _ in range(min(3, len(free) - len(tried))):  # werkt een server niet? volgende
            choice = self.picker.pick([Proxy(str(c)) for c in free if str(c) not in tried])
            tried.append(choice.url)
            tunnel = VpnTunnel(Path(choice.url), profile)
            try:
                tunnel.start()
                return tunnel
            except ConnectionError:
                continue
        raise ConnectionError("Geen verbinding met de VPN (geprobeerd: "
                              + ", ".join(Path(t).stem for t in tried) + ").")

    def _stop_browser(self, ident: Identity, graceful: bool) -> None:
        if not ident.alive():
            return
        if graceful:
            # Netjes sluiten zodat Chromium cookies/logins wegschrijft.
            if cdp_browser_close(ident.profile):
                try:
                    ident.process.wait(timeout=6)
                    return
                except subprocess.TimeoutExpired:
                    pass
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/PID", str(ident.process.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                ident.process.terminate()
            try:
                ident.process.wait(timeout=8)
                return
            except subprocess.TimeoutExpired:
                pass
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(ident.process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            ident.process.kill()
        try:
            ident.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def close(self, ident: Identity) -> None:
        # Altijd netjes sluiten, zodat Chromium bladwijzers (en bij bewaarde
        # identiteiten ook logins) naar schijf schrijft.
        self._stop_browser(ident, graceful=True)
        sync_bookmarks_back(ident.profile, ident.bookmarks_digest)
        sync_pinned_back(ident.profile)
        if ident.tunnel:
            ident.tunnel.stop()
        if not ident.saved:
            wipe_dir(ident.profile)
        if ident in self.identities:
            self.identities.remove(ident)

    def close_all(self) -> None:
        for ident in list(self.identities):
            self.close(ident)

    def new_identity(self, url: str | None = None) -> Identity:
        """Alles sluiten (tijdelijke profielen wissen), dan één verse identiteit starten."""
        self.close_all()
        return self.spawn(url)

    def save(self, ident: Identity, name: str) -> Identity:
        """Bewaar een open identiteit (logins, cookies, VPN-server) en heropen ze meteen."""
        name = name.strip()
        if not SAFE_NAME_RE.match(name):
            raise ValueError("Gebruik een naam met alleen letters, cijfers, spaties, - of _ (max 40).")
        if ident.saved:
            raise ValueError(f"Deze identiteit is al bewaard als '{ident.saved.name}'.")
        target = identities_dir() / name
        if target.exists():
            raise ValueError(f"Er bestaat al een bewaarde identiteit '{name}'.")
        self._stop_browser(ident, graceful=True)
        sync_bookmarks_back(ident.profile, ident.bookmarks_digest)
        sync_pinned_back(ident.profile)
        if ident.tunnel:
            ident.tunnel.stop()
        if ident in self.identities:
            self.identities.remove(ident)
        target.mkdir(parents=True)
        for _ in range(20):  # Windows laat bestanden soms even vast na het sluiten
            try:
                shutil.move(str(ident.profile), str(target / "profile"))
                break
            except OSError:
                time.sleep(0.2)
        else:
            shutil.copytree(ident.profile, target / "profile", dirs_exist_ok=True)
            wipe_dir(ident.profile)
        si = SavedIdentity(
            name, target,
            vpn=ident.tunnel.conf.name if ident.tunnel else "",
            proxy=ident.proxy.url if (ident.proxy and not ident.tunnel) else "",
        )
        _write_meta(si)
        return self.spawn(saved=si)

    def open_saved(self, si: SavedIdentity) -> Identity:
        return self.spawn(saved=si)

    def reap(self) -> list[Identity]:
        """Ruim identiteiten op waarvan de gebruiker het venster zelf sloot."""
        gone = [i for i in self.identities if not i.alive()]
        for i in gone:
            self.close(i)
        return gone


# --------------------------------------------------------------------------- Mullvad-account
#
# Het accountnummer werkt als een wachtwoord. Het staat alleen lokaal in
# data/ (nooit in git). Op Windows wordt het versleuteld met DPAPI: alleen
# jouw Windows-gebruiker op deze pc kan het weer lezen.

MULLVAD_ACCOUNT_URL = "https://mullvad.net/account"
MULLVAD_WG_CONFIG_URL = "https://mullvad.net/account/wireguard-config"


def mullvad_account_path() -> Path:
    return data_dir() / "mullvad_account.bin"


def normalize_mullvad_account(text: str) -> str | None:
    digits = re.sub(r"[\s-]", "", text or "")
    return digits if re.fullmatch(r"\d{16}", digits) else None


def format_mullvad_account(number: str) -> str:
    return " ".join(number[i:i + 4] for i in range(0, len(number), 4))


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # 0x1 = geen UI
    if not ok:
        raise OSError("Windows-versleuteling (DPAPI) mislukt.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[attr-defined]


def save_mullvad_account(number: str) -> None:
    norm = normalize_mullvad_account(number)
    if not norm:
        raise ValueError("Een Mullvad-accountnummer bestaat uit 16 cijfers.")
    if os.name == "nt":
        payload = b"dpapi:" + _dpapi(norm.encode(), protect=True)
    else:
        payload = b"plain:" + norm.encode()  # buiten Windows: niet versleuteld
    mullvad_account_path().write_bytes(payload)


def load_mullvad_account() -> str:
    try:
        payload = mullvad_account_path().read_bytes()
    except OSError:
        return ""
    try:
        if payload.startswith(b"dpapi:"):
            return _dpapi(payload[6:], protect=False).decode()
        if payload.startswith(b"plain:"):
            return payload[6:].decode()
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def forget_mullvad_account() -> None:
    mullvad_account_path().unlink(missing_ok=True)
