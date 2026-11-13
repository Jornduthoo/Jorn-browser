"""Uiterlijk van Jorn Browser: donker thema, verloopknoppen, kaarten."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

# Kleuren (afgestemd op het logo: violet -> indigo -> cyaan)
BG = "#0d0f1a"
PANEL = "#151829"
PANEL_HI = "#1c2036"
BORDER = "#262b47"
TEXT = "#e8eaf6"
MUTED = "#8a90b0"
ACCENT1 = "#8b5cf6"
ACCENT2 = "#22d3ee"
ACCENT_MID = "#6366f1"
OK = "#34d399"
WARN = "#fbbf24"
DANGER = "#f87171"


def resource(name: str) -> Path:
    """Pad naar een bestand in assets/ (ook binnen de PyInstaller-exe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def pick_font(root: tk.Misc) -> tuple[str, str]:
    fams = set(tkfont.families(root))
    for normal, bold in (("Segoe UI", "Segoe UI Semibold"), ("Inter", "Inter"),
                         ("Helvetica Neue", "Helvetica Neue"), ("DejaVu Sans", "DejaVu Sans")):
        if normal in fams:
            return normal, (bold if bold in fams else normal)
    return "TkDefaultFont", "TkDefaultFont"


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = _hex(a)
    rb, gb, bb = _hex(b)
    return f"#{round(ra + (rb - ra) * t):02x}{round(ga + (gb - ga) * t):02x}{round(ba + (bb - ba) * t):02x}"


def _lighten(c: str, t: float) -> str:
    return _mix(c, "#ffffff", t)


def apply(root: tk.Tk) -> dict:
    """Zet het donkere thema op alle ttk-widgets. Geeft de lettertypes terug."""
    normal, bold = pick_font(root)
    fonts = {
        "body": (normal, 10),
        "small": (normal, 9),
        "bold": (bold, 10, "bold") if bold == normal else (bold, 10),
        "h2": (bold, 12, "bold") if bold == normal else (bold, 12),
        "title": (bold, 18, "bold") if bold == normal else (bold, 18),
        "hero": (bold, 15, "bold") if bold == normal else (bold, 15),
        "big": (bold, 16, "bold") if bold == normal else (bold, 16),
    }
    root.configure(bg=BG)
    for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(named).configure(family=normal, size=10)
        except tk.TclError:
            pass
    # Kleuren voor standaarddialogen/lijsten
    root.option_add("*Listbox.background", PANEL_HI)
    root.option_add("*Listbox.foreground", TEXT)

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL_HI,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                troughcolor=PANEL, focuscolor=ACCENT_MID, font=fonts["body"])
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=fonts["small"])
    s.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    s.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=fonts["small"])
    s.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=fonts["h2"])
    s.configure("Title.TLabel", background=BG, foreground=TEXT, font=fonts["title"])
    s.configure("Big.TLabel", background=PANEL, foreground=TEXT, font=fonts["big"])

    s.configure("TButton", background=PANEL_HI, foreground=TEXT, borderwidth=1,
                bordercolor=BORDER, lightcolor=PANEL_HI, darkcolor=PANEL_HI,
                padding=(12, 7), font=fonts["body"])
    s.map("TButton",
          background=[("pressed", BORDER), ("active", "#252a46")],
          bordercolor=[("active", ACCENT_MID)],
          lightcolor=[("active", "#252a46")], darkcolor=[("active", "#252a46")])
    s.configure("Danger.TButton", foreground=DANGER)
    s.configure("Ghost.TButton", background=PANEL, lightcolor=PANEL, darkcolor=PANEL)

    s.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG, lightcolor=BG,
                darkcolor=BG, tabmargins=(0, 4, 0, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 8),
                borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG, font=fonts["bold"])
    s.map("TNotebook.Tab",
          background=[("selected", PANEL_HI), ("active", PANEL)],
          foreground=[("selected", "#ffffff"), ("active", TEXT)],
          bordercolor=[("selected", PANEL_HI)], lightcolor=[("selected", ACCENT_MID)],
          darkcolor=[("selected", PANEL_HI)], expand=[("selected", (0, 0, 0, 0))])

    for w in ("TRadiobutton", "TCheckbutton"):
        s.configure(w, background=PANEL, foreground=TEXT, indicatorbackground=PANEL_HI,
                    indicatorforeground=ACCENT2, indicatormargin=(0, 0, 8, 0), padding=(0, 4))
        s.map(w, background=[("active", PANEL)],
              indicatorbackground=[("selected", ACCENT_MID), ("active", BORDER)],
              foreground=[("disabled", MUTED)])
    s.configure("TEntry", fieldbackground=PANEL_HI, foreground=TEXT, insertcolor=TEXT,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
    s.map("TEntry", bordercolor=[("focus", ACCENT_MID)], lightcolor=[("focus", ACCENT_MID)],
          fieldbackground=[("readonly", PANEL)], foreground=[("readonly", MUTED)])
    s.configure("TCombobox", fieldbackground=PANEL_HI, background=PANEL_HI, foreground=TEXT,
                arrowcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL_HI)], foreground=[("readonly", TEXT)],
          selectbackground=[("readonly", PANEL_HI)], selectforeground=[("readonly", TEXT)],
          bordercolor=[("focus", ACCENT_MID)])
    root.option_add("*TCombobox*Listbox.background", PANEL_HI)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_MID)
    s.configure("TSeparator", background=BORDER)
    s.configure("Vertical.TScrollbar", background=PANEL_HI, troughcolor=PANEL, arrowcolor=MUTED,
                bordercolor=PANEL, lightcolor=PANEL_HI, darkcolor=PANEL_HI)
    return fonts


