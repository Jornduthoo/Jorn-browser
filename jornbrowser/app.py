"""Jorn Browser: venster met de knop "Nieuwe identiteit"."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from . import core
except ImportError:  # gestart als los script / PyInstaller
    import core  # type: ignore


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
        self.geometry("560x520")
        self.minsize(480, 440)
        self.cfg = core.load_config()
        self.mgr = core.IdentityManager(self.cfg)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        nb.add(self._build_main(nb), text="Identiteit")
        nb.add(self._build_network(nb), text="Netwerk")
        nb.add(self._build_extensions(nb), text="Extensies")
        nb.add(self._build_settings(nb), text="Instellingen")

        self.status = tk.StringVar(value="Klaar.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        self.bind_all("<Control-n>", lambda e: self.new_identity())
        self.bind_all("<Control-N>", lambda e: self.new_identity())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(1000, self._tick)

        if not core.find_chromium(self.cfg):
            self.after(300, self._warn_no_chromium)

    # ------------------------------------------------------------------ tabbladen

    def _build_main(self, parent):
        f = ttk.Frame(parent, padding=12)
        style = ttk.Style(self)
        style.configure("Big.TButton", font=("Segoe UI", 14, "bold"), padding=12)

        ttk.Button(f, text="🔄  Nieuwe identiteit  (Ctrl+N)", style="Big.TButton",
                   command=self.new_identity).pack(fill="x")
        ttk.Label(f, text="Sluit alle vensters, wist cookies/cache/geschiedenis en start "
                          "opnieuw met een vers profiel (en een andere proxy als die aan staat).",
                  wraplength=500, foreground="#555").pack(fill="x", pady=(6, 12))

        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="➕ Extra identiteit (apart venster)", command=self.extra_identity).pack(side="left")
        ttk.Button(row, text="🌐 Toon mijn IP", command=self.show_ip).pack(side="left", padx=6)
        ttk.Button(row, text="✖ Alles sluiten & wissen", command=self.close_all).pack(side="right")

        ttk.Label(f, text="Actieve identiteiten:").pack(anchor="w", pady=(14, 2))
        self.ident_list = tk.Listbox(f, height=8)
        self.ident_list.pack(fill="both", expand=True)
        ttk.Button(f, text="Geselecteerde sluiten & wissen", command=self.close_selected).pack(anchor="e", pady=(6, 0))
        return f

    def _build_network(self, parent):
        f = ttk.Frame(parent, padding=12)
        self.proxy_mode = tk.StringVar(value=self.cfg["proxy_mode"])
        ttk.Radiobutton(f, text="Geen proxy: mijn VPN-app (bv. VPN Unlimited) bepaalt het IP",
                        value="none", variable=self.proxy_mode, command=self._save_net).pack(anchor="w")
        ttk.Label(f, text="Ander IP = in je VPN-app van server wisselen, daarna 'Nieuwe identiteit'.",
                  foreground="#555").pack(anchor="w", padx=22)
        ttk.Radiobutton(f, text="Proxylijst: elke identiteit krijgt automatisch een ander IP",
                        value="list", variable=self.proxy_mode, command=self._save_net).pack(anchor="w", pady=(10, 0))

        order = ttk.Frame(f)
        order.pack(anchor="w", padx=22, pady=4)
        self.proxy_order = tk.StringVar(value=self.cfg["proxy_order"])
        ttk.Label(order, text="Volgorde:").pack(side="left")
        ttk.Radiobutton(order, text="willekeurig", value="random", variable=self.proxy_order,
                        command=self._save_net).pack(side="left")
        ttk.Radiobutton(order, text="na elkaar", value="sequential", variable=self.proxy_order,
                        command=self._save_net).pack(side="left")

        btns = ttk.Frame(f)
        btns.pack(anchor="w", padx=22, pady=4)
        ttk.Button(btns, text="proxies.txt bewerken", command=self.edit_proxies).pack(side="left")
        ttk.Button(btns, text="Mullvad-lijst ophalen", command=self.fetch_mullvad).pack(side="left", padx=6)
        self.proxy_count = tk.StringVar()
        ttk.Label(f, textvariable=self.proxy_count, foreground="#555").pack(anchor="w", padx=22)
        self._refresh_proxy_count()

        ttk.Separator(f).pack(fill="x", pady=12)
        self.webrtc = tk.BooleanVar(value=self.cfg["block_webrtc_leak"])
        ttk.Checkbutton(f, text="WebRTC-lek blokkeren (aanbevolen: verbergt je echte IP)",
                        variable=self.webrtc, command=self._save_net).pack(anchor="w")
        return f

    def _build_extensions(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Label(f, text="Plak een Chrome Web Store-link (of extensie-ID):").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        self.ext_url = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.ext_url)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.add_extension())
        ttk.Button(row, text="Toevoegen", command=self.add_extension).pack(side="left", padx=(6, 0))

        ttk.Label(f, text="Geïnstalleerd (vinkje = aan). Wijzigingen gelden vanaf de volgende identiteit.",
                  foreground="#555").pack(anchor="w", pady=(10, 2))
        self.ext_frame = ttk.Frame(f)
        self.ext_frame.pack(fill="both", expand=True)

        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text="Extensiemap openen", command=lambda: open_path(core.extensions_dir())).pack(side="left")
        ttk.Button(row2, text="Vernieuwen", command=self._refresh_extensions).pack(side="left", padx=6)
        self._refresh_extensions()
        return f

    def _build_settings(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Label(f, text="Chromium (chrome.exe):").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        found = core.find_chromium(self.cfg)
        self.chromium_path = tk.StringVar(value=str(found) if found else "")
        ttk.Entry(row, textvariable=self.chromium_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Kiezen…", command=self.pick_chromium).pack(side="left", padx=(6, 0))

        ttk.Label(f, text="Startpagina:").pack(anchor="w", pady=(10, 0))
        self.start_url = tk.StringVar(value=self.cfg["start_url"])
        ttk.Entry(f, textvariable=self.start_url).pack(fill="x", pady=4)
        ttk.Label(f, text="IP-controlepagina:").pack(anchor="w", pady=(6, 0))
        self.check_url = tk.StringVar(value=self.cfg["check_url"])
        ttk.Entry(f, textvariable=self.check_url).pack(fill="x", pady=4)
        ttk.Button(f, text="Opslaan", command=self._save_settings).pack(anchor="e", pady=8)

        ttk.Separator(f).pack(fill="x", pady=8)
        ttk.Button(f, text="Datamap openen", command=lambda: open_path(core.data_dir())).pack(anchor="w")
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

    def new_identity(self):
        self.status.set("Nieuwe identiteit starten…")
        self.update_idletasks()
        self._run(self.mgr.new_identity, lambda i: f"✔ {i.describe()}")

    def extra_identity(self):
        self._run(self.mgr.spawn, lambda i: f"✔ Extra: {i.describe()}")

    def close_all(self):
        self._run(self.mgr.close_all, "Alle identiteiten gesloten en gewist.")

    def close_selected(self):
        sel = self.ident_list.curselection()
        if sel:
            ident = self.mgr.identities[sel[0]]
            self._run(lambda: self.mgr.close(ident), f"Identiteit #{ident.number} gewist.")

    def show_ip(self):
        """Opent de IP-controlepagina in elke actieve identiteit (dus via haar eigen proxy)."""
        if not self.mgr.identities:
            self._run(lambda: self.mgr.spawn(self.cfg["check_url"]), lambda i: f"✔ {i.describe()}")
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

    def _save_settings(self):
        self.cfg["chromium_path"] = self.chromium_path.get().strip()
        self.cfg["start_url"] = self.start_url.get().strip() or "about:blank"
        self.cfg["check_url"] = self.check_url.get().strip() or core.DEFAULT_CONFIG["check_url"]
        core.save_config(self.cfg)
        self.status.set("Instellingen opgeslagen.")

    def _refresh_proxy_count(self):
        n = len(core.load_proxies())
        self.proxy_count.set(f"{n} proxy's in proxies.txt")

    def _refresh_extensions(self):
        for w in self.ext_frame.winfo_children():
            w.destroy()
        exts = core.list_extensions()
        if not exts:
            ttk.Label(self.ext_frame, text="(nog geen extensies)", foreground="#888").pack(anchor="w")
        for ext in exts:
            row = ttk.Frame(self.ext_frame)
            row.pack(fill="x")
            var = tk.BooleanVar(value=ext.enabled)
            ttk.Checkbutton(row, text=ext.name, variable=var,
                            command=lambda e=ext, v=var: core.set_extension_enabled(e, v.get())).pack(side="left")
            ttk.Button(row, text="Verwijderen", width=11,
                       command=lambda e=ext: (core.remove_extension(e), self._refresh_extensions())).pack(side="right")

    def _refresh_identities(self):
        self.ident_list.delete(0, "end")
        for ident in self.mgr.identities:
            self.ident_list.insert("end", ident.describe())

    def _tick(self):
        if self.mgr.reap():
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
