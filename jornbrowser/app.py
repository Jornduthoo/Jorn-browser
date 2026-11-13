"""Jorn Browser: venster met de knop "Nieuwe identiteit"."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from . import core
    from . import theme as T
except ImportError:  # gestart als los script / PyInstaller
    import core  # type: ignore
    import theme as T  # type: ignore


def open_path(path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jorn Browser")
        self.geometry("640x780")
        self.minsize(560, 620)
        self.F = T.apply(self)
        self._set_icon()
        self.cfg = core.load_config()
        self.mgr = core.IdentityManager(self.cfg)
        self.status = tk.StringVar(value="Klaar. Klik op Nieuwe identiteit om te starten.")

        self._build_header()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=(4, 0))
        nb.add(self._build_main(nb), text="  Identiteit  ")
        nb.add(self._build_network(nb), text="  Netwerk  ")
        nb.add(self._build_extensions(nb), text="  Extensies  ")
        nb.add(self._build_settings(nb), text="  Instellingen  ")

        bar = tk.Frame(self, bg=T.PANEL, height=34)
        bar.pack(fill="x", side="bottom")
        tk.Label(bar, textvariable=self.status, bg=T.PANEL, fg=T.MUTED, anchor="w",
                 font=self.F["small"], padx=14, pady=8).pack(fill="x")

        self.bind_all("<Control-n>", lambda e: self.new_identity())
        self.bind_all("<Control-N>", lambda e: self.new_identity())
        self.bind_all("<Control-s>", lambda e: self.save_identity())
        self.bind_all("<Control-S>", lambda e: self.save_identity())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(1000, self._tick)
        self._refresh_identities()

        if not core.find_chromium(self.cfg):
            self.after(300, self._warn_no_chromium)

    def _set_icon(self):
        try:
            self._icon = tk.PhotoImage(file=str(T.resource("logo-64.png")))
            self.iconphoto(True, self._icon)
            if os.name == "nt":
                self.iconbitmap(default=str(T.resource("icon.ico")))
        except tk.TclError:
            self._icon = None

    # ------------------------------------------------------------------ opbouw

    def _build_header(self):
        h = ttk.Frame(self, padding=(16, 14, 16, 6))
        h.pack(fill="x")
        try:
            self._logo = tk.PhotoImage(file=str(T.resource("logo-64.png"))).subsample(1)
            tk.Label(h, image=self._logo, bg=T.BG).pack(side="left")
        except tk.TclError:
            pass
        txt = ttk.Frame(h)
        txt.pack(side="left", padx=(12, 0))
        ttk.Label(txt, text="Jorn Browser", style="Title.TLabel").pack(anchor="w")
        ttk.Label(txt, text="Privé. Snel. Telkens iemand anders.", style="Muted.TLabel").pack(anchor="w")
        self.pill = T.Pill(h, self.F["small"])
        self.pill.pack(side="right")

    def _build_main(self, parent):
        f = ttk.Frame(parent, padding=(4, 14, 4, 10))

        self.big_btn = T.GradientButton(f, "↻   Nieuwe identiteit", self.new_identity, height=78,
                                        font=self.F["hero"], subtext="Alles wissen  ·  nieuw IP  ·  Ctrl+N")
        self.big_btn.pack(fill="x")

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        for i in range(3):
            row.columnconfigure(i, weight=1, uniform="b")
        sec = ("#232846", "#2d3360")
        T.GradientButton(row, "★  Bewaren", self.save_identity, height=44, radius=10, colors=sec,
                         font=self.F["bold"]).grid(row=0, column=0, sticky="ew")
        T.GradientButton(row, "◎  Toon mijn IP", self.show_ip, height=44, radius=10, colors=sec,
                         font=self.F["bold"]).grid(row=0, column=1, sticky="ew", padx=8)
        T.GradientButton(row, "＋  Extra venster", self.extra_identity, height=44, radius=10, colors=sec,
                         font=self.F["bold"]).grid(row=0, column=2, sticky="ew")

        c = T.card(f)
        c.outer.pack(fill="x", pady=(14, 0))
        top = ttk.Frame(c, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Nu open", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="Alles sluiten", style="Danger.TButton", command=self.close_all).pack(side="right")
        ttk.Button(top, text="Sluiten", command=self.close_selected).pack(side="right", padx=6)
        self.ident_list = T.listbox(c, height=3)
        self.ident_list.pack(fill="x", pady=(10, 0))

        c2 = T.card(f)
        c2.outer.pack(fill="both", expand=True, pady=(12, 0))
        top2 = ttk.Frame(c2, style="Card.TFrame")
        top2.pack(fill="x")
        ttk.Label(top2, text="★  Bewaarde identiteiten", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top2, text="Verwijderen", style="Danger.TButton", command=self.delete_saved).pack(side="right")
        ttk.Button(top2, text="Openen", command=self.open_saved).pack(side="right", padx=6)
        ttk.Label(c2, text="Logins, cookies en dezelfde VPN-server blijven bewaard. Dubbelklik om te openen.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(4, 0))
        self.saved_list = T.listbox(c2, height=4)
        self.saved_list.pack(fill="both", expand=True, pady=(8, 0))
        self.saved_list.bind("<Double-Button-1>", lambda e: self.open_saved())
        return f

    def _build_network(self, parent):
        f = ttk.Frame(parent, padding=(4, 14, 4, 10))
        self.proxy_mode = tk.StringVar(value=self.cfg["proxy_mode"])

        c = T.card(f)
        c.outer.pack(fill="x")
        ttk.Radiobutton(c, text="Ingebouwde VPN  (aanbevolen)", value="vpn",
                        variable=self.proxy_mode, command=self._save_net).pack(anchor="w")
        ttk.Label(c, text="Elke identiteit een eigen VPN-server. Geen VPN-app nodig: voeg WireGuard-"
                          "bestanden (.conf of .zip) toe van je VPN-dienst.",
                  style="CardMuted.TLabel", wraplength=520).pack(anchor="w", padx=(26, 0))
        vbtn = ttk.Frame(c, style="Card.TFrame")
        vbtn.pack(anchor="w", padx=(26, 0), pady=(10, 4))
        ttk.Button(vbtn, text="＋ VPN-bestanden toevoegen", command=self.add_vpn_configs).pack(side="left")
        ttk.Button(vbtn, text="Map openen", command=lambda: open_path(core.vpn_dir())).pack(side="left", padx=6)
        self.vpn_count = tk.StringVar()
        ttk.Label(c, textvariable=self.vpn_count, style="CardMuted.TLabel",
                  wraplength=520).pack(anchor="w", padx=(26, 0))

        c2 = T.card(f)
        c2.outer.pack(fill="x", pady=(12, 0))
        ttk.Radiobutton(c2, text="Proxylijst  (proxies.txt)", value="list", variable=self.proxy_mode,
                        command=self._save_net).pack(anchor="w")
        btns = ttk.Frame(c2, style="Card.TFrame")
        btns.pack(anchor="w", padx=(26, 0), pady=(6, 4))
        ttk.Button(btns, text="Bewerken", command=self.edit_proxies).pack(side="left")
        ttk.Button(btns, text="Mullvad-lijst ophalen", command=self.fetch_mullvad).pack(side="left", padx=6)
        self.proxy_count = tk.StringVar()
        ttk.Label(c2, textvariable=self.proxy_count, style="CardMuted.TLabel").pack(anchor="w", padx=(26, 0))
        ttk.Radiobutton(c2, text="Geen  (een aparte VPN-app op je pc bepaalt het IP)", value="none",
                        variable=self.proxy_mode, command=self._save_net).pack(anchor="w", pady=(12, 0))

        c3 = T.card(f)
        c3.outer.pack(fill="x", pady=(12, 0))
        order = ttk.Frame(c3, style="Card.TFrame")
        order.pack(anchor="w")
        self.proxy_order = tk.StringVar(value=self.cfg["proxy_order"])
        ttk.Label(order, text="Server kiezen:", style="Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(order, text="willekeurig", value="random", variable=self.proxy_order,
                        command=self._save_net).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(order, text="na elkaar", value="sequential", variable=self.proxy_order,
                        command=self._save_net).pack(side="left")
        self.webrtc = tk.BooleanVar(value=self.cfg["block_webrtc_leak"])
        ttk.Checkbutton(c3, text="WebRTC-lek blokkeren  (verbergt je echte IP, aanbevolen)",
                        variable=self.webrtc, command=self._save_net).pack(anchor="w", pady=(8, 0))
        self._refresh_proxy_count()
        return f

    def _build_extensions(self, parent):
        f = ttk.Frame(parent, padding=(4, 14, 4, 10))
        c = T.card(f)
        c.outer.pack(fill="x")
        ttk.Label(c, text="Extensie toevoegen", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(c, text="Plak een link uit de Chrome Web Store (of een extensie-ID).",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.ext_url = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.ext_url)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.add_extension())
        ttk.Button(row, text="＋ Toevoegen", command=self.add_extension).pack(side="left", padx=(8, 0))

        c2 = T.card(f)
        c2.outer.pack(fill="both", expand=True, pady=(12, 0))
        top = ttk.Frame(c2, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Geïnstalleerd", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="Map openen", command=lambda: open_path(core.extensions_dir())).pack(side="right")
        ttk.Button(top, text="Vernieuwen", command=self._refresh_extensions).pack(side="right", padx=6)
        ttk.Label(c2, text="Vinkje = aan. Wijzigingen gelden vanaf de volgende identiteit. "
                           "Tip: hoe minder extensies, hoe minder herkenbaar je bent.",
                  style="CardMuted.TLabel", wraplength=520).pack(anchor="w", pady=(4, 8))
        self.ext_frame = ttk.Frame(c2, style="Card.TFrame")
        self.ext_frame.pack(fill="both", expand=True)
        self._refresh_extensions()
        return f

    def _build_settings(self, parent):
        f = ttk.Frame(parent, padding=(4, 14, 4, 10))

        m = T.card(f)
        m.outer.pack(fill="x", pady=(0, 12))
        ttk.Label(m, text="Mullvad-account", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(m, text="Alleen op deze pc bewaard" + (", versleuteld met Windows." if os.name == "nt" else ".")
                  + " Behandel het als een wachtwoord.", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(m, style="Card.TFrame")
        row.pack(fill="x")
        saved = core.load_mullvad_account()
        self.mullvad_acc = tk.StringVar(value=core.format_mullvad_account(saved) if saved else "")
        self.mullvad_entry = ttk.Entry(row, textvariable=self.mullvad_acc, show="•", font=self.F["h2"])
        self.mullvad_entry.pack(side="left", fill="x", expand=True)
        self.mullvad_show = ttk.Button(row, text="Toon", width=6, command=self._toggle_mullvad)
        self.mullvad_show.pack(side="left", padx=(8, 0))
        row2 = ttk.Frame(m, style="Card.TFrame")
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="Opslaan", command=self.save_mullvad).pack(side="left")
        ttk.Button(row2, text="Kopiëren", command=self.copy_mullvad).pack(side="left", padx=6)
        ttk.Button(row2, text="Vergeten", style="Danger.TButton", command=self.forget_mullvad).pack(side="left")
        row3 = ttk.Frame(m, style="Card.TFrame")
        row3.pack(fill="x", pady=(8, 0))
        ttk.Button(row3, text="Mijn account ↗",
                   command=lambda: webbrowser.open(core.MULLVAD_ACCOUNT_URL)).pack(side="left")
        ttk.Button(row3, text="WireGuard-bestanden maken ↗",
                   command=lambda: webbrowser.open(core.MULLVAD_WG_CONFIG_URL)).pack(side="left", padx=6)

        c = T.card(f)
        c.outer.pack(fill="x")
        ttk.Label(c, text="Chromium (chrome.exe)", style="CardTitle.TLabel").pack(anchor="w")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        found = core.find_chromium(self.cfg)
        self.chromium_path = tk.StringVar(value=str(found) if found else "")
        ttk.Entry(row, textvariable=self.chromium_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Kiezen…", command=self.pick_chromium).pack(side="left", padx=(8, 0))

        c2 = T.card(f)
        c2.outer.pack(fill="x", pady=(12, 0))
        ttk.Label(c2, text="Startpagina", style="CardTitle.TLabel").pack(anchor="w")
        self.start_url = tk.StringVar(value=self.cfg["start_url"])
        ttk.Entry(c2, textvariable=self.start_url).pack(fill="x", pady=(6, 10))
        ttk.Label(c2, text="IP-controlepagina", style="CardTitle.TLabel").pack(anchor="w")
        self.check_url = tk.StringVar(value=self.cfg["check_url"])
        ttk.Entry(c2, textvariable=self.check_url).pack(fill="x", pady=(6, 10))
        ttk.Button(c2, text="Opslaan", command=self._save_settings).pack(anchor="e")

        ttk.Button(f, text="Datamap openen", command=lambda: open_path(core.data_dir())).pack(anchor="w", pady=(12, 0))
        return f

    # ------------------------------------------------------------------ acties

    def _run(self, fn, done_msg=None):
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - toon elke fout aan de gebruiker
            messagebox.showerror("Jorn Browser", str(e))
            self.status.set("Fout: " + str(e))
            return None
        self._refresh_identities()
        if done_msg:
            self.status.set(done_msg(result) if callable(done_msg) else done_msg)
        return result

    def _run_bg(self, fn, done_msg, busy_msg):
        """Zoals _run, maar in de achtergrond (VPN verbinden duurt even)."""
        if getattr(self, "_busy", False):
            return
        self._busy = True
        self.status.set(busy_msg)
        self.big_btn.set_busy(True, "Bezig…")

        def work():
            try:
                result = fn()
                self.after(0, lambda: self._bg_done(done_msg(result), None))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.after(0, lambda: self._bg_done(None, err))

        threading.Thread(target=work, daemon=True).start()

    def _bg_done(self, msg, err):
        self._busy = False
        self.big_btn.set_busy(False, "↻   Nieuwe identiteit")
        self._refresh_identities()
        if err:
            self.status.set("Fout: " + err)
            messagebox.showerror("Jorn Browser", err)
        else:
            self.status.set(msg)

    def new_identity(self):
        self._run_bg(self.mgr.new_identity, lambda i: f"✔ {i.describe()}", "Nieuwe identiteit starten…")

    def extra_identity(self):
        self._run_bg(self.mgr.spawn, lambda i: f"✔ Extra: {i.describe()}", "Extra identiteit starten…")

    def save_identity(self):
        """Eén klik: de open identiteit onthouden en meteen verder gebruiken."""
        unsaved = [i for i in self.mgr.identities if not i.saved]
        if not unsaved:
            messagebox.showinfo("Bewaren", "Er is geen open (niet-bewaarde) identiteit om te bewaren.\n"
                                           "Klik eerst op 'Nieuwe identiteit'.")
            return
        sel = self.ident_list.curselection()
        ident = self.mgr.identities[sel[0]] if (sel and sel[0] < len(self.mgr.identities)) else unsaved[-1]
        if ident.saved:
            ident = unsaved[-1]
        default = f"Identiteit {len(core.list_saved_identities()) + 1}"
        name = simpledialog.askstring("Bewaren", "Naam voor deze identiteit:", initialvalue=default, parent=self)
        if not name:
            return
        self._run_bg(lambda: self.mgr.save(ident, name),
                     lambda i: f"★ Bewaard: {i.describe()}", "Bewaren…")

    def _selected_saved(self):
        sel = self.saved_list.curselection()
        saved = core.list_saved_identities()
        if not sel or sel[0] >= len(saved) or not saved:
            messagebox.showinfo("Bewaarde identiteiten", "Selecteer eerst een bewaarde identiteit.")
            return None
        return saved[sel[0]]

    def open_saved(self):
        si = self._selected_saved()
        if si:
            self._run_bg(lambda: self.mgr.open_saved(si), lambda i: f"✔ {i.describe()}", f"'{si.name}' openen…")

    def delete_saved(self):
        si = self._selected_saved()
        if not si:
            return
        if any(i.saved and i.saved.path == si.path for i in self.mgr.identities):
            messagebox.showwarning("Verwijderen", f"Sluit '{si.name}' eerst.")
            return
        if messagebox.askyesno("Verwijderen", f"'{si.name}' en al haar logins/cookies definitief wissen?"):
            core.delete_saved_identity(si)
            self._refresh_saved()
            self.status.set(f"'{si.name}' gewist.")

    def _refresh_saved(self):
        self.saved_list.delete(0, "end")
        open_paths = {i.saved.path for i in self.mgr.identities if i.saved}
        for si in core.list_saved_identities():
            self.saved_list.insert("end", ("●  " if si.path in open_paths else "    ") + si.describe())

    def close_all(self):
        self._run(self.mgr.close_all, "Alle identiteiten gesloten en gewist.")

    def close_selected(self):
        sel = self.ident_list.curselection()
        if sel and sel[0] < len(self.mgr.identities):
            ident = self.mgr.identities[sel[0]]
            self._run(lambda: self.mgr.close(ident), f"Identiteit #{ident.number} gewist.")

    def show_ip(self):
        """Opent de IP-controlepagina in elke actieve identiteit (dus via haar eigen proxy)."""
        if not self.mgr.identities:
            self._run_bg(lambda: self.mgr.spawn(self.cfg["check_url"]), lambda i: f"✔ {i.describe()}",
                         "Identiteit starten…")
            return
        chromium = core.find_chromium(self.cfg)
        for ident in self.mgr.identities:
            subprocess.Popen([str(chromium), f"--user-data-dir={ident.profile}", self.cfg["check_url"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def edit_proxies(self):
        core.load_proxies()  # maakt het bestand aan als het nog niet bestaat
        open_path(core.proxies_path())

    def fetch_mullvad(self):
        self.status.set("Mullvad-serverlijst ophalen…")

        def work():
            try:
                proxies = core.fetch_mullvad_proxies()
                core.write_proxies(proxies)
                msg = (f"✔ {len(proxies)} Mullvad-proxies opgeslagen. Werkt alleen terwijl je met "
                       "Mullvad (WireGuard) verbonden bent.")
                self.after(0, lambda: (self.status.set(msg), self._refresh_proxy_count()))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Mullvad", f"Ophalen mislukt: {err}"))

        threading.Thread(target=work, daemon=True).start()

    def add_extension(self):
        ext_id = core.extract_extension_id(self.ext_url.get())
        if not ext_id:
            messagebox.showwarning("Extensie", "Geen geldige Web Store-link of ID gevonden.")
            return
        self.status.set(f"Extensie {ext_id} downloaden…")

        def work():
            try:
                path = core.download_extension(ext_id)
                name = core._manifest_name(path)
                self.after(0, lambda: (self.status.set(f"✔ '{name}' toegevoegd. Actief vanaf de volgende identiteit."),
                                       self.ext_url.set(""), self._refresh_extensions()))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Extensie", f"Toevoegen mislukt: {err}"))

        threading.Thread(target=work, daemon=True).start()

    def _toggle_mullvad(self):
        hidden = self.mullvad_entry.cget("show") == "•"
        self.mullvad_entry.configure(show="" if hidden else "•")
        self.mullvad_show.configure(text="Verberg" if hidden else "Toon")

    def save_mullvad(self):
        try:
            core.save_mullvad_account(self.mullvad_acc.get())
        except (ValueError, OSError) as e:
            messagebox.showerror("Mullvad-account", str(e))
            return
        self.mullvad_acc.set(core.format_mullvad_account(core.load_mullvad_account()))
        self.status.set("✔ Mullvad-account opgeslagen (alleen op deze pc).")

    def copy_mullvad(self):
        number = core.normalize_mullvad_account(self.mullvad_acc.get())
        if not number:
            messagebox.showwarning("Mullvad-account", "Vul eerst een geldig accountnummer in (16 cijfers).")
            return
        self.clipboard_clear()
        self.clipboard_append(number)
        self.status.set("✔ Gekopieerd. Het klembord wordt over 30 seconden gewist.")

        def wipe():
            try:
                if self.clipboard_get() == number:
                    self.clipboard_clear()
                    self.status.set("Klembord gewist.")
            except tk.TclError:
                pass
        self.after(30000, wipe)

    def forget_mullvad(self):
        if messagebox.askyesno("Mullvad-account", "Accountnummer van deze pc wissen?"):
            core.forget_mullvad_account()
            self.mullvad_acc.set("")
            self.status.set("Mullvad-account gewist van deze pc.")

    def pick_chromium(self):
        p = filedialog.askopenfilename(title="Kies chrome.exe van Chromium",
                                       filetypes=[("chrome.exe", "chrome.exe"), ("Alle bestanden", "*")])
        if p:
            self.chromium_path.set(p)
            self._save_settings()

    # ------------------------------------------------------------------ opslaan / verversen

    def _save_net(self):
        self.cfg["proxy_mode"] = self.proxy_mode.get()
        self.cfg["proxy_order"] = self.proxy_order.get()
        self.cfg["block_webrtc_leak"] = bool(self.webrtc.get())
        core.save_config(self.cfg)
        self._refresh_proxy_count()
        self._refresh_pill()

    def _save_settings(self):
        self.cfg["chromium_path"] = self.chromium_path.get().strip()
        self.cfg["start_url"] = self.start_url.get().strip() or "about:blank"
        self.cfg["check_url"] = self.check_url.get().strip() or core.DEFAULT_CONFIG["check_url"]
        core.save_config(self.cfg)
        self.status.set("Instellingen opgeslagen.")

    def _refresh_proxy_count(self):
        n = len(core.load_proxies())
        self.proxy_count.set(f"{n} proxy's in proxies.txt")
        names = [c.stem for c in core.list_vpn_configs()]
        if names:
            shown = ", ".join(names[:6]) + (" …" if len(names) > 6 else "")
            self.vpn_count.set(f"{len(names)} VPN-server(s): {shown}")
        else:
            self.vpn_count.set("Nog geen VPN-servers toegevoegd.")

    def add_vpn_configs(self):
        paths = filedialog.askopenfilenames(
            title="Kies WireGuard-bestanden",
            filetypes=[("WireGuard", "*.conf *.zip"), ("Alle bestanden", "*")])
        if not paths:
            return
        try:
            n = core.import_vpn_configs(list(paths))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("VPN", f"Toevoegen mislukt: {e}")
            return
        self._refresh_proxy_count()
        self._refresh_pill()
        self.status.set(f"✔ {n} VPN-server(s) toegevoegd.")

    def _refresh_extensions(self):
        for w in self.ext_frame.winfo_children():
            w.destroy()
        exts = core.list_extensions()
        if not exts:
            ttk.Label(self.ext_frame, text="Nog geen extensies.", style="CardMuted.TLabel").pack(anchor="w")
        for ext in exts:
            row = ttk.Frame(self.ext_frame, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=ext.enabled)
            ttk.Checkbutton(row, text=ext.name, variable=var,
                            command=lambda e=ext, v=var: core.set_extension_enabled(e, v.get())).pack(side="left")
            ttk.Button(row, text="Verwijderen", style="Danger.TButton",
                       command=lambda e=ext: (core.remove_extension(e), self._refresh_extensions())).pack(side="right")

    def _refresh_identities(self):
        self.ident_list.delete(0, "end")
        for ident in self.mgr.identities:
            self.ident_list.insert("end", "  " + ident.describe())
        if not self.mgr.identities:
            self.ident_list.insert("end", "  Nog niets open. Klik op Nieuwe identiteit.")
            self.ident_list.itemconfig(0, fg=T.MUTED)
        self._refresh_saved()
        self._refresh_pill()

    def _refresh_pill(self):
        mode = self.cfg.get("proxy_mode")
        n_open = len(self.mgr.identities)
        suffix = f"  ·  {n_open} open" if n_open else ""
        if mode == "vpn":
            n = len(core.list_vpn_configs())
            if n:
                self.pill.set(f"VPN  ·  {n} server{'s' if n != 1 else ''}{suffix}", T.OK)
            else:
                self.pill.set("VPN  ·  nog geen servers", T.WARN)
        elif mode == "list":
            self.pill.set(f"Proxy  ·  {len(core.load_proxies())}{suffix}", T.ACCENT2)
        else:
            self.pill.set(f"Systeem-VPN{suffix}", T.MUTED)

    def _tick(self):
        if not getattr(self, "_busy", False) and self.mgr.reap():
            self._refresh_identities()
            self.status.set("Gesloten venster gewist.")
        self.after(1000, self._tick)

    def _warn_no_chromium(self):
        messagebox.showinfo(
            "Chromium nodig",
            "Jorn Browser gebruikt Chromium (de open-source basis van Chrome).\n\n"
            "Installeer het met deze opdracht in PowerShell:\n"
            "    winget install eloston.ungoogled-chromium\n\n"
            "Of kies chrome.exe zelf via het tabblad Instellingen.")

    def on_close(self):
        self.mgr.close_all()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