def card(parent, padding=16) -> ttk.Frame:
    """Een paneel met lichtere achtergrond en een dun randje."""
    outer = tk.Frame(parent, bg=BORDER, highlightthickness=0)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    inner.outer = outer  # type: ignore[attr-defined]
    return inner


def listbox(parent, height=4) -> tk.Listbox:
    return tk.Listbox(parent, height=height, bg=PANEL_HI, fg=TEXT, selectbackground=ACCENT_MID,
                      selectforeground="#ffffff", highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=ACCENT_MID, borderwidth=0, activestyle="none")


class GradientButton(tk.Canvas):
    """Grote knop met kleurverloop, afgeronde hoeken en hover-effect."""

    def __init__(self, parent, text: str, command, height=60, radius=14,
                 colors=(ACCENT1, ACCENT_MID, ACCENT2), font=None, subtext: str = "",
                 bg: str = BG):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.subtext, self.command = text, subtext, command
        self.radius, self.colors, self.font = radius, colors, font
        self.hover = self.pressed = self.disabled = False
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.redraw()

    def _release(self, e):
        was = self.pressed
        self._set(pressed=False)
        if was and not self.disabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set_busy(self, busy: bool, text: str | None = None):
        self.disabled = busy
        if text is not None:
            self.text = text
        self.configure(cursor="watch" if busy else "hand2")
        self.redraw()

    def _color_at(self, t: float) -> str:
        c = self.colors
        if len(c) == 2:
            col = _mix(c[0], c[1], t)
        else:
            col = _mix(c[0], c[1], t * 2) if t < 0.5 else _mix(c[1], c[2], (t - 0.5) * 2)
        if self.disabled:
            return _mix(col, PANEL_HI, 0.55)
        if self.pressed:
            return _mix(col, "#000000", 0.15)
        if self.hover:
            return _lighten(col, 0.12)
        return col

    def redraw(self):
        self.delete("all")
        w, h, r = self.winfo_width(), self.winfo_height(), self.radius
        if w < 4:
            return
        for x in range(w):
            # verticale lijn, ingekort in de hoeken -> afgeronde vorm
            edge = min(x + 0.5, w - x - 0.5)  # afstand tot de dichtstbijzijnde zijkant
            if edge < r:
                dist = min(r, r - edge)
                d = r - (r * r - dist * dist) ** 0.5
            else:
                d = 0
            self.create_line(x, d, x, h - d, fill=self._color_at(x / max(1, w - 1)))
        if h >= 60:  # zachte glans bovenaan de grote knop
            self.create_line(r, 1, w - r, 1, fill=_lighten(self._color_at(0.5), 0.35))
        cy = h / 2 - (8 if self.subtext else 0)
        self.create_text(w / 2, cy, text=self.text, fill="#ffffff", font=self.font)
        if self.subtext:
            self.create_text(w / 2, cy + 20, text=self.subtext, fill="#e6e9ff",
                             font=(self.font[0], 9) if self.font else None)


class Pill(tk.Canvas):
    """Klein afgerond label met gekleurd bolletje (status)."""

    def __init__(self, parent, font, bg=BG):
        super().__init__(parent, height=28, width=10, bg=bg, highlightthickness=0, bd=0)
        self.font = font
        self.set("…", MUTED)

    def set(self, text: str, color: str):
        self.delete("all")
        tmp = self.create_text(0, 0, text=text, font=self.font, anchor="nw")
        x1, y1, x2, y2 = self.bbox(tmp)
        self.delete(tmp)
        w = (x2 - x1) + 40
        h = 28
        self.configure(width=w)
        r = h // 2
        fill = PANEL
        self.create_oval(0, 0, h, h, fill=fill, outline=fill)
        self.create_oval(w - h, 0, w, h, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_oval(12, r - 4, 20, r + 4, fill=color, outline=color)
        self.create_text(28, r, text=text, fill=TEXT, font=self.font, anchor="w")
