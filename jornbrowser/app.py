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
    from . import updater
except ImportError:  # gestart als los script / PyInstaller
    import core  # type: ignore
    import theme as T  # type: ignore
    import updater  # type: ignore


def open_path(path) -> None:
    """Open een map of bestand in Verkenner. Lukt dat niet: toon het pad."""
    path = str(path)
    try:
        if os.name == "nt":
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                subprocess.Popen(["explorer", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showinfo("Map openen", f"Kon de map niet automatisch openen ({e}).\n\n"
                                          f"Open ze zelf in Verkenner:\n{path}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jorn Browser")
        self.geometry("640x780")
        self.minsize(560, 620)
        self.F = T.apply(self)
        self._set_icon()
        self.cfg = core.load_config()
        core.log(f"=== Jorn Browser v{updater.current_version()} gestart (map {core.app_dir()})")
        self.mgr = core.IdentityManager(self.cfg)
        self.status = tk.StringVar(value="Klaar. Klik op Nieuwe identiteit om te starten.")

        if not updater.cleanup_after_update():
            # oude versie draait nog even: straks opnieuw proberen
            for ms in (2000, 5000, 15000, 60000):
                self.after(ms, updater.cleanup_after_update)
        self._build_header()
        self.update_bar = tk.Frame(self, bg=T.ACCENT_MID)  # verschijnt alleen bij een update
        nb = ttk.Notebook(self)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=14, pady=(4, 0))
        nb.add(self._build_main(nb), text="  Identiteit  ")
        nb.add(self._build_network(nb), text="  Netwerk  ")
        nb.add(self._build_extensions(nb), text="  Extensies  ")
        nb.add(self._build_settings(nb), text="  Instellingen  ")

        bar = tk.Frame(self, bg=T.PANEL, height=34)
        bar.pack(fill="x", side="bottom", before=nb)  # eerst inpakken: blijft altijd zichtbaar
        upd = tk.Label(bar, text="Updates zoeken", bg=T.PANEL, fg=T.ACCENT2, cursor="hand2",
                       font=self.F["small"], padx=10)
        upd.pack(side="right")
        upd.bind("<Button-1>", lambda e: self.check_updates(manual=True))
        tk.Label(bar, text=f"v{updater.current_version()}", bg=T.PANEL, fg=T.MUTED,
                 font=self.F["small"]).pack(side="right")
        tk.Label(bar, textvariable=self.status, bg=T.PANEL, fg=T.MUTED, anchor="w",
                 font=self.F["small"], padx=14, pady=8).pack(side="left", fill="x", expand=True)

        self.bind_all("<Control-n>", lambda e: self.new_identity())
        self.bind_all("<Control-N>", lambda e: self.new_identity())
        self.bind_all("<Control-s>", lambda e: self.save_identity())
        self.bind_all("<Control-S>", lambda e: self.save_identity())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(1000, self._tick)
        self._refresh_identities()

        if not core.find_chromium(self.cfg):
            self.after(300, self._warn_no_chromium)
        if self.cfg.get("auto_update_check", True):
            self.after(2500, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------------ updates

    def check_updates(self, manual: bool):
        if manual:
            self.status.set("Zoeken naar updates…")

        def work():
            try:
                info = updater.check_latest()
                self.after(0, lambda: self._update_result(info, None, manual))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.after(0, lambda: self._update_result(None, err, manual))

        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, err, manual):
        if err:
            if manual:
                self.status.set("Updates zoeken mislukt: " + err)
            return
        if not info:
            if manual:
                self.status.set(f"✔ Je hebt de nieuwste versie (v{updater.current_version()}).")
            return
        self._show_update_bar(info)

    def _show_update_bar(self, info):
        b = self.update_bar
        for w in b.winfo_children():
            w.destroy()
        tk.Label(b, text=f"  ★  Nieuwe versie {info['version']} beschikbaar", bg=T.ACCENT_MID, fg="#ffffff",
                 font=self.F["bold"], pady=8).pack(side="left")
        # Vaste breedte: de knop verspringt niet als de tekst verandert.
        self.update_btn = tk.Label(b, text="Nu bijwerken", bg="#ffffff", fg=T.ACCENT_MID, width=16,
                                   font=self.F["bold"], cursor="hand2", padx=6, pady=3)
        self.update_btn.pack(side="right", padx=10)
        self.update_btn.bind("<Button-1>", lambda e: self.install_update(info))
        later = tk.Label(b, text="Later", bg=T.ACCENT_MID, fg="#e0e3ff", font=self.F["small"], cursor="hand2")
        later.pack(side="right")
        later.bind("<Button-1>", lambda e: b.pack_forget())
        self.update_later = later
        b.pack(fill="x", padx=14, pady=(0, 4), before=self.nb)

    def install_update(self, info):
        if not updater.is_installed_exe():
            messagebox.showinfo("Update", "Bijwerken kan alleen in JornBrowser.exe (niet vanuit de broncode).\n"
                                          "Haal de nieuwe versie van GitHub.")
            return
        if self.mgr.identities and not messagebox.askyesno(
                "Update", "Jorn Browser herstart na de update. Open vensters worden gesloten "
                          "(bewaarde identiteiten blijven bewaard). Doorgaan?"):
            return
        self.update_btn.unbind("<Button-1>")
        self.update_btn.configure(text="Downloaden…", cursor="")
        self.update_later.pack_forget()

        def progress(frac):
            self.after(0, lambda: self.update_btn.configure(text=f"Downloaden… {int(frac * 100)}%"))

        def work():
            try:
                new_exe = updater.download(info, progress)
                self.after(0, lambda: self._finish_update(new_exe))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.after(0, lambda: (messagebox.showerror("Update", f"Update mislukt: {err}"),
                                       self._show_update_bar(info)))

        threading.Thread(target=work, daemon=True).start()

    def _finish_update(self, new_exe):
        self.update_btn.configure(text="Herstarten…")

        # Vensters sluiten kan even duren: op de achtergrond, zodat de app
        # zichzelf blijft tekenen (anders blijven er stukjes oude tekst staan).
        def work():
            try:
                self.mgr.close_all()
                updater.install_and_restart(new_exe)
            except OSError as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("Update", f"Kon de update niet installeren: {err}"))
                return
            self.after(0, self.destroy)

        threading.Thread(target=work, daemon=True).start()

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
        srow = ttk.Frame(c3, style="Card.TFrame")
        srow.pack(anchor="w", pady=(8, 0))
        self.skip_slow = tk.BooleanVar(value=self.cfg.get("skip_slow_servers", True))
        ttk.Checkbutton(srow, text="Trage servers overslaan: trager dan", variable=self.skip_slow,
                        command=self._save_net).pack(side="left")
        self.max_latency = tk.StringVar(value=str(self.cfg.get("max_latency_ms", 500)))
        lat = ttk.Spinbox(srow, from_=50, to=2000, increment=50, width=6, textvariable=self.max_latency,
                          command=self._save_net)
        lat.pack(side="left", padx=(6, 4))
        lat.bind("<FocusOut>", lambda e: self._save_net())
        lat.bind("<Return>", lambda e: self._save_net())
        ttk.Label(srow, text="ms", style="Card.TLabel").pack(side="left")
        ttk.Label(c3, text="Alleen bij het openen van een venster: een lopende verbinding wordt nooit "
                           "gewisseld of verbroken. Metingen worden 12 uur onthouden. Een bewaarde "
                           "identiteit houdt altijd haar eigen server.",
                  style="CardMuted.TLabel", wraplength=520).pack(anchor="w", pady=(2, 0))
        self.webrtc = tk.BooleanVar(value=self.cfg["block_webrtc_leak"])
        ttk.Checkbutton(c3, text="WebRTC-lek blokkeren  (verbergt je echte IP, aanbevolen)",
                        variable=self.webrtc, command=self._save_net).pack(anchor="w", pady=(8, 0))
        ttk.Label(c3, text="IP-controlepagina  (voor ◎ Toon mijn IP)", style="Card.TLabel").pack(anchor="w", pady=(12, 0))
        self.check_url = tk.StringVar(value=self.cfg["check_url"])
        iprow = ttk.Frame(c3, style="Card.TFrame")
        iprow.pack(fill="x", pady=(6, 0))
        ttk.Entry(iprow, textvariable=self.check_url).pack(side="left", fill="x", expand=True)
        ttk.Button(iprow, text="Opslaan", command=self._save_settings).pack(side="left", padx=(8, 0))
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

        ct = T.card(f)
        ct.outer.pack(fill="x", pady=(12, 0))
        trow = ttk.Frame(ct, style="Card.TFrame")
        trow.pack(fill="x")
        ttk.Label(trow, text="Instellingen van extensies", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(trow, text="⚙ Extensies instellen", command=self.open_template).pack(side="right")
        ttk.Label(ct, text="Instellingen van je extensies (thema, weergave, tools) worden onthouden: "
                           "pas je iets aan in een venster, dan start elke nieuwe identiteit daarmee. "
                           "Hier kan je ze ook apart instellen. Cookies en websitedata gaan nooit mee.",
                  style="CardMuted.TLabel", wraplength=520).pack(anchor="w", pady=(4, 0))

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
        ttk.Label(c2, text="Eigen extensie (map met manifest.json)? Kopieer die map naar:",
                  style="CardMuted.TLabel").pack(anchor="w")
        self.ext_path_var = tk.StringVar(value=str(core.extensions_dir()))
        pe = ttk.Entry(c2, textvariable=self.ext_path_var, state="readonly")
        pe.pack(fill="x", pady=(4, 10))
        self.ext_frame = ttk.Frame(c2, style="Card.TFrame")
        self.ext_frame.pack(fill="both", expand=True)
        self._refresh_extensions()
        return f

    def _build_settings(self, parent):
        sf = T.ScrollFrame(parent)
        f = ttk.Frame(sf.inner, padding=(4, 14, 8, 10))
        f.pack(fill="both", expand=True)

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
        ttk.Button(row2, text="Opslaan", style="Small.TButton", command=self.save_mullvad).pack(side="left")
        ttk.Button(row2, text="Kopiëren", style="Small.TButton", command=self.copy_mullvad).pack(side="left", padx=4)
        ttk.Button(row2, text="Vergeten", style="SmallDanger.TButton", command=self.forget_mullvad).pack(side="left")
        row3 = ttk.Frame(m, style="Card.TFrame")
        row3.pack(fill="x", pady=(6, 0))
        ttk.Button(row3, text="Mijn account ↗", style="Small.TButton",
                   command=lambda: webbrowser.open(core.MULLVAD_ACCOUNT_URL)).pack(side="left")
        ttk.Button(row3, text="WireGuard-bestanden maken ↗", style="Small.TButton",
                   command=lambda: webbrowser.open(core.MULLVAD_WG_CONFIG_URL)).pack(side="left", padx=4)

        c = T.card(f)
        c.outer.pack(fill="x")
        ttk.Label(c, text="Chromium (chrome.exe)", style="CardTitle.TLabel").pack(anchor="w")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        found = core.find_chromium(self.cfg)
        self.chromium_path = tk.StringVar(value=str(found) if found else "")
        ttk.Entry(row, textvariable=self.chromium_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Kiezen…", command=self.pick_chromium).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Datamap", command=lambda: open_path(core.data_dir())).pack(side="left", padx=(6, 0))
        ttk.Button(c, text="Logboek openen (voor probleemoplossing)",
                   command=lambda: (core.log("logboek geopend"), open_path(core.log_path()))).pack(anchor="w", pady=(8, 0))
        self.auto_update = tk.BooleanVar(value=self.cfg.get("auto_update_check", True))

        def on_auto():
            self.cfg["auto_update_check"] = bool(self.auto_update.get())
            core.save_config(self.cfg)
        ttk.Checkbutton(c, text="Bij het opstarten op updates controleren", variable=self.auto_update,
                        command=on_auto).pack(anchor="w", pady=(8, 0))
        wrow = ttk.Frame(c, style="Card.TFrame")
        wrow.pack(anchor="w", pady=(8, 0))
        ttk.Label(wrow, text="Venster bij openen:", style="Card.TLabel").pack(side="left")
        names = {v: k for k, v in core.WINDOW_MODES.items()}
        self.window_mode = tk.StringVar(value=names.get(self.cfg.get("window_mode", "maximized"),
                                                        "Gemaximaliseerd"))
        wbox = ttk.Combobox(wrow, textvariable=self.window_mode, state="readonly", width=24,
                            values=list(core.WINDOW_MODES))
        wbox.pack(side="left", padx=(8, 0))

        def on_window(_e=None):
            self.cfg["window_mode"] = core.WINDOW_MODES[self.window_mode.get()]
            core.save_config(self.cfg)
            self.status.set("✔ Geldt vanaf de volgende identiteit. (Volledig scherm verlaten: F11)")
        wbox.bind("<<ComboboxSelected>>", on_window)
        self.allow_paste = tk.BooleanVar(value=self.cfg.get("devtools_allow_paste", True))

        def on_paste():
            self.cfg["devtools_allow_paste"] = bool(self.allow_paste.get())
            core.save_config(self.cfg)
            self.status.set("✔ Geldt vanaf de volgende identiteit.")
        ttk.Checkbutton(c, text="Plakken in de DevTools-console altijd toestaan (geen \"allow pasting\")",
                        variable=self.allow_paste, command=on_paste).pack(anchor="w", pady=(4, 0))
        ttk.Label(c, text="Plak nooit code die een onbekende je stuurt: zo stelen oplichters accounts.",
                  style="CardMuted.TLabel").pack(anchor="w", padx=(26, 0))

        c2 = T.card(f)
        c2.outer.pack(fill="x", pady=(12, 0))
        ttk.Label(c2, text="Startpagina", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(c2, text="Tip: met een VPN geeft Google vaak captchas. Deze zoekmachines niet.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(2, 0))
        self.start_url = tk.StringVar(value=self.cfg["start_url"])
        names = list(core.START_PAGES)
        current = next((n for n, u in core.START_PAGES.items() if u == self.cfg["start_url"]), "")
        self.start_choice = tk.StringVar(value=current or "Eigen adres")
        combo = ttk.Combobox(c2, textvariable=self.start_choice, values=names + ["Eigen adres"],
                             state="readonly")
        combo.pack(fill="x", pady=(6, 6))

        def on_pick(_e=None):
            url = core.START_PAGES.get(self.start_choice.get())
            if url:
                self.start_url.set(url)
                self._save_settings()
        combo.bind("<<ComboboxSelected>>", on_pick)
        sentry = ttk.Entry(c2, textvariable=self.start_url)
        sentry.pack(fill="x", pady=(0, 10))
        sentry.bind("<Return>", lambda e: self._save_settings())
        sentry.bind("<FocusOut>", lambda e: self._save_settings())

        ttk.Label(c2, text="Zoeken in de adresbalk", style="CardTitle.TLabel").pack(anchor="w")
        self.search_choice = tk.StringVar(value=self.cfg.get("search_engine", "DuckDuckGo"))
        scombo = ttk.Combobox(c2, textvariable=self.search_choice, state="readonly",
                              values=[n if n != "Google" else "Google (Chromium-standaard)"
                                      for n in core.SEARCH_ENGINES])
        if self.search_choice.get() == "Google":
            self.search_choice.set("Google (Chromium-standaard)")
        scombo.pack(fill="x", pady=(6, 10))

        def on_search(_e=None):
            choice = self.search_choice.get().split(" (")[0]
            self.cfg["search_engine"] = choice
            core.save_config(self.cfg)
            self.status.set(f"✔ Adresbalk zoekt via {choice} vanaf de volgende identiteit.")
        scombo.bind("<<ComboboxSelected>>", on_search)
        return sf

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

    def open_template(self):
        self._run_bg(self.mgr.open_template,
                     lambda i: "⚙ Stel je extensies in en sluit dan het venster. Nieuwe identiteiten "
                               "starten met deze instellingen.", "Sjabloon openen…")

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
        self.cfg["skip_slow_servers"] = bool(self.skip_slow.get())
        try:
            self.cfg["max_latency_ms"] = max(50, min(2000, int(self.max_latency.get())))
        except ValueError:
            pass
        self.max_latency.set(str(self.cfg["max_latency_ms"]))
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
