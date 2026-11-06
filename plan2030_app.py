"""Spar- och Pensionsplan – översikt med sidopanel, konton och inkomstperioder."""

from __future__ import annotations

import calendar
import ctypes
import os
import re
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import utdelning_core
from paminnelse import texter_att_visa
from aktiehandel_panel import AktieHandelApp
from utdelning_panel import UtdelningApp
from plan_engine import (
    ANTAL_KONTON,
    Engangsinsattning,
    Engangsuttag,
    KontoConfig,
    KontoTransaktion,
    MANAD_NAMN_TILL_NUMMER,
    MANADER,
    Overforing,
    Ranteandring,
    PlanConfig,
    formatera_kr,
    konto_visningsnamn,
    kora_plan_med_transaktioner,
    samlad_ranta_visad,
    transaktioner_for_konto,
)
from plan_save import (
    hamta_aktiv_plan,
    hamta_installningar,
    har_visat_manual,
    ladda_data,
    lista_planer,
    markera_forsta_start_klar,
    markera_manual_visad,
    migrera_gammal_sparfil,
    normalisera_personer,
    normalisera_plan_namn,
    plan_fil,
    spara_aktiv_plan,
    spara_data,
    spara_installningar,
    ta_bort_plan,
    uppgradera_plan_data,
)
from saldo_pdf import skriv_kontoutdrag_pdf

TEMA = {
    "bg": "#F3EFE6",
    "kort": "#FFFcf7",
    "sida": "#16343F",
    "sida_aktiv": "#1F4A58",
    "accent": "#2A9D8F",
    "accent_mork": "#1E7A70",
    "text": "#17323C",
    "muted": "#6B7C83",
    "linje": "#E4DCCB",
    "pengar": "#0F3D3E",
    "fara": "#B03A2E",
    "vit": "#FFFFFF",
}

MAX_AR = 2060
OVERSIKT_START_AR = 2026
MANUAL_FIL = "Manual.pdf"
IKON_FIL = "pension.ico"


def heltal_varde(text: str) -> int:
    text = str(text).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return 0
    return int(float(text.replace(",", ".")))


def decimal_varde(text: str, standard: float) -> float:
    text = str(text).strip().replace(" ", "").replace(",", ".")
    if not text:
        return standard
    return float(text)


def app_katalog() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def hamta_bundlad_fil(namn: str) -> Path | None:
    kandidater: list[Path] = []
    if getattr(sys, "frozen", False):
        kandidater.append(Path(sys.executable).parent / namn)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            kandidater.append(Path(meipass) / namn)
    else:
        kandidater.append(Path(__file__).parent / namn)
    for sokvag in kandidater:
        if sokvag.is_file():
            return sokvag
    return None


def hamta_ikon_sokvag() -> Path | None:
    return hamta_bundlad_fil(IKON_FIL)


def hamta_manual_sokvag() -> Path | None:
    return hamta_bundlad_fil(MANUAL_FIL)


def dagens_ar_manad() -> tuple[int, int]:
    idag = date.today()
    return idag.year, idag.month


def ar_lista() -> list[int]:
    nu, _ = dagens_ar_manad()
    return list(range(OVERSIKT_START_AR, max(MAX_AR, nu + 25) + 1))


def tomt_konto() -> dict:
    return {
        "aktiv": False,
        "namn": "",
        "sparat": "0",
        "ranta": "2.4",
        "skatt": "30",
        "rante_andringar": [],
        "overskott": False,
        "manadsranta": False,
    }


def standard_konton() -> list[dict]:
    return [tomt_konto() for _ in range(ANTAL_KONTON)]


PERIOD_NYCKLAR = frozenset({
    "ar_fran", "manad_fran", "ar_till", "manad_till", "person1", "person2", "behov", "anteckning",
})
UTDELNINGSKONTO = "utdelning"
KURSVINSTKONTO = "kursvinst"


def gissa_borstyp(raw: dict) -> str:
    """Planer från före borstyp: Nordnet/Aktiekonto var utdelningskontot och Avanza/Aktier kursvinstkontot."""
    typ = str(raw.get("borstyp") or "")
    if typ in (UTDELNINGSKONTO, KURSVINSTKONTO):
        return typ
    namn = str(raw.get("namn", "")).strip().casefold()
    if namn in ("nordnet", "aktiekonto"):
        return UTDELNINGSKONTO
    if namn in ("avanza", "aktier"):
        return KURSVINSTKONTO
    return ""


def tomt_borskonto(namn: str, skatt: str, typ: str) -> dict:
    konto = tomt_konto()
    konto.update({
        "aktiv": True,
        "namn": namn,
        "borstyp": typ,
        "ranta": "0",
        "skatt": skatt,
        "aktier": {"stocks": [], "cash": 0, "dividends": [], "kontanter": 0},
    })
    return konto


def konto_ar_aktivt(konto: dict) -> bool:
    if konto.get("aktiv"):
        return True
    namn = str(konto.get("namn", "")).strip()
    try:
        saldo = heltal_varde(str(konto.get("sparat", "0")))
    except ValueError:
        saldo = 0
    return bool(namn or saldo)


def _manad_nyckel(ar: int, manad: int) -> int:
    return ar * 12 + manad


def _rorelse_sortering(post: dict) -> tuple[int, int, int, str, int]:
    """Sorteringsnyckel: år, månad, dag, typ, belopp – tidigast först."""
    try:
        ar = int(heltal_varde(str(post.get("ar", 0))))
    except (TypeError, ValueError):
        ar = 0
    manad = _tolka_rorelse_manad(post)
    dag = _tolka_dag(post, ar, manad)
    typ = str(post.get("typ", ""))
    try:
        belopp = int(heltal_varde(str(post.get("belopp", 0))))
    except (TypeError, ValueError):
        belopp = 0
    return (ar, manad, dag, typ, belopp)


def _tolka_dag(post: dict, ar: int | None = None, manad: int | None = None) -> int:
    manad = manad if manad is not None else _tolka_rorelse_manad(post)
    if ar is None:
        try:
            ar = int(heltal_varde(str(post.get("ar", 2026))))
        except (TypeError, ValueError):
            ar = 2026
    try:
        dag = int(heltal_varde(str(post.get("dag", 1))))
    except (TypeError, ValueError):
        dag = 1
    return min(max(dag, 1), calendar.monthrange(ar, manad)[1])


def formatera_datum(ar: int, manad: int, dag: int) -> str:
    return f"{dag} {MANADER[manad - 1]} {ar}"


def _tolka_rorelse_manad(post: dict, standard: int = 1) -> int:
    raw = post.get("manad", standard)
    if isinstance(raw, int):
        return raw if 1 <= raw <= 12 else standard
    text = str(raw).strip()
    if text in MANAD_NAMN_TILL_NUMMER:
        return MANAD_NAMN_TILL_NUMMER[text]
    try:
        nr = int(heltal_varde(text))
        return nr if 1 <= nr <= 12 else standard
    except ValueError:
        return standard


def generera_manader(
    ar_fran: int,
    ar_till: int,
    manad_fran: int = 1,
    manad_till: int = 12,
) -> list[tuple[int, int]]:
    manader: list[tuple[int, int]] = []
    for ar in range(ar_fran, ar_till + 1):
        m_start = manad_fran if ar == ar_fran else 1
        m_slut = manad_till if ar == ar_till else 12
        for manad in range(m_start, m_slut + 1):
            manader.append((ar, manad))
    return manader


def knapp(parent: tk.Misc, text: str, cmd, *, bg: str, fg: str = "#FFFFFF", pady: int = 8) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=cmd,
        bg=bg,
        fg=fg,
        activebackground=bg,
        activeforeground=fg,
        relief=tk.FLAT,
        bd=0,
        padx=16,
        pady=pady,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    )


def centrera(fonster: tk.Misc, bredd: int, hojd: int) -> None:
    fonster.update_idletasks()
    skarm_b = fonster.winfo_screenwidth()
    skarm_h = fonster.winfo_screenheight()
    x = max(0, (skarm_b - bredd) // 2)
    y = max(0, (skarm_h - hojd) // 2)
    fonster.geometry(f"{bredd}x{hojd}+{x}+{y}")


class NyPlanDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, titel: str = "Ny plan", meddelande: str = "") -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.title(titel)
        self.configure(bg=TEMA["bg"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()

        kort = tk.Frame(self, bg=TEMA["kort"], padx=24, pady=20)
        kort.pack(padx=16, pady=16)
        tk.Label(kort, text=titel, font=("Segoe UI", 16, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)
        if meddelande:
            tk.Label(
                kort, text=meddelande, font=("Segoe UI", 10), bg=TEMA["kort"], fg=TEMA["muted"],
            ).pack(anchor=tk.W, pady=(4, 12))

        tk.Label(kort, text="Planens namn", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self.namn = tk.StringVar()
        tk.Entry(kort, textvariable=self.namn, font=("Segoe UI", 12), width=28).pack(anchor=tk.W, pady=(2, 12))

        self.antal = tk.IntVar(value=2)
        tk.Label(kort, text="Antal personer", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        valj = tk.Frame(kort, bg=TEMA["kort"])
        valj.pack(anchor=tk.W, pady=(2, 12))
        tk.Radiobutton(valj, text="En", variable=self.antal, value=1, bg=TEMA["kort"], command=self._synka).pack(side=tk.LEFT)
        tk.Radiobutton(valj, text="Två", variable=self.antal, value=2, bg=TEMA["kort"], command=self._synka).pack(side=tk.LEFT)

        tk.Label(kort, text="Namn person 1", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self.p1 = tk.StringVar()
        tk.Entry(kort, textvariable=self.p1, font=("Segoe UI", 11), width=28).pack(anchor=tk.W, pady=(2, 8))
        self.p2_lbl = tk.Label(kort, text="Namn person 2", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold"))
        self.p2_lbl.pack(anchor=tk.W)
        self.p2 = tk.StringVar()
        self.p2_entry = tk.Entry(kort, textvariable=self.p2, font=("Segoe UI", 11), width=28)
        self.p2_entry.pack(anchor=tk.W, pady=(2, 16))

        knappar = tk.Frame(kort, bg=TEMA["kort"])
        knappar.pack(fill=tk.X)
        knapp(knappar, "Avbryt", self._avbryt, bg="#8A9AA0", pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        knapp(knappar, "Skapa plan", self._ok, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._avbryt())
        self.protocol("WM_DELETE_WINDOW", self._avbryt)
        self.update_idletasks()
        centrera(self, self.winfo_reqwidth() + 8, self.winfo_reqheight() + 8)
        self.lift()
        self.focus_force()

    def _synka(self) -> None:
        tva = self.antal.get() == 2
        tillstand = tk.NORMAL if tva else tk.DISABLED
        self.p2_entry.configure(state=tillstand)
        self.p2_lbl.configure(fg=TEMA["text"] if tva else TEMA["muted"])

    def _ok(self) -> None:
        try:
            plan_namn = normalisera_plan_namn(self.namn.get())
        except ValueError as err:
            messagebox.showerror("Fel", str(err), parent=self)
            return
        antal = 1 if self.antal.get() == 1 else 2
        namn = [self.p1.get().strip()]
        if antal == 2:
            namn.append(self.p2.get().strip())
        self.result = {"plan_namn": plan_namn, "antal": antal, "namn": namn}
        self.grab_release()
        self.destroy()

    def _avbryt(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


class Rullhjul(tk.Canvas):
    """Animerad rulle för år eller månad."""

    ITEM_H = 46

    def __init__(self, parent: tk.Misc, varden: list[str], index: int, on_change, bredd: int = 168, on_utanfor=None, text_utanfor=None) -> None:
        super().__init__(parent, width=bredd, height=190, highlightthickness=0, bg=TEMA["kort"], bd=0)
        self.varden = varden
        self.index = max(0, min(index, len(varden) - 1))
        self.visuellt = float(self.index)
        self.on_change = on_change
        self.on_utanfor = on_utanfor
        self.text_utanfor = text_utanfor
        self._job: str | None = None
        self.bind("<MouseWheel>", self._hjul)
        self.bind("<Button-1>", self._klick)
        self.bind("<Up>", lambda _e: self._steg(-1))
        self.bind("<Down>", lambda _e: self._steg(1))
        self.focus_set()
        self._rita()

    def _hjul(self, event: tk.Event) -> None:
        self._steg(-1 if event.delta > 0 else 1)

    def _klick(self, event: tk.Event) -> None:
        mitt = self.winfo_height() / 2
        diff = int(round((event.y - mitt) / self.ITEM_H))
        self._steg(diff)

    def _steg(self, diff: int) -> None:
        if not diff:
            return
        nytt = self.index + diff
        if nytt < 0 or nytt >= len(self.varden):
            if self.on_utanfor and self.on_utanfor(diff):
                return
        self.satt_index(nytt)

    def satt_index(self, index: int, animera: bool = True, tyst: bool = False) -> None:
        nytt = max(0, min(int(index), len(self.varden) - 1))
        if nytt == self.index and abs(self.visuellt - nytt) < 0.02:
            return
        self.index = nytt
        if not animera:
            self.visuellt = float(nytt)
            self._rita()
        else:
            self._animera()
        if self.on_change and not tyst:
            self.on_change(self.index)

    def satt_varden(self, varden: list[str], index: int) -> None:
        self.varden = varden
        self.index = max(0, min(int(index), len(varden) - 1))
        self.visuellt = float(self.index)
        self._rita()

    def _animera(self) -> None:
        if self._job:
            self.after_cancel(self._job)
        delta = self.index - self.visuellt
        if abs(delta) < 0.03:
            self.visuellt = float(self.index)
            self._rita()
            self._job = None
            return
        self.visuellt += delta * 0.28
        self._rita()
        self._job = self.after(16, self._animera)

    def _rita(self) -> None:
        self.delete("all")
        w = int(self.winfo_reqwidth() or 168)
        h = int(self.winfo_reqheight() or 230)
        mitt = h / 2
        self.create_rectangle(8, mitt - 26, w - 8, mitt + 26, fill="#E7F4F1", outline="", width=0)
        spann = (mitt + 40) / self.ITEM_H
        lag = int(self.visuellt - spann)
        if self.visuellt - spann < lag:
            lag -= 1
        hog = int(self.visuellt + spann) + 2
        for i in range(lag, hog + 1):
            if 0 <= i < len(self.varden):
                text = self.varden[i]
            elif self.text_utanfor:
                text = self.text_utanfor(i)
                if not text:
                    continue
            else:
                continue
            y = mitt + (i - self.visuellt) * self.ITEM_H
            if y < -30 or y > h + 30:
                continue
            avstand = abs(i - self.visuellt)
            if avstand < 0.45:
                farg, storlek, vikt = TEMA["pengar"], 18, "bold"
            elif avstand < 1.3:
                farg, storlek, vikt = TEMA["text"], 14, "normal"
            else:
                farg, storlek, vikt = "#B0BBB8", 12, "normal"
            self.create_text(w / 2, y, text=text, fill=farg, font=("Segoe UI", storlek, vikt))


class DatumValjare(tk.Frame):
    def __init__(self, parent: tk.Misc, ar: int, manad: int, dag: int, on_change) -> None:
        super().__init__(parent, bg=TEMA["kort"])
        self.on_change = on_change
        self.ar_varden = ar_lista()
        self.manad = manad
        self.ar = ar if ar in self.ar_varden else self.ar_varden[0]
        self.dag = min(max(dag, 1), calendar.monthrange(self.ar, self.manad)[1])

        tk.Label(
            self, text="Visa saldo", font=("Segoe UI", 11), bg=TEMA["kort"], fg=TEMA["muted"],
        ).pack(pady=(8, 0))

        rullar = tk.Frame(self, bg=TEMA["kort"])
        rullar.pack(pady=8)
        self.dag_hjul = Rullhjul(
            rullar, [str(d) for d in range(1, calendar.monthrange(self.ar, self.manad)[1] + 1)],
            self.dag - 1, self._pa_dag, bredd=72, on_utanfor=self._rulla_dag,
            text_utanfor=self._dag_text,
        )
        self.dag_hjul.pack(side=tk.LEFT, padx=6)
        self.manad_hjul = Rullhjul(
            rullar, [m.capitalize() for m in MANADER], self.manad - 1, self._pa_manad, bredd=150,
            on_utanfor=self._rulla_manad, text_utanfor=self._manad_text,
        )
        self.manad_hjul.pack(side=tk.LEFT, padx=6)
        ar_idx = self.ar_varden.index(self.ar)
        self.ar_hjul = Rullhjul(
            rullar, [str(a) for a in self.ar_varden], ar_idx, self._pa_ar, bredd=108,
        )
        self.ar_hjul.pack(side=tk.LEFT, padx=6)

        nav = tk.Frame(self, bg=TEMA["kort"])
        nav.pack(pady=(0, 10))
        tk.Button(
            nav, text="◂  förra", command=lambda: self._nudge(-1),
            bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT, cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=12)
        tk.Button(
            nav, text="nästa  ▸", command=lambda: self._nudge(1),
            bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT, cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=12)

    def valt(self) -> tuple[int, int, int]:
        return self.ar, self.manad, self.dag

    def satt(self, ar: int, manad: int, dag: int) -> None:
        if ar not in self.ar_varden:
            ar = self.ar_varden[0]
        manad = min(max(manad, 1), 12)
        dag = min(max(dag, 1), calendar.monthrange(ar, manad)[1])
        self.ar = ar
        self.manad = manad
        self.dag = dag
        self.ar_hjul.satt_index(self.ar_varden.index(ar), animera=False, tyst=True)
        self.manad_hjul.satt_index(manad - 1, animera=False, tyst=True)
        self._synka_dagar()

    def _synka_dagar(self) -> None:
        maxdag = calendar.monthrange(self.ar, self.manad)[1]
        self.dag = min(self.dag, maxdag)
        self.dag_hjul.satt_varden([str(d) for d in range(1, maxdag + 1)], self.dag - 1)

    def _pa_dag(self, index: int) -> None:
        self.dag = index + 1
        self.on_change()

    def _pa_manad(self, index: int) -> None:
        self.manad = index + 1
        self._synka_dagar()
        self.on_change()

    def _pa_ar(self, index: int) -> None:
        self.ar = self.ar_varden[index]
        self._synka_dagar()
        self.manad_hjul._rita()
        self.on_change()

    def _manad_text(self, index: int) -> str | None:
        ar, manad0 = divmod(self.ar * 12 + index, 12)
        if ar not in self.ar_varden:
            return None
        return MANADER[manad0].capitalize()

    def _dag_text(self, index: int) -> str | None:
        nytt = date(self.ar, self.manad, 1) + timedelta(days=index)
        if nytt.year not in self.ar_varden:
            return None
        return str(nytt.day)

    def _flytta_till(self, nytt: date) -> None:
        if nytt.year not in self.ar_varden:
            return
        self.ar = nytt.year
        self.manad = nytt.month
        self.dag = nytt.day
        self.ar_hjul.satt_index(self.ar_varden.index(self.ar), animera=False, tyst=True)
        self.manad_hjul.satt_index(self.manad - 1, animera=False, tyst=True)
        self._synka_dagar()
        self.on_change()

    def _rulla_dag(self, diff: int) -> bool:
        self._flytta_till(date(self.ar, self.manad, self.dag) + timedelta(days=diff))
        return True

    def _rulla_manad(self, diff: int) -> bool:
        total = self.ar * 12 + (self.manad - 1) + diff
        ar, manad = divmod(total, 12)
        manad += 1
        if ar not in self.ar_varden:
            return True
        dag = min(self.dag, calendar.monthrange(ar, manad)[1])
        self._flytta_till(date(ar, manad, dag))
        return True

    def _nudge(self, steg: int) -> None:
        try:
            nytt = date(self.ar, self.manad, self.dag) + timedelta(days=steg)
        except ValueError:
            return
        if nytt.year not in self.ar_varden:
            return
        self.ar = nytt.year
        self.manad = nytt.month
        self.dag = nytt.day
        self.ar_hjul.satt_index(self.ar_varden.index(self.ar), tyst=True)
        self.manad_hjul.satt_index(self.manad - 1, tyst=True)
        self._synka_dagar()
        self.on_change()


class NyttKontoDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.title("Nytt konto")
        self.configure(bg=TEMA["bg"])
        self.resizable(False, False)
        self.grab_set()
        kort = tk.Frame(self, bg=TEMA["kort"], padx=22, pady=18)
        kort.pack(padx=14, pady=14)
        tk.Label(kort, text="Nytt konto", font=("Segoe UI", 16, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)
        tk.Label(
            kort, text="Döp kontot och fyll i saldo, ränta och skatt.",
            font=("Segoe UI", 10), bg=TEMA["kort"], fg=TEMA["muted"],
        ).pack(anchor=tk.W, pady=(2, 12))

        self.namn = tk.StringVar()
        self.sparat = tk.StringVar(value="0")
        self.ranta = tk.StringVar(value="2.4")
        self.skatt = tk.StringVar(value="30")
        for etikett, var in (
            ("Namn", self.namn),
            ("Saldo nu (kr)", self.sparat),
            ("Ränta (%/år)", self.ranta),
            ("Skatt på ränta (%)", self.skatt),
        ):
            tk.Label(kort, text=etikett, bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
            tk.Entry(kort, textvariable=var, font=("Segoe UI", 11), width=28).pack(anchor=tk.W, pady=(2, 8))

        knappar = tk.Frame(kort, bg=TEMA["kort"])
        knappar.pack(fill=tk.X, pady=(8, 0))
        knapp(knappar, "Avbryt", self._avbryt, bg="#8A9AA0", pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        knapp(knappar, "Lägg till", self._ok, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._avbryt())
        self.update_idletasks()
        centrera(self, self.winfo_reqwidth() + 8, self.winfo_reqheight() + 8)
        self.lift()
        self.focus_force()

    def _ok(self) -> None:
        namn = self.namn.get().strip()
        if not namn:
            messagebox.showerror("Fel", "Kontot måste ha ett namn.", parent=self)
            return
        try:
            heltal_varde(self.sparat.get())
            decimal_varde(self.ranta.get(), 2.4)
            decimal_varde(self.skatt.get(), 30)
        except ValueError:
            messagebox.showerror("Fel", "Saldo, ränta och skatt måste vara tal.", parent=self)
            return
        self.result = {
            "namn": namn,
            "sparat": self.sparat.get().strip() or "0",
            "ranta": self.ranta.get().strip() or "2.4",
            "skatt": self.skatt.get().strip() or "30",
        }
        self.grab_release()
        self.destroy()

    def _avbryt(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


class RanteAndringDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        standard_ar: int,
        standard_manad: int,
        standard_ranta: str,
        standard_skatt: str,
    ) -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.title("Ränteändring")
        self.configure(bg=TEMA["bg"])
        self.resizable(False, False)
        self.grab_set()
        kort = tk.Frame(self, bg=TEMA["kort"], padx=22, pady=18)
        kort.pack(padx=14, pady=14)
        tk.Label(kort, text="Ny ränta från månad", font=("Segoe UI", 15, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)

        self.ar = tk.StringVar(value=str(standard_ar))
        self.manad = tk.StringVar(value=MANADER[standard_manad - 1])
        self.ranta = tk.StringVar(value=str(standard_ranta or "2.4"))
        self.skatt = tk.StringVar(value=str(standard_skatt or "30"))
        rad = tk.Frame(kort, bg=TEMA["kort"])
        rad.pack(anchor=tk.W, pady=10)
        ttk.Combobox(rad, textvariable=self.ar, values=[str(a) for a in ar_lista()], width=8, state="readonly").pack(side=tk.LEFT)
        ttk.Combobox(rad, textvariable=self.manad, values=MANADER, width=6, state="readonly").pack(side=tk.LEFT, padx=6)
        tk.Entry(rad, textvariable=self.ranta, width=8, font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(8, 2))
        tk.Label(rad, text="% ränta", bg=TEMA["kort"], fg=TEMA["muted"]).pack(side=tk.LEFT)
        tk.Entry(rad, textvariable=self.skatt, width=6, font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(10, 2))
        tk.Label(rad, text="% skatt", bg=TEMA["kort"], fg=TEMA["muted"]).pack(side=tk.LEFT)

        knappar = tk.Frame(kort, bg=TEMA["kort"])
        knappar.pack(fill=tk.X, pady=(8, 0))
        knapp(knappar, "Avbryt", self._avbryt, bg="#8A9AA0", pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        knapp(knappar, "Spara", self._ok, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._avbryt())
        self.update_idletasks()
        centrera(self, self.winfo_reqwidth() + 8, self.winfo_reqheight() + 8)

    def _ok(self) -> None:
        try:
            ranta = decimal_varde(self.ranta.get(), -1)
            skatt = decimal_varde(self.skatt.get(), -1)
        except ValueError:
            messagebox.showerror("Fel", "Ange giltig ränta och skatt.", parent=self)
            return
        if ranta < 0 or skatt < 0:
            messagebox.showerror("Fel", "Ange giltig ränta och skatt.", parent=self)
            return
        self.result = {
            "ar": str(int(self.ar.get())),
            "manad": self.manad.get(),
            "ranta": self.ranta.get().strip().replace(",", "."),
            "skatt": self.skatt.get().strip().replace(",", "."),
        }
        self.grab_release()
        self.destroy()

    def _avbryt(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


def _koppla_dag(ar_var: tk.StringVar, manad_var: tk.StringVar, dag_var: tk.StringVar, dag_box: ttk.Combobox) -> None:
    def justera(*_args: object) -> None:
        try:
            ar = int(ar_var.get())
        except ValueError:
            return
        manad = MANAD_NAMN_TILL_NUMMER.get(manad_var.get(), 1)
        maxdag = calendar.monthrange(ar, manad)[1]
        dag_box.configure(values=[str(d) for d in range(1, maxdag + 1)])
        try:
            dag = int(dag_var.get())
        except ValueError:
            dag = 1
        dag_var.set(str(min(max(dag, 1), maxdag)))

    ar_var.trace_add("write", justera)
    manad_var.trace_add("write", justera)
    justera()


class RorelseDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        titel: str,
        typ: str,
        standard_ar: int,
        standard_manad: int,
        standard_dag: int = 1,
        befintlig: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.typ = typ
        self.title(titel)
        self.configure(bg=TEMA["bg"])
        self.resizable(False, False)
        self.grab_set()
        kort = tk.Frame(self, bg=TEMA["kort"], padx=22, pady=18)
        kort.pack(padx=14, pady=14)
        tk.Label(kort, text=titel, font=("Segoe UI", 15, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)

        self.ar = tk.StringVar(value=str(standard_ar))
        self.manad = tk.StringVar(value=MANADER[standard_manad - 1])
        self.dag = tk.StringVar(value=str(standard_dag))
        self.belopp = tk.StringVar(value=str((befintlig or {}).get("belopp", "")))
        self.anteckning = tk.StringVar(value=str((befintlig or {}).get("anteckning", "")))
        rad = tk.Frame(kort, bg=TEMA["kort"])
        rad.pack(anchor=tk.W, pady=10)
        dag_box = ttk.Combobox(rad, textvariable=self.dag, width=4, state="readonly")
        dag_box.pack(side=tk.LEFT)
        ttk.Combobox(rad, textvariable=self.manad, values=MANADER, width=6, state="readonly").pack(side=tk.LEFT, padx=6)
        ttk.Combobox(rad, textvariable=self.ar, values=[str(a) for a in ar_lista()], width=8, state="readonly").pack(side=tk.LEFT)
        tk.Entry(rad, textvariable=self.belopp, width=12, font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(8, 4))
        tk.Label(rad, text="kr", bg=TEMA["kort"], fg=TEMA["muted"]).pack(side=tk.LEFT)
        _koppla_dag(self.ar, self.manad, self.dag, dag_box)
        tk.Label(
            kort, text="Påminnelse en vecka innan och dagen innan.",
            bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 6))

        tk.Label(kort, text="Anteckning (valfritt)", bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 8, "bold")).pack(anchor=tk.W)
        tk.Entry(kort, textvariable=self.anteckning, width=40, font=("Segoe UI", 11)).pack(anchor=tk.W, pady=(2, 0), fill=tk.X)

        knappar = tk.Frame(kort, bg=TEMA["kort"])
        knappar.pack(fill=tk.X, pady=(12, 0))
        knapp(knappar, "Avbryt", self._avbryt, bg="#8A9AA0", pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        knapp(knappar, "Spara", self._ok, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._avbryt())
        self.update_idletasks()
        centrera(self, max(self.winfo_reqwidth() + 8, 420), self.winfo_reqheight() + 8)

    def _ok(self) -> None:
        try:
            belopp = heltal_varde(self.belopp.get())
        except ValueError:
            messagebox.showerror("Fel", "Ange belopp i kronor.", parent=self)
            return
        if belopp <= 0:
            messagebox.showerror("Fel", "Beloppet måste vara större än 0.", parent=self)
            return
        manad = MANAD_NAMN_TILL_NUMMER[self.manad.get()]
        ar = int(self.ar.get())
        self.result = {
            "typ": self.typ,
            "ar": ar,
            "manad": manad,
            "dag": _tolka_dag({"dag": self.dag.get(), "ar": ar}, ar, manad),
            "belopp": belopp,
            "anteckning": self.anteckning.get().strip(),
        }
        self.grab_release()
        self.destroy()

    def _avbryt(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


class OverforDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        konton: list[dict],
        fran_idx: int,
        standard_ar: int,
        standard_manad: int,
        standard_dag: int = 1,
        befintlig: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.konton = konton
        self.title("Ändra överföring" if befintlig else "Överför")
        self.configure(bg=TEMA["bg"])
        self.resizable(False, False)
        self.grab_set()
        kort = tk.Frame(self, bg=TEMA["kort"], padx=22, pady=18)
        kort.pack(padx=14, pady=14)
        tk.Label(kort, text="Överför mellan konton", font=("Segoe UI", 15, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)
        tk.Label(
            kort, text="Görs det datum du väljer. Påminnelse en vecka innan och dagen innan.",
            font=("Segoe UI", 10), bg=TEMA["kort"], fg=TEMA["muted"],
        ).pack(anchor=tk.W, pady=(2, 12))

        aktiva = [(i, k) for i, k in enumerate(konton) if konto_ar_aktivt(k)]
        namn = [konto_visningsnamn(konton, i + 1) for i, _k in aktiva]
        self._index_map = [i for i, _k in aktiva]
        self.fran = tk.StringVar(value=konto_visningsnamn(konton, fran_idx + 1))
        andra = [n for n in namn if n != self.fran.get()]
        self.till = tk.StringVar(value=andra[0] if andra else "")
        if befintlig:
            try:
                till_nr = int(heltal_varde(str(befintlig.get("till_konto", "0"))))
            except ValueError:
                till_nr = 0
            if 1 <= till_nr <= len(konton):
                self.till.set(konto_visningsnamn(konton, till_nr))
        self.ar = tk.StringVar(value=str(standard_ar))
        self.manad = tk.StringVar(value=MANADER[standard_manad - 1])
        self.dag = tk.StringVar(value=str(standard_dag))
        self.belopp = tk.StringVar(value=str((befintlig or {}).get("belopp", "")))
        self.anteckning = tk.StringVar(value=str((befintlig or {}).get("anteckning", "")))

        for etikett, var, varden, bredd in (
            ("Från", self.fran, namn, 22),
            ("Till", self.till, andra or namn, 22),
        ):
            tk.Label(kort, text=etikett, bg=TEMA["kort"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
            ttk.Combobox(kort, textvariable=var, values=varden, width=bredd, state="readonly").pack(anchor=tk.W, pady=(2, 8))

        rad = tk.Frame(kort, bg=TEMA["kort"])
        rad.pack(anchor=tk.W, pady=(0, 8))
        dag_box = ttk.Combobox(rad, textvariable=self.dag, width=4, state="readonly")
        dag_box.pack(side=tk.LEFT)
        ttk.Combobox(rad, textvariable=self.manad, values=MANADER, width=6, state="readonly").pack(side=tk.LEFT, padx=6)
        ttk.Combobox(rad, textvariable=self.ar, values=[str(a) for a in ar_lista()], width=8, state="readonly").pack(side=tk.LEFT)
        tk.Entry(rad, textvariable=self.belopp, width=12, font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(8, 4))
        tk.Label(rad, text="kr", bg=TEMA["kort"], fg=TEMA["muted"]).pack(side=tk.LEFT)
        _koppla_dag(self.ar, self.manad, self.dag, dag_box)

        tk.Label(kort, text="Anteckning (valfritt)", bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 8, "bold")).pack(anchor=tk.W)
        tk.Entry(kort, textvariable=self.anteckning, width=40, font=("Segoe UI", 11)).pack(anchor=tk.W, pady=(2, 8), fill=tk.X)

        knappar = tk.Frame(kort, bg=TEMA["kort"])
        knappar.pack(fill=tk.X, pady=(8, 0))
        knapp(knappar, "Avbryt", self._avbryt, bg="#8A9AA0", pady=6).pack(side=tk.RIGHT, padx=(8, 0))
        knapp(knappar, "Spara" if befintlig else "Överför", self._ok, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._avbryt())
        self.update_idletasks()
        centrera(self, max(self.winfo_reqwidth() + 8, 420), self.winfo_reqheight() + 8)

    def _ok(self) -> None:
        try:
            belopp = heltal_varde(self.belopp.get())
        except ValueError:
            messagebox.showerror("Fel", "Ange belopp i kronor.", parent=self)
            return
        if belopp <= 0:
            messagebox.showerror("Fel", "Beloppet måste vara större än 0.", parent=self)
            return
        namn = [konto_visningsnamn(self.konton, i + 1) for i in self._index_map]
        try:
            fran = self._index_map[namn.index(self.fran.get())] + 1
            till = self._index_map[namn.index(self.till.get())] + 1
        except ValueError:
            messagebox.showerror("Fel", "Välj två konton.", parent=self)
            return
        if fran == till:
            messagebox.showerror("Fel", "Välj två olika konton.", parent=self)
            return
        manad_nr = MANAD_NAMN_TILL_NUMMER[self.manad.get()]
        ar = int(self.ar.get())
        self.result = {
            "ar": str(ar),
            "manad": self.manad.get(),
            "dag": _tolka_dag({"dag": self.dag.get(), "ar": ar}, ar, manad_nr),
            "fran_konto": str(fran),
            "till_konto": str(till),
            "belopp": str(belopp),
            "anteckning": self.anteckning.get().strip(),
        }
        self.grab_release()
        self.destroy()

    def _avbryt(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


def redigera_post(parent: tk.Misc, konton: list[dict], slag: str, post: dict) -> bool:
    """Öppna dialogen ifylld och skriv ändringen direkt i posten. True om sparad."""
    try:
        ar = int(heltal_varde(str(post.get("ar"))))
    except (TypeError, ValueError):
        ar = date.today().year
    manad = _tolka_rorelse_manad(post)
    dag = _tolka_dag(post, ar, manad)
    if slag == "rorelse":
        typ = str(post.get("typ") or "uttag")
        titel = "Ändra insättning" if typ == "insattning" else "Ändra uttag"
        dialog = RorelseDialog(parent, titel, typ, ar, manad, dag, befintlig=post)
        parent.wait_window(dialog)
        if not dialog.result:
            return False
        konto = post.get("konto")
        kalla = post.get("kalla")
        kopplad = post.get("kontanter_kopplad")
        post.clear()
        post.update(dialog.result)
        post["konto"] = konto
        if kalla:
            post["kalla"] = kalla
        if kopplad:
            post["kontanter_kopplad"] = True
        return True
    try:
        fran = int(heltal_varde(str(post.get("fran_konto", "1"))))
    except ValueError:
        fran = 1
    dialog = OverforDialog(parent, konton, max(fran - 1, 0), ar, manad, dag, befintlig=post)
    parent.wait_window(dialog)
    if not dialog.result:
        return False
    kopplad = post.get("kontanter_kopplad")
    post.clear()
    post.update(dialog.result)
    if kopplad:
        post["kontanter_kopplad"] = True
    return True


class KontoFonster(tk.Toplevel):
    def __init__(self, parent: "PensionsplanApp", valt: int | None = None) -> None:
        super().__init__(parent)
        self.app = parent
        self.title("Konton")
        self.configure(bg=TEMA["bg"])
        self._valt = valt if valt is not None else 0
        self._bygg()
        self.protocol("WM_DELETE_WINDOW", self._tillbaka)
        if parent._ar_borskonto(self._valt):
            centrera(self, *self._bors_storlek())
            self.minsize(1200, 720)
        else:
            centrera(self, 1080, 720)
        self.lift()
        self.focus_force()

    def _bygg(self) -> None:
        topp = tk.Frame(self, bg=TEMA["sida"], padx=18, pady=12)
        topp.pack(fill=tk.X)
        tk.Label(topp, text="Konton", font=("Segoe UI", 18, "bold"), bg=TEMA["sida"], fg=TEMA["vit"]).pack(side=tk.LEFT)
        self.overskott_lbl = tk.Label(
            topp, text=self.app.overskott_text(),
            font=("Segoe UI", 10), bg=TEMA["sida"], fg="#A9C5C8",
        )
        self.overskott_lbl.pack(side=tk.LEFT, padx=16)
        knapp(topp, "←  Översikt", self._tillbaka, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT)

        kropp = tk.Frame(self, bg=TEMA["bg"], padx=16, pady=14)
        kropp.pack(fill=tk.BOTH, expand=True)
        kropp.columnconfigure(1, weight=1)
        kropp.rowconfigure(0, weight=1)

        vanster = tk.Frame(kropp, bg=TEMA["bg"], width=240)
        vanster.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        vanster.grid_propagate(False)
        vanster.columnconfigure(0, weight=1)
        vanster.rowconfigure(1, weight=1)
        knapp(vanster, "+  Lägg till konto", self._nytt, bg=TEMA["accent"], pady=7).grid(
            row=0, column=0, sticky="ew", pady=(0, 10),
        )
        lista_scroll = tk.Frame(vanster, bg=TEMA["bg"])
        lista_scroll.grid(row=1, column=0, sticky="nsew")
        self.lista_canvas = tk.Canvas(lista_scroll, bg=TEMA["bg"], highlightthickness=0, bd=0, width=220)
        lista_sb = ttk.Scrollbar(lista_scroll, orient=tk.VERTICAL, command=self.lista_canvas.yview)
        self.lista = tk.Frame(self.lista_canvas, bg=TEMA["bg"])
        self._lista_win = self.lista_canvas.create_window((0, 0), window=self.lista, anchor=tk.NW)

        def _pa_lista_inner(_e: tk.Event | None = None) -> None:
            self.lista_canvas.configure(scrollregion=self.lista_canvas.bbox("all"))

        def _pa_lista_canvas(e: tk.Event) -> None:
            self.lista_canvas.itemconfigure(self._lista_win, width=e.width)

        def _lista_hjul(e: tk.Event) -> str:
            self.lista_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        self.lista.bind("<Configure>", _pa_lista_inner)
        self.lista_canvas.bind("<Configure>", _pa_lista_canvas)
        self.lista_canvas.bind("<MouseWheel>", _lista_hjul)
        self.lista.bind("<MouseWheel>", _lista_hjul)
        self.lista_canvas.configure(yscrollcommand=lista_sb.set)
        self.lista_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lista_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._drag_idx: int | None = None
        self._lista_rader: list[tuple[int, tk.Frame]] = []

        self.detail = tk.Frame(kropp, bg=TEMA["kort"], padx=18, pady=16)
        self.detail.grid(row=0, column=1, sticky="nsew")
        self._rita_lista()
        self._rita_detail()

    def _aktiva_index(self) -> list[int]:
        return [i for i, k in enumerate(self.app.konton) if konto_ar_aktivt(k)]

    def _rita_lista(self) -> None:
        for w in self.lista.winfo_children():
            w.destroy()
        self._lista_rader = []
        index = self._aktiva_index()
        if not index:
            tk.Label(
                self.lista, text="Inga konton än.\nLägg till och döpa det första.",
                bg=TEMA["bg"], fg=TEMA["muted"], font=("Segoe UI", 10), justify=tk.LEFT,
            ).pack(anchor=tk.W)
            return
        if self._valt not in index:
            self._valt = index[0]
        saldon = self.app.saldo_per_konto()

        def _hjul(e: tk.Event) -> str:
            self.lista_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        for i in index:
            aktiv = i == self._valt
            bg = TEMA["sida"] if aktiv else TEMA["kort"]
            fg = TEMA["vit"] if aktiv else TEMA["text"]
            kan_dra = i != 0
            ram = tk.Frame(
                self.lista, bg=bg, padx=12, pady=10,
                cursor="fleur" if kan_dra else "hand2",
            )
            ram.pack(fill=tk.X, pady=4)
            titel = konto_visningsnamn(self.app.konton, i + 1)
            if kan_dra:
                titel = f"⠿  {titel}"
            tk.Label(ram, text=titel, bg=bg, fg=fg, font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
            tk.Label(
                ram, text=formatera_kr(saldon[i]),
                bg=bg, fg="#A9C5C8" if aktiv else TEMA["muted"], font=("Segoe UI", 10),
            ).pack(anchor=tk.W)
            ram.bind("<Button-1>", lambda e, nr=i: self._lista_tryck(e, nr))
            ram.bind("<B1-Motion>", self._lista_dra)
            ram.bind("<ButtonRelease-1>", self._lista_slapp)
            for barn in ram.winfo_children():
                barn.bind("<Button-1>", lambda e, nr=i: self._lista_tryck(e, nr))
                barn.bind("<B1-Motion>", self._lista_dra)
                barn.bind("<ButtonRelease-1>", self._lista_slapp)
                barn.bind("<MouseWheel>", _hjul)
            ram.bind("<MouseWheel>", _hjul)
            self._lista_rader.append((i, ram))
        self.lista_canvas.configure(scrollregion=self.lista_canvas.bbox("all"))

    def _lista_tryck(self, event: tk.Event, nr: int) -> None:
        self._valj(nr)
        self._drag_idx = nr if nr != 0 else None
        self._drag_start_y = event.y_root

    def _lista_dra(self, event: tk.Event) -> None:
        if self._drag_idx is None:
            return
        # Visuell feedback via scroll om man drar nära kanten
        try:
            y_lokal = event.y_root - self.lista_canvas.winfo_rooty()
            h = self.lista_canvas.winfo_height()
            if y_lokal < 24:
                self.lista_canvas.yview_scroll(-1, "units")
            elif y_lokal > h - 24:
                self.lista_canvas.yview_scroll(1, "units")
        except tk.TclError:
            pass

    def _lista_slapp(self, event: tk.Event) -> None:
        fran = self._drag_idx
        self._drag_idx = None
        if fran is None or fran == 0:
            return
        till = None
        for idx, ram in self._lista_rader:
            if idx == 0:
                continue
            try:
                y1 = ram.winfo_rooty()
                y2 = y1 + ram.winfo_height()
            except tk.TclError:
                continue
            if y1 <= event.y_root <= y2:
                till = idx
                break
        if till is None or till == fran:
            return
        self._ordna_konton(fran, till)

    def _ordna_konton(self, fran: int, till: int) -> None:
        """Flytta konto i listan (inte plånboken) och mappa om rörelser."""
        if fran == 0 or till == 0:
            return
        aktiva = self._aktiva_index()
        ovriga = [i for i in aktiva if i != 0]
        if fran not in ovriga or till not in ovriga:
            return
        a = ovriga.index(fran)
        b = ovriga.index(till)
        post = ovriga.pop(a)
        ovriga.insert(b, post)
        ny_ordning = [0] + ovriga
        inaktiva = [i for i in range(len(self.app.konton)) if i not in aktiva]
        full = ny_ordning + inaktiva
        gamla = self.app.konton
        nya = [tomt_konto() for _ in range(ANTAL_KONTON)]
        mapping: dict[int, int] = {}
        for new_i, old_i in enumerate(full):
            if new_i >= ANTAL_KONTON or old_i >= len(gamla):
                continue
            nya[new_i] = gamla[old_i]
            mapping[old_i + 1] = new_i + 1
        self.app.konton = nya
        for r in self.app.rorelser:
            try:
                k = int(r.get("konto", 0))
            except (TypeError, ValueError):
                continue
            if k in mapping:
                r["konto"] = mapping[k]
        for o in self.app.overforingar:
            for nyckel in ("fran_konto", "till_konto"):
                try:
                    k = int(heltal_varde(str(o.get(nyckel, "0"))))
                except (TypeError, ValueError):
                    continue
                if k in mapping:
                    o[nyckel] = str(mapping[k])
        self._valt = mapping.get(fran + 1, self._valt + 1) - 1
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()

    def _valj(self, nr: int) -> None:
        self._valt = nr
        self._rita_lista()
        self._rita_detail()

    def _rita_detail(self) -> None:
        for w in self.detail.winfo_children():
            w.destroy()
        if self.app._aktiekonto_index() == self._valt:
            self._rita_aktiepanel()
            return
        if self.app._aktier_index() == self._valt:
            self._rita_vardepanel()
            return
        self.detail.configure(padx=18, pady=16)
        index = self._aktiva_index()
        if not index:
            tk.Label(
                self.detail, text="Lägg till ett konto för att komma igång.",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 12),
            ).pack(anchor=tk.W)
            return
        k = self.app.konton[self._valt]
        tk.Label(
            self.detail, text=konto_visningsnamn(self.app.konton, self._valt + 1),
            bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 20, "bold"),
        ).pack(anchor=tk.W)
        if self._valt == 0:
            tk.Label(
                self.detail,
                text="Plånboken – fylls på automatiskt från konto 2 när månaden inte räcker. Du kan sätta in här eller på konto 2 när du vill.",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 10), wraplength=420, justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(4, 0))
        elif self._valt == 1:
            tk.Label(
                self.detail,
                text="Buffert – används automatiskt för att fylla på konto 1. Du kan sätta in här när du vill.",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 10), wraplength=420, justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(4, 0))

        saldo_nu = self.app.saldo_for_konto(self._valt + 1)
        datum_txt = formatera_datum(self.app.visnings_ar, self.app.visnings_manad, self.app.visnings_dag)
        tk.Label(
            self.detail,
            text=f"Saldo {datum_txt}:  {formatera_kr(saldo_nu)}",
            bg=TEMA["kort"], fg=TEMA["pengar"], font=("Segoe UI", 14, "bold"),
        ).pack(anchor=tk.W, pady=(10, 0))

        falt = tk.Frame(self.detail, bg=TEMA["kort"])
        falt.pack(fill=tk.X, pady=12)
        self.namn_var = tk.StringVar(value=k.get("namn", ""))
        self.sparat_var = tk.StringVar(value=k.get("sparat", "0"))
        self.ranta_var = tk.StringVar(value=k.get("ranta", "2.4"))
        self.skatt_var = tk.StringVar(value=k.get("skatt", "30"))
        for col, (etikett, var) in enumerate((
            ("Namn", self.namn_var),
            ("Startsaldo (kr)", self.sparat_var),
            ("Ränta %", self.ranta_var),
            ("Skatt %", self.skatt_var),
        )):
            tk.Label(falt, text=etikett, bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 8, "bold")).grid(row=0, column=col, sticky=tk.W, padx=(0, 12))
            e = tk.Entry(falt, textvariable=var, font=("Segoe UI", 11), width=14)
            e.grid(row=1, column=col, sticky=tk.W, padx=(0, 12), pady=(2, 0))
            var.trace_add("write", lambda *_: self._spara_falt())

        val = tk.Frame(self.detail, bg=TEMA["kort"])
        val.pack(fill=tk.X)
        self.manadsranta_var = tk.BooleanVar(value=bool(k.get("manadsranta")))
        tk.Checkbutton(
            val, text="Ränta varje månad (ränta på ränta). Annars kommer räntan i januari året efter.",
            variable=self.manadsranta_var, command=self._spara_val,
            bg=TEMA["kort"], activebackground=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9),
        ).pack(anchor=tk.W)
        if self._valt != 0:
            self.overskott_var = tk.BooleanVar(value=self.app._sparkonto_index() == self._valt)
            tk.Checkbutton(
                val, text="Framtida överskott och underskott räknas på det här kontot",
                variable=self.overskott_var, command=self._spara_val,
                bg=TEMA["kort"], activebackground=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9),
            ).pack(anchor=tk.W)

        knappar = tk.Frame(self.detail, bg=TEMA["kort"])
        knappar.pack(fill=tk.X, pady=(8, 14))
        knapp(knappar, "+ Insättning", lambda: self._rorelse("insattning"), bg=TEMA["accent"], pady=6).pack(side=tk.LEFT, padx=(0, 6))
        knapp(knappar, "− Uttag", lambda: self._rorelse("uttag"), bg=TEMA["sida"], pady=6).pack(side=tk.LEFT, padx=(0, 6))
        knapp(knappar, "Överför", self._overfor, bg="#3D6B7A", pady=6).pack(side=tk.LEFT, padx=(0, 6))
        angra = knapp(knappar, "Ångra borttagen", self.app.angra_borttagen, bg="#8A9AA0", pady=6)
        angra.pack(side=tk.LEFT, padx=(0, 6))
        if not self.app.borttagna_handelser:
            angra.configure(state=tk.DISABLED)
        if self._valt != 0:
            knapp(knappar, "Ta bort konto", self._ta_bort, bg=TEMA["fara"], pady=6).pack(side=tk.RIGHT)
        else:
            tk.Label(
                knappar, text="Plånboken kan inte tas bort",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9),
            ).pack(side=tk.RIGHT)

        self._rita_rante_andringar()

        tk.Label(
            self.detail, text="Insättningar och uttag",
            bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 11, "bold"),
        ).pack(anchor=tk.W, pady=(4, 0))

        scroll_yttre = tk.Frame(self.detail, bg=TEMA["kort"])
        scroll_yttre.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self._rorelse_canvas = tk.Canvas(
            scroll_yttre, bg=TEMA["kort"], highlightthickness=0, bd=0,
        )
        scrollbar = ttk.Scrollbar(scroll_yttre, orient=tk.VERTICAL, command=self._rorelse_canvas.yview)
        self.rorelse_lista = tk.Frame(self._rorelse_canvas, bg=TEMA["kort"])
        self._rorelse_fonster_id = self._rorelse_canvas.create_window((0, 0), window=self.rorelse_lista, anchor=tk.NW)

        def _pa_inner(_e: tk.Event | None = None) -> None:
            self._rorelse_canvas.configure(scrollregion=self._rorelse_canvas.bbox("all"))

        def _pa_canvas(e: tk.Event) -> None:
            self._rorelse_canvas.itemconfigure(self._rorelse_fonster_id, width=e.width)

        def _hjul(e: tk.Event) -> str:
            self._rorelse_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        self.rorelse_lista.bind("<Configure>", _pa_inner)
        self._rorelse_canvas.bind("<Configure>", _pa_canvas)
        self._rorelse_canvas.bind("<MouseWheel>", _hjul)
        self.rorelse_lista.bind("<MouseWheel>", _hjul)

        self._rorelse_canvas.configure(yscrollcommand=scrollbar.set)
        self._rorelse_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._rita_rorelser()

    def _bors_storlek(self) -> tuple[int, int]:
        try:
            extra = int(round(self.winfo_fpixels("2c")))
        except tk.TclError:
            extra = 76
        return 1360, 876 + extra

    def _bredda_borsfonster(self) -> None:
        self.minsize(1200, 720)
        bredd, hojd = self._bors_storlek()
        try:
            if self.winfo_width() < 1300 or self.winfo_height() < hojd - 8:
                centrera(self, bredd, hojd)
        except tk.TclError:
            pass

    def _rita_borsnamn(self, typtext: str) -> None:
        rad = tk.Frame(self.detail, bg=TEMA["kort"], padx=12, pady=6)
        rad.pack(fill=tk.X)
        tk.Label(rad, text="Kontots namn", bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        namn = tk.StringVar(value=self.app.konton[self._valt].get("namn", ""))
        tk.Entry(rad, textvariable=namn, font=("Segoe UI", 10), width=22).pack(side=tk.LEFT, padx=(8, 12))
        tk.Label(rad, text=typtext, bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT)

        def spara(*_a) -> None:
            nytt = namn.get().strip()
            if not nytt:
                return
            self.app.konton[self._valt]["namn"] = nytt
            self.app._schemalagd_sparning()
            self._rita_lista()

        namn.trace_add("write", spara)

    def _rita_aktiepanel(self) -> None:
        self.detail.configure(padx=0, pady=0)
        self._bredda_borsfonster()
        self._rita_borsnamn("Utdelningskonto – utdelningar, gratisaktier och avkastning på insatsen. Namnet kan du ändra fritt.")
        panel = UtdelningApp(self.detail)
        panel.pack(fill=tk.BOTH, expand=True)
        panel.koppla_insattning(self._insattning_pa_bors)
        panel.visa_insatt(self.app.insatt_till_aktiekonto())
        panel.visa_kontanter(self.app.kontantkassa(), self.app.satt_kontantkassa)

    def _rita_vardepanel(self) -> None:
        self.detail.configure(padx=0, pady=0)
        self._bredda_borsfonster()
        self._rita_borsnamn("Kursvinstkonto – visar plus och minus mot det du betalat. Namnet kan du ändra fritt.")
        panel = AktieHandelApp(self.detail, self.app._las_vardeaktier, self.app._skriv_vardeaktier)
        panel.pack(fill=tk.BOTH, expand=True)
        panel.koppla_insattning(self._insattning_pa_bors)
        panel.visa_insatt(self.app.insatt_till_konto(self.app._aktier_index()))
        panel.visa_kontanter(self.app.aktier_kontantkassa(), self.app.satt_aktier_kontanter)

    def _rita_rante_andringar(self) -> None:
        ram = tk.Frame(self.detail, bg=TEMA["kort"])
        ram.pack(fill=tk.X, pady=(0, 12))
        topp = tk.Frame(ram, bg=TEMA["kort"])
        topp.pack(fill=tk.X)
        tk.Label(
            topp, text="Ränteändringar", bg=TEMA["kort"], fg=TEMA["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)
        knapp(topp, "+ Lägg till", self._lagg_rante_andring, bg=TEMA["accent"], pady=4).pack(side=tk.RIGHT)

        lista = tk.Frame(ram, bg=TEMA["kort"])
        lista.pack(fill=tk.X, pady=(6, 0))
        andringar = list(self.app.konton[self._valt].get("rante_andringar") or [])
        if not andringar:
            tk.Label(
                lista, text="Ingen framtida ränteändring – basräntan ovan gäller.",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9),
            ).pack(anchor=tk.W)
            return
        for idx, a in enumerate(andringar):
            try:
                manad_nr = _tolka_rorelse_manad(a)
                text = (
                    f"{MANADER[manad_nr - 1]} {a.get('ar')}:  "
                    f"{a.get('ranta', '')} %  (skatt {a.get('skatt', '')} %)"
                )
            except (TypeError, ValueError, IndexError):
                text = str(a)
            rad = tk.Frame(lista, bg=TEMA["kort"])
            rad.pack(fill=tk.X, pady=2)
            tk.Label(rad, text=text, bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 10)).pack(side=tk.LEFT)
            tk.Button(
                rad, text="ta bort", command=lambda i=idx: self._ta_bort_rante_andring(i),
                bg=TEMA["kort"], fg=TEMA["fara"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
            ).pack(side=tk.RIGHT)

    def _lagg_rante_andring(self) -> None:
        dialog = RanteAndringDialog(
            self, self.app.visnings_ar, self.app.visnings_manad,
            self.ranta_var.get(), self.skatt_var.get(),
        )
        self.wait_window(dialog)
        if not dialog.result:
            return
        k = self.app.konton[self._valt]
        andringar = list(k.get("rante_andringar") or [])
        andringar.append(dialog.result)
        andringar.sort(key=lambda a: (_manad_nyckel(int(a["ar"]), _tolka_rorelse_manad(a))))
        k["rante_andringar"] = andringar
        self.app._schemalagd_sparning()
        self._rita_detail()
        self.app._uppdatera_oversikt()

    def _ta_bort_rante_andring(self, idx: int) -> None:
        k = self.app.konton[self._valt]
        andringar = list(k.get("rante_andringar") or [])
        if 0 <= idx < len(andringar):
            del andringar[idx]
            k["rante_andringar"] = andringar
            self.app._schemalagd_sparning()
            self._rita_detail()
            self.app._uppdatera_oversikt()

    def _rita_rorelser(self) -> None:
        for w in self.rorelse_lista.winfo_children():
            w.destroy()
        poster = [
            r for r in self.app.rorelser
            if int(r.get("konto", 0)) == self._valt + 1 and str(r.get("kalla") or "") != "overskott"
        ]
        poster.sort(key=_rorelse_sortering)
        over = [
            o for o in self.app.overforingar
            if str(o.get("fran_konto")) == str(self._valt + 1) or str(o.get("till_konto")) == str(self._valt + 1)
        ]
        over.sort(key=_rorelse_sortering)

        def _hjul(e: tk.Event) -> str:
            self._rorelse_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        def _bind_hjul(widget: tk.Misc) -> None:
            widget.bind("<MouseWheel>", _hjul)
            for barn in widget.winfo_children():
                _bind_hjul(barn)

        overskott = [
            rad for rad in self.app.synliga_overskott()
            if self.app._overskott_visas_pa(rad, self._valt)
        ]
        if overskott:
            tk.Label(
                self.rorelse_lista, text="Kvar efter lön och räkningar",
                bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 11, "bold"),
            ).pack(anchor=tk.W, pady=(0, 4))
            for rad_overskott in overskott:
                text = (
                    f"{formatera_datum(rad_overskott['ar'], rad_overskott['manad'], rad_overskott['dag'])}:  "
                    f"+{formatera_kr(rad_overskott['belopp'])}"
                )
                if rad_overskott["anteckning"]:
                    text = f"{text}  –  {rad_overskott['anteckning']}"
                rad = tk.Frame(self.rorelse_lista, bg=TEMA["kort"])
                rad.pack(fill=tk.X, pady=2)
                etikett = tk.Label(
                    rad, text=text, bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 10),
                    anchor=tk.W, cursor="hand2",
                )
                etikett.pack(side=tk.LEFT, fill=tk.X, expand=True)
                ar_o, manad_o = rad_overskott["ar"], rad_overskott["manad"]
                etikett.bind("<Button-1>", lambda _e, a=ar_o, m=manad_o: self.app.redigera_overskott(self, a, m))
                tk.Button(
                    rad, text="ta bort", command=lambda a=ar_o, m=manad_o: self.app.nolla_overskott(a, m),
                    bg=TEMA["kort"], fg=TEMA["fara"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
                ).pack(side=tk.RIGHT)
                tk.Button(
                    rad, text="ändra", command=lambda a=ar_o, m=manad_o: self.app.redigera_overskott(self, a, m),
                    bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
                ).pack(side=tk.RIGHT)

        if not poster and not over and not overskott:
            tk.Label(
                self.rorelse_lista, text="Inga insättningar eller uttag ännu.",
                bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 10),
            ).pack(anchor=tk.W)
            _bind_hjul(self.rorelse_lista)
            return

        for r in poster:
            tecken = "+" if r.get("typ") == "insattning" else "−"
            manad_nr = _tolka_rorelse_manad(r)
            dag = _tolka_dag(r, int(r["ar"]), manad_nr)
            anteckning = str(r.get("anteckning", "")).strip()
            text = f"{formatera_datum(int(r['ar']), manad_nr, dag)}:  {tecken}{formatera_kr(int(r['belopp']))}"
            if anteckning:
                text = f"{text}  –  {anteckning}"
            rad = tk.Frame(self.rorelse_lista, bg=TEMA["kort"])
            rad.pack(fill=tk.X, pady=2)
            etikett = tk.Label(
                rad, text=text, bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 10),
                anchor=tk.W, cursor="hand2",
            )
            etikett.pack(side=tk.LEFT, fill=tk.X, expand=True)
            etikett.bind("<Button-1>", lambda _e, post=r: self._andra_post("rorelse", post))
            tk.Button(
                rad, text="ta bort", command=lambda post=r: self._ta_bort_rorelse(post),
                bg=TEMA["kort"], fg=TEMA["fara"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
            ).pack(side=tk.RIGHT)
            tk.Button(
                rad, text="ändra", command=lambda post=r: self._andra_post("rorelse", post),
                bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
            ).pack(side=tk.RIGHT)

        if over:
            tk.Label(
                self.rorelse_lista, text="Manuella överföringar",
                bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 11, "bold"),
            ).pack(anchor=tk.W, pady=(12, 4))
            for o in over:
                try:
                    manad_nr = _tolka_rorelse_manad(o)
                    ar = int(heltal_varde(str(o.get("ar"))))
                    dag = _tolka_dag(o, ar, manad_nr)
                    nar_txt = formatera_datum(ar, manad_nr, dag)
                except (TypeError, ValueError, IndexError):
                    nar_txt = str(o.get("manad", ""))
                anteckning = str(o.get("anteckning", "")).strip()
                text = (
                    f"{nar_txt}: {formatera_kr(heltal_varde(str(o.get('belopp', '0'))))}  "
                    f"konto {o.get('fran_konto')} → {o.get('till_konto')}"
                )
                if anteckning:
                    text = f"{text}  –  {anteckning}"
                rad = tk.Frame(self.rorelse_lista, bg=TEMA["kort"])
                rad.pack(fill=tk.X, pady=2)
                etikett = tk.Label(
                    rad, text=text, bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 10),
                    anchor=tk.W, cursor="hand2",
                )
                etikett.pack(side=tk.LEFT, fill=tk.X, expand=True)
                etikett.bind("<Button-1>", lambda _e, post=o: self._andra_post("overforing", post))
                tk.Button(
                    rad, text="ta bort", command=lambda post=o: self._ta_bort_overforing(post),
                    bg=TEMA["kort"], fg=TEMA["fara"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
                ).pack(side=tk.RIGHT)
                tk.Button(
                    rad, text="ändra", command=lambda post=o: self._andra_post("overforing", post),
                    bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
                ).pack(side=tk.RIGHT)

        _bind_hjul(self.rorelse_lista)
        self._rorelse_canvas.configure(scrollregion=self._rorelse_canvas.bbox("all"))

    def _sortera_rorelser(self) -> None:
        self.app.rorelser.sort(key=_rorelse_sortering)
        self.app.overforingar.sort(key=_rorelse_sortering)

    def _spara_falt(self) -> None:
        k = self.app.konton[self._valt]
        k["namn"] = self.namn_var.get().strip()
        k["sparat"] = self.sparat_var.get().strip() or "0"
        k["ranta"] = self.ranta_var.get().strip() or "2.4"
        k["skatt"] = self.skatt_var.get().strip() or "30"
        k["aktiv"] = True
        self.overskott_lbl.configure(text=self.app.overskott_text())
        self.app._schemalagd_sparning()
        self._rita_lista()

    def _spara_val(self) -> None:
        k = self.app.konton[self._valt]
        k["manadsranta"] = bool(self.manadsranta_var.get())
        if self._valt != 0:
            pa = bool(self.overskott_var.get())
            if pa:
                for annat in self.app.konton:
                    annat["overskott"] = False
            k["overskott"] = pa
        self.overskott_lbl.configure(text=self.app.overskott_text())
        self.app._schemalagd_sparning()
        self._rita_lista()
        self.app._uppdatera_oversikt()

    def _nytt(self) -> None:
        ledig = next((i for i, k in enumerate(self.app.konton) if not konto_ar_aktivt(k)), None)
        if ledig is None:
            messagebox.showinfo("Fullt", f"Max {ANTAL_KONTON} konton.", parent=self)
            return
        dialog = NyttKontoDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        k = self.app.konton[ledig]
        k.update(dialog.result)
        k["aktiv"] = True
        k["rante_andringar"] = []
        self._valt = ledig
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()

    def _rorelse(self, typ: str) -> None:
        titel = "Insättning" if typ == "insattning" else "Uttag"
        ar, manad, dag = self.app.visnings_ar, self.app.visnings_manad, self.app.visnings_dag
        dialog = RorelseDialog(self, titel, typ, ar, manad, dag)
        self.wait_window(dialog)
        if not dialog.result:
            return
        post = dialog.result
        post["konto"] = self._valt + 1
        self.app.rorelser.append(post)
        self._sortera_rorelser()
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()

    def _insattning_pa_bors(self) -> None:
        """Pengar utifrån, in i kontantkassan. Dras inte från något annat konto."""
        ar, manad, dag = self.app.visnings_ar, self.app.visnings_manad, self.app.visnings_dag
        dialog = RorelseDialog(self, "Insättning", "insattning", ar, manad, dag)
        self.wait_window(dialog)
        if not dialog.result:
            return
        post = dialog.result
        post["konto"] = self._valt + 1
        post["kontanter_kopplad"] = True
        self.app.rorelser.append(post)
        self.app._andra_kontanter_fran_insattning(None, post)
        self._sortera_rorelser()
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()
        self.app._uppdatera_handelser()

    def _overfor(self) -> None:
        if len(self._aktiva_index()) < 2:
            messagebox.showinfo("Fler konton", "Lägg till minst två konton för att överföra.", parent=self)
            return
        dialog = OverforDialog(
            self, self.app.konton, self._valt,
            self.app.visnings_ar, self.app.visnings_manad, self.app.visnings_dag,
        )
        self.wait_window(dialog)
        if not dialog.result:
            return
        post = dialog.result
        post["kontanter_kopplad"] = True
        self.app.overforingar.append(post)
        self.app._andra_kontanter_fran_overforing(None, post)
        self._sortera_rorelser()
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()

    def _andra_post(self, slag: str, post: dict) -> None:
        gammal = dict(post) if slag == "overforing" and post.get("kontanter_kopplad") else None
        gammal_ins = dict(post) if slag == "rorelse" and post.get("kontanter_kopplad") else None
        if not redigera_post(self, self.app.konton, slag, post):
            return
        if gammal is not None:
            self.app._andra_kontanter_fran_overforing(gammal, post)
        if gammal_ins is not None:
            self.app._andra_kontanter_fran_insattning(gammal_ins, post)
        self._sortera_rorelser()
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()
        self.app._uppdatera_handelser()

    def _ta_bort_rorelse(self, post: dict) -> None:
        self.app.ta_bort_handelse("rorelse", post)

    def _ta_bort_overforing(self, post: dict) -> None:
        self.app.ta_bort_handelse("overforing", post)

    def _ta_bort(self) -> None:
        if self._valt == 0:
            messagebox.showinfo(
                "Plånboken",
                "Konto 1 (plånboken) kan inte tas bort – dit går inkomst och månadsbehov.",
                parent=self,
            )
            return
        namn = konto_visningsnamn(self.app.konton, self._valt + 1)
        if not messagebox.askyesno("Ta bort", f"Ta bort {namn}?", parent=self):
            return
        nr = self._valt + 1
        self.app.konton[self._valt] = tomt_konto()
        self.overskott_lbl.configure(text=self.app.overskott_text())
        self.app.rorelser = [r for r in self.app.rorelser if int(r.get("konto", 0)) != nr]
        self.app.overforingar = [
            o for o in self.app.overforingar
            if int(o.get("fran_konto", 0)) != nr and int(o.get("till_konto", 0)) != nr
        ]
        self.app._schemalagd_sparning()
        self._rita_lista()
        self._rita_detail()
        self.app._uppdatera_oversikt()

    def _tillbaka(self) -> None:
        self.app._konto_fonster = None
        self.app._uppdatera_oversikt()
        self.destroy()
        self.app.lift()
        self.app.focus_force()


class InkomstFonster(tk.Toplevel):
    def __init__(self, parent: "PensionsplanApp") -> None:
        super().__init__(parent)
        self.app = parent
        self.title("Inkomster")
        self.configure(bg=TEMA["bg"])
        self._borttagen: tuple[int, dict] | None = None
        self._bygg()
        self.protocol("WM_DELETE_WINDOW", self._tillbaka)
        centrera(self, 1480, 700)
        self.lift()
        self.focus_force()

    def _bygg(self) -> None:
        topp = tk.Frame(self, bg=TEMA["sida"], padx=18, pady=12)
        topp.pack(fill=tk.X)
        rubrik = tk.Frame(topp, bg=TEMA["sida"])
        rubrik.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(rubrik, text="Inkomster", font=("Segoe UI", 18, "bold"), bg=TEMA["sida"], fg=TEMA["vit"]).pack(anchor=tk.W)
        tk.Label(
            rubrik, text="Lägg perioder vartefter – från en månad till en slutmånad",
            font=("Segoe UI", 10), bg=TEMA["sida"], fg="#A9C5C8",
        ).pack(anchor=tk.W, pady=(2, 0))
        knapp(topp, "←  Översikt", self._tillbaka, bg=TEMA["accent"], pady=6).pack(side=tk.RIGHT, anchor=tk.CENTER)

        kropp = tk.Frame(self, bg=TEMA["bg"], padx=18, pady=14)
        kropp.pack(fill=tk.BOTH, expand=True)

        personer = tk.Frame(kropp, bg=TEMA["kort"], padx=14, pady=10)
        personer.pack(fill=tk.X, pady=(0, 12))
        tk.Label(personer, text="Personer", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        rad = tk.Frame(personer, bg=TEMA["kort"])
        rad.pack(fill=tk.X, pady=(6, 0))
        self.antal = tk.IntVar(value=self.app.antal_personer)
        tk.Radiobutton(rad, text="En", variable=self.antal, value=1, bg=TEMA["kort"], command=self._byt_antal).pack(side=tk.LEFT)
        tk.Radiobutton(rad, text="Två", variable=self.antal, value=2, bg=TEMA["kort"], command=self._byt_antal).pack(side=tk.LEFT, padx=(8, 16))
        self.p1 = tk.StringVar(value=self.app.person_namn[0] if self.app.person_namn else "")
        self.p2 = tk.StringVar(value=self.app.person_namn[1] if len(self.app.person_namn) > 1 else "")
        tk.Entry(rad, textvariable=self.p1, width=16, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 8))
        self.p2_entry = tk.Entry(rad, textvariable=self.p2, width=16, font=("Segoe UI", 10))
        self.p2_entry.pack(side=tk.LEFT)
        self.p1.trace_add("write", lambda *_: self._spara_personer())
        self.p2.trace_add("write", lambda *_: self._spara_personer())
        self._byt_antal(spara=False)

        tk.Label(
            kropp, text="Perioder", bg=TEMA["bg"], fg=TEMA["text"], font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        self.period_ram = tk.Frame(kropp, bg=TEMA["bg"])
        self.period_ram.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        knapprad = tk.Frame(kropp, bg=TEMA["bg"])
        knapprad.pack(fill=tk.X, anchor=tk.W)
        knapp(knapprad, "+  Lägg till period", self._ny_period, bg=TEMA["accent"], pady=7).pack(side=tk.LEFT)
        self.angra_knapp = knapp(
            knapprad, "Ångra borttagen", self._angra_borttagen, bg=TEMA["sida"], pady=7,
        )
        self.angra_knapp.pack(side=tk.LEFT, padx=(10, 0))
        self._synka_angra_knapp()
        self._rita_perioder()

    def _byt_antal(self, spara: bool = True) -> None:
        tva = self.antal.get() == 2
        self.p2_entry.configure(state=tk.NORMAL if tva else tk.DISABLED)
        if spara:
            self._spara_personer()
            self._rita_perioder()

    def _spara_personer(self) -> None:
        self.app.antal_personer = 1 if self.antal.get() == 1 else 2
        if self.app.antal_personer == 1:
            self.app.person_namn = [self.p1.get().strip()]
        else:
            self.app.person_namn = [self.p1.get().strip(), self.p2.get().strip()]
        self.app._schemalagd_sparning()
        self._uppdatera_period_rubriker()

    def _period_kolumner(self) -> list[tuple[str, int]]:
        n1 = self.p1.get().strip() or "Inkomst 1"
        n2 = self.p2.get().strip() or "Inkomst 2"
        kol = [
            ("Från år", 8),
            ("Månad", 7),
            ("Till år", 8),
            ("Månad", 7),
            (n1, 12),
        ]
        if self.antal.get() == 2:
            kol.append((n2, 12))
        kol += [("Behov / mån", 12), ("Över/under", 12), ("Anteckning", 42), ("", 3)]
        return kol

    def _uppdatera_period_rubriker(self) -> None:
        if not getattr(self, "_hdr_labels", None):
            return
        kol = self._period_kolumner()
        if len(kol) != len(self._hdr_labels):
            return
        for lbl, (text, _) in zip(self._hdr_labels, kol):
            lbl.configure(text=text)

    def _rita_perioder(self) -> None:
        for w in self.period_ram.winfo_children():
            w.destroy()
        self._hdr_labels = []
        tabell = tk.Frame(self.period_ram, bg=TEMA["bg"])
        tabell.pack(anchor=tk.W)
        self.period_tabell = tabell
        for col, (text, bredd) in enumerate(self._period_kolumner()):
            lbl = tk.Label(
                tabell, text=text, bg=TEMA["bg"], fg=TEMA["muted"],
                font=("Segoe UI", 8, "bold"), width=bredd, anchor=tk.W,
            )
            lbl.grid(row=0, column=col, padx=2, pady=(0, 4), sticky="w")
            self._hdr_labels.append(lbl)
            if text == "Anteckning":
                tabell.columnconfigure(col, weight=1, minsize=320)

        if not self.app.perioder:
            tk.Label(
                self.period_ram,
                text="Inga perioder än. Lägg till t.ex. från jul 2026 till dec 2028.",
                bg=TEMA["bg"], fg=TEMA["muted"], font=("Segoe UI", 10),
            ).pack(anchor=tk.W, pady=10)
            return
        for i, p in enumerate(self.app.perioder):
            self._period_rad(i, p)

    def _period_rad(self, i: int, p: dict) -> None:
        tabell = self.period_tabell
        rad_nr = i + 1
        ar_fran = tk.StringVar(value=str(p.get("ar_fran", self.app.start_ar)))
        manad_fran = tk.StringVar(value=str(p.get("manad_fran", "jan")))
        if manad_fran.get() not in MANADER:
            manad_fran.set("jan")
        ar_till = tk.StringVar(value=str(p.get("ar_till", self.app.start_ar)))
        manad_till = tk.StringVar(value=str(p.get("manad_till", "dec")))
        if manad_till.get() not in MANADER:
            manad_till.set("dec")
        person1 = tk.StringVar(value=str(p.get("person1", "")))
        person2 = tk.StringVar(value=str(p.get("person2", "")))
        behov = tk.StringVar(value=str(p.get("behov", "")))
        anteckning = tk.StringVar(value=str(p.get("anteckning", "")))

        ttk.Combobox(tabell, textvariable=ar_fran, values=[str(a) for a in ar_lista()], width=7, state="readonly").grid(row=rad_nr, column=0, padx=2, pady=3, sticky="w")
        ttk.Combobox(tabell, textvariable=manad_fran, values=MANADER, width=6, state="readonly").grid(row=rad_nr, column=1, padx=2, pady=3, sticky="w")
        ttk.Combobox(tabell, textvariable=ar_till, values=[str(a) for a in ar_lista()], width=7, state="readonly").grid(row=rad_nr, column=2, padx=2, pady=3, sticky="w")
        ttk.Combobox(tabell, textvariable=manad_till, values=MANADER, width=6, state="readonly").grid(row=rad_nr, column=3, padx=2, pady=3, sticky="w")
        col = 4
        tk.Entry(tabell, textvariable=person1, width=12, font=("Segoe UI", 10)).grid(row=rad_nr, column=col, padx=2, pady=3, sticky="w")
        col += 1
        if self.antal.get() == 2:
            tk.Entry(tabell, textvariable=person2, width=12, font=("Segoe UI", 10)).grid(row=rad_nr, column=col, padx=2, pady=3, sticky="w")
            col += 1
        tk.Entry(tabell, textvariable=behov, width=12, font=("Segoe UI", 10)).grid(row=rad_nr, column=col, padx=2, pady=3, sticky="w")
        col += 1
        saldo_lbl = tk.Label(
            tabell, text="", bg=TEMA["bg"], fg=TEMA["muted"],
            font=("Segoe UI", 10, "bold"), width=12, anchor=tk.W,
        )
        saldo_lbl.grid(row=rad_nr, column=col, padx=2, pady=3, sticky="w")
        col += 1
        tk.Entry(tabell, textvariable=anteckning, width=42, font=("Segoe UI", 10)).grid(
            row=rad_nr, column=col, padx=2, pady=3, sticky="ew",
        )
        col += 1
        tk.Button(
            tabell, text="X", command=lambda nr=i: self._ta_bort_period(nr),
            bg=TEMA["fara"], fg="white", relief=tk.FLAT, width=3, cursor="hand2",
        ).grid(row=rad_nr, column=col, padx=6, pady=3, sticky="w")

        def uppdatera_saldo(*_a: object) -> None:
            try:
                inkomst = heltal_varde(person1.get())
                if self.antal.get() == 2:
                    inkomst += heltal_varde(person2.get())
                diff = inkomst - heltal_varde(behov.get())
            except ValueError:
                saldo_lbl.configure(text="?", fg=TEMA["fara"])
                return
            if diff > 0:
                saldo_lbl.configure(text=f"+{formatera_kr(diff)}", fg=TEMA["pengar"])
            elif diff < 0:
                saldo_lbl.configure(text=formatera_kr(diff), fg=TEMA["fara"])
            else:
                saldo_lbl.configure(text="0 kr", fg=TEMA["muted"])

        def spara(*_a: object, idx: int = i) -> None:
            self.app.perioder[idx] = {
                "ar_fran": ar_fran.get(),
                "manad_fran": manad_fran.get(),
                "ar_till": ar_till.get(),
                "manad_till": manad_till.get(),
                "person1": person1.get(),
                "person2": person2.get(),
                "behov": behov.get(),
                "anteckning": anteckning.get(),
            }
            self.app._schemalagd_sparning()
            uppdatera_saldo()

        for var in (ar_fran, manad_fran, ar_till, manad_till, person1, person2, behov, anteckning):
            var.trace_add("write", spara)
        uppdatera_saldo()

    def _ny_period(self) -> None:
        if self.app.perioder:
            sista = self.app.perioder[-1]
            try:
                start_ar = int(sista.get("ar_till") or self.app.start_ar)
            except ValueError:
                start_ar = self.app.start_ar
            start_manad = sista.get("manad_till") or "jan"
            nr = MANAD_NAMN_TILL_NUMMER.get(str(start_manad), 12)
            nr += 1
            if nr > 12:
                nr = 1
                start_ar += 1
            manad_namn = MANADER[nr - 1]
        else:
            start_ar = self.app.start_ar
            manad_namn = MANADER[self.app.start_manad - 1]
        self.app.perioder.append({
            "ar_fran": str(start_ar),
            "manad_fran": manad_namn,
            "ar_till": str(start_ar + 2),
            "manad_till": "dec",
            "person1": "",
            "person2": "",
            "behov": "",
            "anteckning": "",
        })
        self.app._schemalagd_sparning()
        self._rita_perioder()

    def _ta_bort_period(self, nr: int) -> None:
        if 0 <= nr < len(self.app.perioder):
            self._borttagen = (nr, dict(self.app.perioder[nr]))
            del self.app.perioder[nr]
            self.app._schemalagd_sparning()
            self._synka_angra_knapp()
            self._rita_perioder()

    def _angra_borttagen(self) -> None:
        if not self._borttagen:
            return
        idx, period = self._borttagen
        idx = max(0, min(idx, len(self.app.perioder)))
        self.app.perioder.insert(idx, dict(period))
        self._borttagen = None
        self.app._schemalagd_sparning()
        self._synka_angra_knapp()
        self._rita_perioder()

    def _synka_angra_knapp(self) -> None:
        if not getattr(self, "angra_knapp", None):
            return
        state = tk.NORMAL if self._borttagen else tk.DISABLED
        self.angra_knapp.configure(state=state)

    def _tillbaka(self) -> None:
        self._spara_personer()
        self.app._inkomst_fonster = None
        self.app._uppdatera_oversikt()
        self.destroy()
        self.app.lift()
        self.app.focus_force()


class HandelserFonster(tk.Toplevel):
    """Aktuella insättningar, uttag och överföringar – kan tas bort härifrån."""

    def __init__(self, parent: "PensionsplanApp") -> None:
        super().__init__(parent)
        self.app = parent
        self.title("Händelser")
        self.configure(bg=TEMA["bg"])
        self._bygg()
        self.protocol("WM_DELETE_WINDOW", self._tillbaka)
        centrera(self, 1180, 720)
        self.lift()
        self.focus_force()

    def _bygg(self) -> None:
        topp = tk.Frame(self, bg=TEMA["sida"], padx=18, pady=12)
        topp.pack(fill=tk.X)
        rubrik = tk.Frame(topp, bg=TEMA["sida"])
        rubrik.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(
            rubrik, text="Händelser", font=("Segoe UI", 18, "bold"),
            bg=TEMA["sida"], fg=TEMA["vit"],
        ).pack(anchor=tk.W)
        tk.Label(
            rubrik, text="Senaste händelsen överst",
            font=("Segoe UI", 10), bg=TEMA["sida"], fg="#A9C5C8",
        ).pack(anchor=tk.W, pady=(2, 0))
        knapp(topp, "←  Översikt", self._tillbaka, bg=TEMA["accent"], pady=6).pack(
            side=tk.RIGHT, anchor=tk.CENTER,
        )
        self.angra_knapp = knapp(topp, "Ångra borttagen", self.app.angra_borttagen, bg="#8A9AA0", pady=6)
        self.angra_knapp.pack(side=tk.RIGHT, anchor=tk.CENTER, padx=(0, 8))

        kropp = tk.Frame(self, bg=TEMA["bg"], padx=18, pady=14)
        kropp.pack(fill=tk.BOTH, expand=True)

        scroll = tk.Frame(kropp, bg=TEMA["bg"])
        scroll.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(scroll, bg=TEMA["bg"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(scroll, orient=tk.VERTICAL, command=self.canvas.yview)
        self.lista = tk.Frame(self.canvas, bg=TEMA["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.lista, anchor=tk.NW)

        def _pa_inner(_e: tk.Event | None = None) -> None:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _pa_canvas(e: tk.Event) -> None:
            self.canvas.itemconfigure(self._win, width=e.width)

        def _hjul(e: tk.Event) -> str:
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        self.lista.bind("<Configure>", _pa_inner)
        self.canvas.bind("<Configure>", _pa_canvas)
        self.canvas.bind("<MouseWheel>", _hjul)
        self.lista.bind("<MouseWheel>", _hjul)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.status = tk.Label(
            kropp, text="", bg=TEMA["bg"], fg=TEMA["muted"], font=("Segoe UI", 9),
        )
        self.status.pack(anchor=tk.W, pady=(8, 0))
        self.varningar = tk.Label(
            kropp, text="", bg=TEMA["bg"], fg=TEMA["fara"], font=("Segoe UI", 10),
            justify=tk.LEFT, wraplength=1100,
        )
        self.varningar.pack(anchor=tk.W, pady=(4, 0))
        self._fyll()

    def _samla_poster(self) -> list[dict]:
        poster: list[dict] = []
        for r in self.app.rorelser:
            try:
                konto = int(r.get("konto", 0))
                ar = int(r.get("ar", self.app.start_ar))
                manad = _tolka_rorelse_manad(r)
                belopp = int(r.get("belopp", 0))
            except (TypeError, ValueError):
                continue
            typ = str(r.get("typ", ""))
            if str(r.get("kalla") or "") == "overskott":
                continue
            if typ == "insattning":
                text = "Insättning"
                tecken = 1
            else:
                text = "Uttag"
                tecken = -1
            poster.append({
                "slag": "rorelse",
                "post": r,
                "ar": ar,
                "manad": manad,
                "dag": _tolka_dag(r, ar, manad),
                "konto_txt": konto_visningsnamn(self.app.konton, konto),
                "beskrivning": text,
                "anteckning": str(r.get("anteckning", "")).strip(),
                "belopp": tecken * abs(belopp),
            })
        for o in self.app.overforingar:
            try:
                ar = int(heltal_varde(str(o.get("ar", self.app.start_ar))))
                manad = _tolka_rorelse_manad(o)
                fran = int(heltal_varde(str(o.get("fran_konto", "0"))))
                till = int(heltal_varde(str(o.get("till_konto", "0"))))
                belopp = heltal_varde(str(o.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            poster.append({
                "slag": "overforing",
                "post": o,
                "ar": ar,
                "manad": manad,
                "dag": _tolka_dag(o, ar, manad),
                "konto_txt": (
                    f"{konto_visningsnamn(self.app.konton, fran)} → "
                    f"{konto_visningsnamn(self.app.konton, till)}"
                ),
                "beskrivning": "Överföring",
                "anteckning": str(o.get("anteckning", "")).strip(),
                "belopp": belopp,
            })
        for rad in self.app.synliga_overskott():
            poster.append({
                "slag": "overskott",
                "post": rad["post"],
                "ar": rad["ar"],
                "manad": rad["manad"],
                "dag": rad["dag"],
                "konto_txt": konto_visningsnamn(
                    self.app.konton, self.app._overskott_konto_nr(rad)
                ),
                "beskrivning": "Kvar efter lön och räkningar",
                "anteckning": rad["anteckning"],
                "belopp": rad["belopp"],
            })
        poster.sort(
            key=lambda p: (int(p["ar"]), int(p["manad"]), int(p["dag"]), p["beskrivning"], abs(int(p["belopp"]))),
            reverse=True,
        )
        return poster

    def _fyll(self) -> None:
        for w in self.lista.winfo_children():
            w.destroy()
        self.angra_knapp.configure(state=tk.NORMAL if self.app.borttagna_handelser else tk.DISABLED)
        varningar = self.app.planvarningar()
        self.varningar.configure(text="\n".join(f"⚠ {v}" for v in varningar))
        poster = self._samla_poster()
        if not poster:
            tk.Label(
                self.lista, text="Inga insättningar, uttag eller överföringar ännu.",
                bg=TEMA["bg"], fg=TEMA["muted"], font=("Segoe UI", 11),
            ).pack(anchor=tk.W, padx=16, pady=16)
            self.status.configure(text="")
            return

        def _hjul(e: tk.Event) -> str:
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        def _bind(widget: tk.Misc) -> None:
            widget.bind("<MouseWheel>", _hjul)
            for barn in widget.winfo_children():
                _bind(barn)

        for p in poster:
            self._handelsekort(p)
        _bind(self.lista)
        self.status.configure(text=f"{len(poster)} händelser  ·  senaste överst")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _handelsekort(self, p: dict) -> None:
        manad_txt = formatera_datum(p["ar"], p["manad"], p["dag"]) if 1 <= p["manad"] <= 12 else str(p["manad"])
        belopp = p["belopp"]
        if p["slag"] == "overforing":
            belopp_txt = formatera_kr(belopp)
            farg = TEMA["text"]
        elif belopp < 0:
            belopp_txt = formatera_kr(belopp)
            farg = TEMA["fara"]
        else:
            belopp_txt = f"+{formatera_kr(belopp)}"
            farg = TEMA["pengar"]

        kort = tk.Frame(
            self.lista, bg=TEMA["kort"], padx=16, pady=12,
            highlightbackground=TEMA["linje"], highlightthickness=1,
        )
        kort.pack(fill=tk.X, padx=4, pady=5)
        vanster = tk.Frame(kort, bg=TEMA["kort"])
        vanster.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hoger = tk.Frame(kort, bg=TEMA["kort"])
        hoger.pack(side=tk.RIGHT, padx=(16, 0))

        tk.Label(
            vanster, text=manad_txt, anchor=tk.W, bg=TEMA["kort"], fg=TEMA["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W)
        tk.Label(
            vanster, text=p["konto_txt"], anchor=tk.W, bg=TEMA["kort"], fg=TEMA["text"],
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor=tk.W, pady=(2, 0))
        detalj = p["beskrivning"]
        if p.get("anteckning"):
            detalj = f"{detalj}   ·   {p['anteckning']}"
        tk.Label(
            vanster, text=detalj, anchor=tk.W, justify=tk.LEFT, wraplength=640,
            bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=(2, 0))

        tk.Label(
            hoger, text=belopp_txt, anchor=tk.E, bg=TEMA["kort"], fg=farg,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor=tk.E)
        knappar = tk.Frame(hoger, bg=TEMA["kort"])
        knappar.pack(anchor=tk.E, pady=(6, 0))
        tk.Button(
            knappar, text="Ändra",
            command=lambda post=p: self._andra(post),
            bg=TEMA["kort"], fg=TEMA["accent_mork"], relief=tk.FLAT,
            cursor="hand2", font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            knappar, text="Ta bort",
            command=lambda post=p: self._ta_bort(post),
            bg=TEMA["kort"], fg=TEMA["fara"], relief=tk.FLAT,
            cursor="hand2", font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

        def _oppna(_e: tk.Event | None = None, post=p) -> None:
            self._andra(post)

        for w in (kort, vanster, *vanster.winfo_children()):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", _oppna)

    def _andra(self, rad: dict) -> None:
        if rad["slag"] == "overskott":
            self.app.redigera_overskott(self, rad["ar"], rad["manad"])
            return
        post = rad["post"]
        gammal = dict(post) if rad["slag"] == "overforing" and post.get("kontanter_kopplad") else None
        gammal_ins = dict(post) if rad["slag"] == "rorelse" and post.get("kontanter_kopplad") else None
        if not redigera_post(self, self.app.konton, rad["slag"], post):
            return
        if gammal is not None:
            self.app._andra_kontanter_fran_overforing(gammal, post)
        if gammal_ins is not None:
            self.app._andra_kontanter_fran_insattning(gammal_ins, post)
        self._efter_andring()

    def _ta_bort(self, rad: dict) -> None:
        if rad["slag"] == "overskott":
            self.app.nolla_overskott(rad["ar"], rad["manad"])
            return
        self.app.ta_bort_handelse(rad["slag"], rad["post"])

    def _efter_andring(self) -> None:
        self.app.rorelser.sort(key=_rorelse_sortering)
        self.app.overforingar.sort(key=_rorelse_sortering)
        self.app._spara_allt(force=True)
        self.app.uppdatera_alla_fonster()

    def _tillbaka(self) -> None:
        self.app._handelser_fonster = None
        self.app._uppdatera_oversikt()
        self.destroy()
        self.app.lift()
        self.app.focus_force()


class PensionsplanApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Spar- och Pensionsplan")
        self.configure(bg=TEMA["bg"])
        self.katalog = app_katalog()
        migrera_gammal_sparfil(self.katalog)
        self.aktiv_plan = ""
        self._save_job: str | None = None
        self._laddar = False
        self._start_avbruten = False
        self._konto_fonster: KontoFonster | None = None
        self._inkomst_fonster: InkomstFonster | None = None
        self._handelser_fonster: HandelserFonster | None = None
        self.borttagna_handelser: list[tuple[str, dict]] = []
        self._belopp_visat = 0.0
        self._belopp_mal = 0
        self._belopp_job: str | None = None

        self.konton = standard_konton()
        self.rorelser: list[dict] = []
        self.overforingar: list[dict] = []
        self.perioder: list[dict] = []
        self.antal_personer = 2
        self.person_namn = ["", ""]
        nu_ar, nu_manad = dagens_ar_manad()
        self.start_ar = nu_ar
        self.start_manad = nu_manad
        self.visnings_ar = nu_ar
        self.visnings_manad = nu_manad
        self.visnings_dag = date.today().day
        self.senaste_resultat = []
        self.senaste_transaktioner: list[KontoTransaktion] = []
        self.senaste_fel = ""
        self.senaste_varning = ""

        self._aktier_behover_sparning = False
        self._skriver_aktier = False
        self._satt_ikon()
        self._bygg_ui()
        self.withdraw()
        self.minsize(1040, 860)
        self.protocol("WM_DELETE_WINDOW", self._stang)
        utdelning_core.set_storage(self._las_aktier_data, self._skriv_aktier_data)

    def _satt_ikon(self) -> None:
        sokvag = hamta_ikon_sokvag()
        if not sokvag:
            return
        try:
            self.iconbitmap(default=str(sokvag))
        except tk.TclError:
            pass

    def _bygg_ui(self) -> None:
        yttre = tk.Frame(self, bg=TEMA["bg"])
        yttre.pack(fill=tk.BOTH, expand=True)

        sida = tk.Frame(yttre, bg=TEMA["sida"], width=220)
        sida.pack(side=tk.LEFT, fill=tk.Y)
        sida.pack_propagate(False)

        tk.Label(
            sida, text="Spar- och\nPensionsplan", font=("Segoe UI", 16, "bold"), bg=TEMA["sida"], fg=TEMA["vit"], justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=18, pady=(22, 4))
        tk.Label(sida, text="Översikt", font=("Segoe UI", 10), bg=TEMA["sida"], fg="#8FB3B8").pack(anchor=tk.W, padx=18, pady=(0, 18))

        self._sidoknapp(sida, "Översikt", self._fokus_oversikt, aktiv=True)
        self._sidoknapp(sida, "Konton", self._oppna_konton)
        self._sidoknapp(sida, "Inkomster", self._oppna_inkomster)
        self._sidoknapp(sida, "Händelser", self._oppna_handelser)

        botten = tk.Frame(sida, bg=TEMA["sida"])
        botten.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=18)
        tk.Label(botten, text="Plan", bg=TEMA["sida"], fg="#8FB3B8", font=("Segoe UI", 8, "bold")).pack(anchor=tk.W)
        self.plan_val = tk.StringVar()
        self.plan_combo = ttk.Combobox(botten, textvariable=self.plan_val, state="readonly", width=18)
        self.plan_combo.pack(fill=tk.X, pady=(4, 8))
        self.plan_combo.bind("<<ComboboxSelected>>", lambda _e: self._byt_plan(self.plan_val.get()))
        tk.Button(
            botten, text="Ny plan", command=self._ny_plan, bg=TEMA["sida_aktiv"], fg=TEMA["vit"],
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            botten, text="Spara kopia…", command=self._spara_kopia, bg=TEMA["sida_aktiv"], fg=TEMA["vit"],
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            botten, text="Öppna från fil…", command=self._oppna_fran_fil, bg=TEMA["sida_aktiv"], fg=TEMA["vit"],
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            botten, text="Ta bort plan", command=self._ta_bort_plan, bg=TEMA["sida_aktiv"], fg="#E8C4C0",
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            botten, text="Inställningar", command=self._installningar, bg=TEMA["sida_aktiv"], fg=TEMA["vit"],
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=(8, 2))
        tk.Button(
            botten, text="Hjälp", command=self._oppna_manual, bg=TEMA["sida_aktiv"], fg=TEMA["vit"],
            relief=tk.FLAT, cursor="hand2", font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=(2, 0))
        tk.Label(
            botten, text="Gillar du programmet?\nSwisha gärna 100 kr till\n070-091 33 10. Tack!",
            bg=TEMA["sida"], fg="#8FB3B8", font=("Segoe UI", 8), justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(10, 0))

        self.mitt = tk.Frame(yttre, bg=TEMA["bg"])
        self.mitt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        kort = tk.Frame(self.mitt, bg=TEMA["kort"])
        kort.place(relx=0.5, rely=0.5, anchor=tk.CENTER, relwidth=0.86, relheight=0.95)

        self.plan_titel = tk.Label(kort, text="Ingen plan", font=("Segoe UI", 13), bg=TEMA["kort"], fg=TEMA["muted"])
        self.plan_titel.pack(pady=(18, 0))

        self.datum_valjare = DatumValjare(
            kort, self.visnings_ar, self.visnings_manad, self.visnings_dag, self._pa_datum,
        )
        self.datum_valjare.pack(pady=(4, 2))
        knapprad = tk.Frame(kort, bg=TEMA["kort"])
        knapprad.pack(pady=(0, 2))
        knapp(
            knapprad, "Spara PDF för valt datum", self._spara_saldo_pdf,
            bg=TEMA["accent"], pady=6,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.kurs_knapp = knapp(
            knapprad, "Uppdatera alla kurser", self._uppdatera_borskurser_knapp,
            bg=TEMA["accent_mork"], pady=6,
        )
        self.kurs_knapp.pack(side=tk.LEFT)
        self.kurs_status = tk.Label(
            kort, text="", font=("Segoe UI", 9), bg=TEMA["kort"], fg=TEMA["muted"],
        )
        self.kurs_status.pack(pady=(0, 4))

        self.belopp_label = tk.Label(
            kort, text="0 kr", font=("Segoe UI", 42, "bold"), bg=TEMA["kort"], fg=TEMA["pengar"],
        )
        self.belopp_label.pack(pady=(8, 0))
        self.under_label = tk.Label(
            kort, text="på alla konton tillsammans", font=("Segoe UI", 12), bg=TEMA["kort"], fg=TEMA["muted"],
        )
        self.under_label.pack()
        self.ranta_label = tk.Label(
            kort, text="", font=("Segoe UI", 10), bg=TEMA["kort"], fg=TEMA["muted"],
        )
        self.ranta_label.pack(pady=(6, 0))
        self.status_label = tk.Label(kort, text="", font=("Segoe UI", 11), bg=TEMA["kort"], fg=TEMA["accent_mork"])
        self.status_label.pack(pady=(10, 4))
        self.varning_label = tk.Label(
            kort, text="", font=("Segoe UI", 10), bg=TEMA["kort"], fg=TEMA["fara"],
            wraplength=760, justify=tk.CENTER,
        )

        self.konto_rad = tk.Frame(kort, bg=TEMA["kort"])
        self.konto_rad.pack(fill=tk.X, padx=16, pady=(8, 16))

        self.bind("<MouseWheel>", self._hjul_datum)

    def _sidoknapp(self, parent: tk.Frame, text: str, cmd, aktiv: bool = False) -> None:
        bg = TEMA["sida_aktiv"] if aktiv else TEMA["sida"]
        tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=TEMA["vit"],
            activebackground=TEMA["sida_aktiv"], activeforeground=TEMA["vit"],
            relief=tk.FLAT, anchor=tk.W, padx=18, pady=11, cursor="hand2",
            font=("Segoe UI", 12, "bold" if aktiv else "normal"),
        ).pack(fill=tk.X, padx=8, pady=2)

    def _hjul_datum(self, event: tk.Event) -> None:
        widget = event.widget
        while widget is not None:
            if isinstance(widget, Rullhjul):
                return
            widget = getattr(widget, "master", None)
        if event.delta > 0:
            self.datum_valjare._nudge(-1)
        else:
            self.datum_valjare._nudge(1)

    def _fokus_oversikt(self) -> None:
        self.lift()
        self.focus_force()

    def _oppna_konton(self, konto_idx: int | None = None) -> None:
        if not self.aktiv_plan:
            messagebox.showinfo("Ingen plan", "Skapa eller öppna en plan först.")
            return
        if self._konto_fonster is not None:
            try:
                if self._konto_fonster.winfo_exists():
                    if konto_idx is not None:
                        self._konto_fonster._valj(konto_idx)
                    self._konto_fonster.lift()
                    self._konto_fonster.focus_force()
                    return
            except tk.TclError:
                pass
        self._konto_fonster = KontoFonster(self, valt=konto_idx)

    def _oppna_inkomster(self) -> None:
        if not self.aktiv_plan:
            messagebox.showinfo("Ingen plan", "Skapa eller öppna en plan först.")
            return
        if self._inkomst_fonster is not None:
            try:
                if self._inkomst_fonster.winfo_exists():
                    self._inkomst_fonster.lift()
                    return
            except tk.TclError:
                pass
        self._inkomst_fonster = InkomstFonster(self)

    def _oppna_handelser(self) -> None:
        if not self.aktiv_plan:
            messagebox.showinfo("Ingen plan", "Skapa eller öppna en plan först.")
            return
        if self._handelser_fonster is not None:
            try:
                if self._handelser_fonster.winfo_exists():
                    self._handelser_fonster.lift()
                    self._handelser_fonster.focus_force()
                    return
            except tk.TclError:
                pass
        self._handelser_fonster = HandelserFonster(self)

    def _uppdatera_handelser(self) -> None:
        if self._handelser_fonster is None:
            return
        try:
            if self._handelser_fonster.winfo_exists():
                self._handelser_fonster._fyll()
        except tk.TclError:
            pass

    def uppdatera_alla_fonster(self) -> None:
        self._uppdatera_oversikt()
        if self._konto_fonster is not None:
            try:
                if self._konto_fonster.winfo_exists():
                    self._konto_fonster._rita_lista()
                    self._konto_fonster._rita_detail()
            except tk.TclError:
                pass
        self._uppdatera_handelser()

    def ta_bort_handelse(self, slag: str, post: dict) -> None:
        if slag == "overforing" and post.get("kontanter_kopplad"):
            self._andra_kontanter_fran_overforing(post, None)
        if slag == "rorelse" and post.get("kontanter_kopplad"):
            self._andra_kontanter_fran_insattning(post, None)
        if slag == "rorelse":
            self.rorelser = [r for r in self.rorelser if r is not post]
        else:
            self.overforingar = [o for o in self.overforingar if o is not post]
        self.borttagna_handelser.append((slag, post))
        self._spara_allt(force=True)
        self.uppdatera_alla_fonster()

    def angra_borttagen(self) -> None:
        if not self.borttagna_handelser:
            return
        slag, post = self.borttagna_handelser.pop()
        if slag == "rorelse":
            self.rorelser.append(post)
            self.rorelser.sort(key=_rorelse_sortering)
            if post.get("kontanter_kopplad"):
                self._andra_kontanter_fran_insattning(None, post)
        else:
            self.overforingar.append(post)
            self.overforingar.sort(key=_rorelse_sortering)
            if post.get("kontanter_kopplad"):
                self._andra_kontanter_fran_overforing(None, post)
        self._spara_allt(force=True)
        self.uppdatera_alla_fonster()

    def _pa_datum(self) -> None:
        if self._laddar:
            return
        self.visnings_ar, self.visnings_manad, self.visnings_dag = self.datum_valjare.valt()
        self._uppdatera_oversikt()
        self._schemalagd_sparning()

    def _visa_startval(self) -> None:
        """Startar direkt med senaste plan – ingen startsida."""
        try:
            planer = lista_planer(self.katalog)
            if planer:
                self._ladda_senaste_plan()
                self._visa_idag()
                markera_forsta_start_klar(self.katalog)
            else:
                self._visa_manual_forsta_gang()
                result = self._fragga_ny_plan("Ny plan", "Skapa din första plan:")
                if not result or not self._skapa_plan_fran_dialog(result):
                    self._start_avbruten = True
                    self.quit()
                    return
                markera_forsta_start_klar(self.katalog)
        except Exception as err:
            self.senaste_fel = str(err)
        if self._start_avbruten:
            return
        self.deiconify()
        centrera(self, 1220, 860)
        self.lift()
        self.focus_force()
        try:
            self._uppdatera_oversikt()
        except Exception as err:
            self.senaste_fel = str(err)
            self.status_label.configure(text=str(err), fg=TEMA["fara"])
        self.after(200, self._uppdatera_borskurser)
        self.after(700, self._visa_paminnelser)

    def _visa_kursstatus(self, text: str) -> None:
        etikett = getattr(self, "kurs_status", None)
        if etikett is None:
            return
        try:
            etikett.configure(text=text)
        except tk.TclError:
            pass

    def _uppdatera_borskurser_knapp(self) -> None:
        self._uppdatera_borskurser(visa=True)

    def _uppdatera_borskurser(self, visa: bool = False) -> None:
        """Hämtar nya börskurser i bakgrunden. Köp, antal och utdelningar rörs inte."""
        if self._start_avbruten:
            return
        if not self.aktiv_plan:
            if visa:
                self._visa_kursstatus("Öppna en plan först.")
            return
        if getattr(self, "_hamtar_kurser", False):
            if visa:
                self._visa_kursstatus("Hämtar kurser...")
            return
        poster: list[tuple[int, str, str]] = []
        for idx in self._borskonto_index():
            aktier = self.konton[idx].get("aktier")
            if not isinstance(aktier, dict):
                continue
            for stock in aktier.get("stocks") or []:
                ticker = str(stock.get("ticker") or "").strip()
                sid = str(stock.get("id") or "")
                if ticker and sid:
                    poster.append((idx, sid, ticker))
        if not poster:
            if visa:
                self._visa_kursstatus("Inga aktier att uppdatera.")
            return
        self._hamtar_kurser = True
        if visa:
            self.kurs_knapp.configure(state=tk.DISABLED, text="Hämtar kurser...")
            self._visa_kursstatus("Hämtar kurser...")

        def work() -> None:
            traffar: list[tuple[int, str, float]] = []
            miss = 0
            for idx, sid, ticker in poster:
                try:
                    traffar.append((idx, sid, utdelning_core.fetch_kurs(ticker)))
                except Exception:
                    miss += 1
            self.after(0, lambda: self._satt_borskurser(traffar, visa=visa, miss=miss))

        threading.Thread(target=work, daemon=True).start()

    def _satt_borskurser(self, traffar: list[tuple[int, str, float]], visa: bool = False, miss: int = 0) -> None:
        self._hamtar_kurser = False
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if visa:
            try:
                self.kurs_knapp.configure(state=tk.NORMAL, text="Uppdatera alla kurser")
            except tk.TclError:
                return
        if self._start_avbruten:
            return
        andra = False
        nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
        nordnet = self._aktiekonto_index()
        for idx, sid, kurs in traffar:
            if idx < 0 or idx >= len(self.konton):
                continue
            k = self.konton[idx]
            aktier = k.get("aktier")
            if not isinstance(aktier, dict):
                continue
            for stock in aktier.get("stocks") or []:
                if str(stock.get("id") or "") != sid:
                    continue
                if stock.get("price") != kurs:
                    stock["price"] = kurs
                    stock["updated"] = nu
                    andra = True
                break
            if idx == nordnet:
                self._synka_aktie_siffror(k)
            else:
                self._synka_vardeaktier(k)
        if andra and not self._laddar:
            self._schemalagd_sparning()
            self.uppdatera_alla_fonster()
        if not visa:
            return
        if miss and not traffar:
            text = "Kurserna gick inte att hämta. De gamla ligger kvar."
        elif miss:
            text = f"Uppdaterade {len(traffar)} kurser. {miss} gick inte att hämta."
        else:
            text = "Alla kurser är uppdaterade."
        self._visa_kursstatus(text)

    def _visa_paminnelser(self) -> None:
        if self._start_avbruten:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            texter = texter_att_visa(self.katalog, data=self._hamta_all_data())
        except Exception:
            texter = []
        if texter:
            messagebox.showinfo("Påminnelse", "\n\n".join(texter), parent=self)
        try:
            self.after(30 * 60 * 1000, self._visa_paminnelser)
        except tk.TclError:
            pass

    def _visa_manual_forsta_gang(self) -> None:
        self._oppna_manual()
        markera_manual_visad(self.katalog)

    def _skrivbord(self) -> Path:
        home = Path.home()
        for mapp in (
            home / "Desktop",
            home / "Skrivbord",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Skrivbord",
            Path(r"C:\OneDrive\Skrivbord"),
        ):
            if mapp.is_dir():
                return mapp
        return home

    def _dokument(self) -> Path:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
        return Path.home() / "Documents"

    def _plan_mapp(self) -> str:
        vald = str(hamta_installningar(self.katalog).get("pdf_mapp") or "")
        if vald and Path(vald).is_dir():
            return vald
        mapp = self._dokument() / "Spar- och Pensionsplan"
        try:
            mapp.mkdir(parents=True, exist_ok=True)
            return str(mapp)
        except OSError:
            return str(self._skrivbord())

    def _pdf_mapp(self) -> Path:
        return Path(self._plan_mapp())

    def _hall_fem_pdf(self, sparad: Path) -> None:
        """Behåller de fem nyaste PDF:erna som programmet sparat för planen. Andra filer rörs inte."""
        if not hamta_installningar(self.katalog).get("behall_fem_pdf", True):
            return
        monster = re.compile(re.escape(self.aktiv_plan) + r" \d{4}-\d{2}-\d{2}\.pdf", re.IGNORECASE)
        mapp = sparad.parent
        try:
            pdfs = [p for p in mapp.iterdir() if p.is_file() and monster.fullmatch(p.name)]
            pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for gammal in pdfs[5:]:
                gammal.unlink()
        except OSError:
            pass

    def _installningar(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Inställningar")
        dialog.configure(bg=TEMA["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        kort = tk.Frame(dialog, bg=TEMA["kort"], padx=22, pady=18)
        kort.pack(padx=14, pady=14)
        tk.Label(kort, text="Inställningar", font=("Segoe UI", 16, "bold"), bg=TEMA["kort"], fg=TEMA["text"]).pack(anchor=tk.W)

        tk.Label(kort, text="Mapp för PDF och kopior", bg=TEMA["kort"], fg=TEMA["text"], font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(12, 0))
        mapp_lbl = tk.Label(kort, text=self._plan_mapp(), bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9), wraplength=420, justify=tk.LEFT)
        mapp_lbl.pack(anchor=tk.W, pady=(2, 6))

        def valj() -> None:
            ny = filedialog.askdirectory(parent=dialog, title="Välj mapp för PDF och kopior", initialdir=self._plan_mapp())
            if ny:
                spara_installningar(self.katalog, {"pdf_mapp": ny})
                mapp_lbl.configure(text=self._plan_mapp())

        knapp(kort, "Välj mapp…", valj, bg=TEMA["sida"], pady=4).pack(anchor=tk.W)

        fem = tk.BooleanVar(value=bool(hamta_installningar(self.katalog).get("behall_fem_pdf", True)))
        tk.Checkbutton(
            kort, text="Behåll bara de 5 senaste PDF:erna för varje plan (andra filer rörs aldrig)",
            variable=fem, command=lambda: spara_installningar(self.katalog, {"behall_fem_pdf": bool(fem.get())}),
            bg=TEMA["kort"], activebackground=TEMA["kort"], font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(12, 0))

        tk.Label(
            kort,
            text="Vilket konto som får överskott och vilka konton som har ränta varje månad väljer du på kontot under Konton.",
            bg=TEMA["kort"], fg=TEMA["muted"], font=("Segoe UI", 9), wraplength=420, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(12, 0))

        knapp(kort, "Stäng", dialog.destroy, bg=TEMA["accent"], pady=6).pack(anchor=tk.E, pady=(14, 0))
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        centrera(dialog, dialog.winfo_reqwidth() + 8, dialog.winfo_reqheight() + 8)

    def _spara_saldo_pdf(self) -> None:
        if not self.aktiv_plan:
            messagebox.showinfo("Ingen plan", "Skapa eller öppna en plan först.", parent=self)
            return
        aktiva = [i for i, k in enumerate(self.konton) if konto_ar_aktivt(k)]
        if not aktiva:
            messagebox.showinfo("Inga konton", "Lägg till minst ett konto först.", parent=self)
            return
        ar, manad, dag = self.visnings_ar, self.visnings_manad, self.visnings_dag
        saldon = self.saldo_per_konto(ar, manad, dag)
        rader = [
            (i + 1, konto_visningsnamn(self.konton, i + 1), saldon[i])
            for i in aktiva
        ]
        datum_txt = formatera_datum(ar, manad, dag)
        forslag = f"{self.aktiv_plan} {ar}-{manad:02d}-{dag:02d}.pdf"
        sokvag = filedialog.asksaveasfilename(
            parent=self,
            title="Spara PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=forslag,
            initialdir=str(self._pdf_mapp()),
        )
        if not sokvag:
            return
        mal = Path(sokvag)
        if mal.suffix.lower() != ".pdf":
            mal = mal.with_suffix(".pdf")
        try:
            skriv_kontoutdrag_pdf(
                mal,
                plan_namn=self.aktiv_plan,
                datum_text=datum_txt,
                konton=rader,
                varning=self.senaste_fel or self.senaste_varning,
            )
        except OSError as err:
            messagebox.showerror("Fel", f"Kunde inte spara PDF:\n{err}", parent=self)
            return
        except Exception as err:
            messagebox.showerror("Fel", f"Kunde inte skapa PDF:\n{err}", parent=self)
            return
        self._hall_fem_pdf(mal)
        messagebox.showinfo("PDF", f"Sparad:\n{mal}", parent=self)
        try:
            os.startfile(mal)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _oppna_manual(self) -> None:
        sokvag = hamta_manual_sokvag()
        if not sokvag:
            messagebox.showinfo("Hjälp", f"Manualen hittades inte ({MANUAL_FIL}).")
            return
        try:
            os.startfile(sokvag)  # type: ignore[attr-defined]
        except OSError as err:
            messagebox.showerror("Fel", f"Kunde inte öppna manualen:\n{err}")

    def _fragga_ny_plan(self, titel: str = "Ny plan", meddelande: str = "") -> dict | None:
        dialog = NyPlanDialog(self, titel=titel, meddelande=meddelande)
        self.wait_window(dialog)
        return dialog.result

    def _skapa_plan_fran_dialog(self, result: dict) -> bool:
        try:
            self.aktiv_plan = result["plan_namn"]
            self._nollstall()
            self.konton[8] = tomt_borskonto("Avanza", "0", KURSVINSTKONTO)
            self.konton[9] = tomt_borskonto("Nordnet", "30", UTDELNINGSKONTO)
            self.antal_personer = result["antal"]
            self.person_namn = result["namn"] if result["antal"] == 2 else [result["namn"][0]]
            self._spara_allt(force=True)
            self._uppdatera_plan_lista()
            return True
        except ValueError as err:
            messagebox.showerror("Fel", str(err))
            return False

    def _nollstall(self) -> None:
        nu_ar, nu_manad = dagens_ar_manad()
        self.konton = standard_konton()
        self.rorelser = []
        self.overforingar = []
        self.borttagna_handelser = []
        self.perioder = []
        self.start_ar = nu_ar
        self.start_manad = nu_manad
        self.visnings_ar = nu_ar
        self.visnings_manad = nu_manad
        self.visnings_dag = date.today().day
        self.senaste_resultat = []
        self.senaste_transaktioner = []
        self.senaste_fel = ""
        self.senaste_varning = ""

    def _visa_idag(self) -> None:
        """Vid start visas dagens datum, inte det man senast bläddrade till."""
        idag = date.today()
        self.visnings_ar = idag.year
        self.visnings_manad = idag.month
        self.visnings_dag = idag.day
        self.datum_valjare.satt(self.visnings_ar, self.visnings_manad, self.visnings_dag)
        self._uppdatera_oversikt()

    def _ladda_senaste_plan(self) -> None:
        planer = lista_planer(self.katalog)
        if not planer:
            self.aktiv_plan = ""
            return
        namn = hamta_aktiv_plan(self.katalog)
        if namn not in planer:
            namn = planer[0]
        self.aktiv_plan = namn
        self._ladda_aktiv_plan()

    def _byt_plan(self, namn: str) -> None:
        if not namn:
            return
        try:
            namn = normalisera_plan_namn(namn)
            if namn != self.aktiv_plan:
                self._spara_allt(force=True)
                self.aktiv_plan = namn
            self._ladda_aktiv_plan()
        except ValueError as err:
            messagebox.showerror("Fel", str(err))

    def _ny_plan(self) -> None:
        self._oppna_manual()
        result = self._fragga_ny_plan("Ny plan", "Ange namn och personer för den nya planen:")
        if result:
            self._skapa_plan_fran_dialog(result)
            self._uppdatera_oversikt()

    def _namn_fran_planfil(self, sokvag: Path) -> str:
        try:
            return normalisera_plan_namn(sokvag.stem)
        except ValueError:
            rensat = "".join(ch if ch.isalnum() or ch in " -_åäöÅÄÖ" else " " for ch in sokvag.stem).strip()
            rensat = " ".join(rensat.split()) or "importerad plan"
            return normalisera_plan_namn(rensat)

    def _spara_kopia(self) -> None:
        if not self.aktiv_plan:
            messagebox.showinfo("Ingen plan", "Skapa eller öppna en plan först.")
            return
        self._spara_allt(force=True)
        sokvag = filedialog.asksaveasfilename(
            parent=self,
            title="Spara kopia av planen",
            defaultextension=".json",
            filetypes=[("Plan", "*.json"), ("Alla filer", "*.*")],
            initialfile=f"{self.aktiv_plan}.json",
            initialdir=self._plan_mapp(),
        )
        if not sokvag:
            return
        try:
            spara_data(Path(sokvag), self._hamta_all_data())
        except OSError as err:
            messagebox.showerror("Fel", f"Kunde inte spara kopian:\n{err}")
            return
        messagebox.showinfo("Kopia sparad", f"Kopian ligger här:\n{sokvag}")

    def _oppna_fran_fil(self) -> bool:
        sokvag = filedialog.askopenfilename(
            parent=self,
            title="Öppna plan från fil",
            filetypes=[("Plan", "*.json"), ("Alla filer", "*.*")],
            initialdir=self._plan_mapp(),
        )
        if not sokvag:
            return False
        fil = Path(sokvag)
        data = ladda_data(fil)
        if not data:
            messagebox.showerror("Fel", f"Kunde inte läsa planen:\n{fil}")
            return False
        try:
            namn = self._namn_fran_planfil(fil)
        except ValueError as err:
            messagebox.showerror("Fel", str(err))
            return False
        if namn in lista_planer(self.katalog) and namn != self.aktiv_plan:
            if not messagebox.askyesno(
                "Planen finns redan",
                f"Planen ”{namn}” finns redan här. Skriva över den?",
            ):
                nytt = simpledialog.askstring(
                    "Nytt namn", "Ange ett namn för den importerade planen:", parent=self,
                )
                if not nytt:
                    return False
                try:
                    namn = normalisera_plan_namn(nytt)
                except ValueError as err:
                    messagebox.showerror("Fel", str(err))
                    return False
        if self.aktiv_plan:
            self._spara_allt(force=True)
        self.aktiv_plan = namn
        self._laddar = True
        try:
            self._ladda_fran_data(uppgradera_plan_data(data))
        finally:
            self._laddar = False
        self._spara_allt(force=True)
        spara_aktiv_plan(self.katalog, self.aktiv_plan)
        self._uppdatera_plan_lista()
        self._uppdatera_oversikt()
        return True

    def _ta_bort_plan(self) -> None:
        namn = self.plan_val.get() or self.aktiv_plan
        if not namn:
            return
        if not messagebox.askyesno("Ta bort plan", f"Ta bort planen ”{namn}” permanent?"):
            return
        try:
            ta_bort_plan(self.katalog, namn)
            if namn == self.aktiv_plan:
                self.aktiv_plan = ""
                self._nollstall()
            self._uppdatera_plan_lista()
            self._uppdatera_oversikt()
        except OSError as err:
            messagebox.showerror("Fel", str(err))

    def _uppdatera_plan_lista(self) -> None:
        planer = lista_planer(self.katalog)
        self.plan_combo["values"] = planer
        self.plan_val.set(self.aktiv_plan if self.aktiv_plan in planer else "")
        self.plan_titel.configure(text=self.aktiv_plan or "Ingen plan")

    def _ladda_aktiv_plan(self) -> None:
        if not self.aktiv_plan:
            return
        fil = plan_fil(self.katalog, self.aktiv_plan)
        data = ladda_data(fil)
        self._laddar = True
        try:
            if not data:
                self._nollstall()
                self._spara_allt(force=True)
                return
            data = uppgradera_plan_data(data)
            self._ladda_fran_data(data)
        finally:
            self._laddar = False
        if self._aktier_behover_sparning:
            self._aktier_behover_sparning = False
            self._spara_allt(force=True)
        spara_aktiv_plan(self.katalog, self.aktiv_plan)
        self._uppdatera_plan_lista()
        self._uppdatera_oversikt()

    def _ladda_fran_data(self, data: dict) -> None:
        g = data.get("gemensamt", {}) or {}
        personer = normalisera_personer(data.get("personer"))
        self.antal_personer = personer["antal"]
        self.person_namn = personer["namn"]
        try:
            self.start_ar = int(g.get("start_ar") or self.start_ar)
        except (TypeError, ValueError):
            pass
        manad_namn = str(g.get("start_manad") or MANADER[self.start_manad - 1])
        self.start_manad = MANAD_NAMN_TILL_NUMMER.get(manad_namn, self.start_manad)
        try:
            self.visnings_ar = int(g.get("visnings_ar") or self.start_ar)
        except (TypeError, ValueError):
            self.visnings_ar = self.start_ar
        if self.visnings_ar not in ar_lista():
            self.visnings_ar = OVERSIKT_START_AR
        vis_m = g.get("visnings_manad")
        if isinstance(vis_m, int):
            self.visnings_manad = vis_m
        elif vis_m in MANAD_NAMN_TILL_NUMMER:
            self.visnings_manad = MANAD_NAMN_TILL_NUMMER[str(vis_m)]
        else:
            self.visnings_manad = self.start_manad
        idag = date.today()
        try:
            self.visnings_dag = int(g.get("visnings_dag") or 0)
        except (TypeError, ValueError):
            self.visnings_dag = 0
        if self.visnings_dag < 1:
            if self.visnings_ar == idag.year and self.visnings_manad == idag.month:
                self.visnings_dag = idag.day
            else:
                self.visnings_dag = 1
        self.visnings_dag = min(self.visnings_dag, calendar.monthrange(self.visnings_ar, self.visnings_manad)[1])

        self.konton = standard_konton()
        for i, raw in enumerate(g.get("konton") or []):
            if i >= ANTAL_KONTON or not isinstance(raw, dict):
                continue
            self.konton[i] = {
                "aktiv": bool(raw.get("aktiv", konto_ar_aktivt(raw))),
                "namn": str(raw.get("namn", "")).strip(),
                "sparat": str(raw.get("sparat", "0")),
                "ranta": str(raw.get("ranta", "2.4")),
                "skatt": str(raw.get("skatt", "30")),
                "rante_andringar": list(raw.get("rante_andringar") or []),
                "overskott": bool(raw.get("overskott")),
                "manadsranta": bool(raw.get("manadsranta")),
            }
            typ = gissa_borstyp(raw)
            if typ:
                self.konton[i]["borstyp"] = typ
            if isinstance(raw.get("aktier"), dict):
                self.konton[i]["aktier"] = raw["aktier"]
            if not self.konton[i]["aktiv"]:
                self.konton[i]["aktiv"] = konto_ar_aktivt(self.konton[i])

        self.overforingar = list(g.get("overforingar") or [])
        self.borttagna_handelser = []
        self.rorelser = list(g.get("konto_rorelser") or [])
        if not self.rorelser:
            for post in g.get("engangsinsattningar") or []:
                if isinstance(post, dict):
                    self.rorelser.append({
                        "konto": int(post.get("konto") or 1),
                        "typ": "insattning",
                        "ar": int(heltal_varde(str(post.get("ar", self.start_ar)))),
                        "manad": MANAD_NAMN_TILL_NUMMER.get(str(post.get("manad", "jan")), 1),
                        "belopp": heltal_varde(str(post.get("belopp", "0"))),
                    })
            for post in g.get("engangsuttag") or []:
                if isinstance(post, dict):
                    self.rorelser.append({
                        "konto": int(post.get("konto") or 1),
                        "typ": "uttag",
                        "ar": int(heltal_varde(str(post.get("ar", self.start_ar)))),
                        "manad": MANAD_NAMN_TILL_NUMMER.get(str(post.get("manad", "jan")), 1),
                        "belopp": heltal_varde(str(post.get("belopp", "0"))),
                    })

        plan = data.get("plan") or {}
        self.perioder = []
        for p in plan.get("perioder") or g.get("perioder") or []:
            if not isinstance(p, dict):
                continue
            # Äldre planfiler hade personernas namn som nycklar, i samma ordning som person 1 och 2.
            gamla = [k for k in p if k not in PERIOD_NYCKLAR]
            self.perioder.append({
                "ar_fran": str(p.get("ar_fran", self.start_ar)),
                "manad_fran": str(p.get("manad_fran", "jan")),
                "ar_till": str(p.get("ar_till", self.start_ar)),
                "manad_till": str(p.get("manad_till", "dec")),
                "person1": str(p.get("person1", p.get(gamla[0], "") if len(gamla) > 0 else "")),
                "person2": str(p.get("person2", p.get(gamla[1], "") if len(gamla) > 1 else "")),
                "behov": str(p.get("behov", "")),
                "anteckning": str(p.get("anteckning", "")),
            })

        self.rorelser.sort(key=_rorelse_sortering)
        self.overforingar.sort(key=_rorelse_sortering)
        self._importera_portfolj_om_tom()

        self.datum_valjare.satt(self.visnings_ar, self.visnings_manad, self.visnings_dag)

    def _hamta_all_data(self) -> dict:
        return {
            "version": 15,
            "personer": {
                "antal": self.antal_personer,
                "namn": self.person_namn if self.antal_personer == 2 else [self.person_namn[0] if self.person_namn else ""],
            },
            "gemensamt": {
                "start_ar": str(self.start_ar),
                "start_manad": MANADER[self.start_manad - 1],
                "visnings_ar": self.visnings_ar,
                "visnings_manad": self.visnings_manad,
                "visnings_dag": self.visnings_dag,
                "slut_ar": str(self._slut_ar()),
                "konton": self.konton,
                "konto_rorelser": self.rorelser,
                "overforingar": self.overforingar,
                "auto_overfor_uttag_konto2": False,
                "engangsuttag": [],
                "engangsinsattningar": [],
            },
            "plan": {"perioder": self.perioder},
        }

    def _schemalagd_sparning(self, *_: object) -> None:
        if self._laddar or not self.aktiv_plan:
            return
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(700, self._spara_allt)

    def _spara_allt(self, force: bool = False) -> None:
        if not self.aktiv_plan:
            return
        if not force:
            self._save_job = None
        try:
            spara_data(plan_fil(self.katalog, self.aktiv_plan), self._hamta_all_data())
            spara_aktiv_plan(self.katalog, self.aktiv_plan)
        except OSError as err:
            messagebox.showerror(
                "Kunde inte spara",
                f"Planen sparades inte:\n{err}\n\nKontrollera att mappen inte är låst (t.ex. OneDrive).",
                parent=self,
            )
        except ValueError as err:
            messagebox.showerror("Kunde inte spara", str(err), parent=self)

    def _slut_ar(self) -> int:
        slut = self.visnings_ar
        for p in self.perioder:
            try:
                slut = max(slut, int(p.get("ar_till") or slut))
            except ValueError:
                pass
        return max(slut, self.start_ar)

    def _bokfort_saldo(
        self,
        till_ar: int,
        till_manad: int,
        *,
        inkludera_overforingar: bool = True,
        till_dag: int = 31,
    ) -> list[int]:
        """Startsaldo + insättningar/uttag/överföringar t.o.m. vald dag (utan ränta)."""
        till = _manad_nyckel(till_ar, till_manad)
        saldon = [0] * ANTAL_KONTON
        for i, k in enumerate(self.konton):
            if konto_ar_aktivt(k):
                saldon[i] = heltal_varde(str(k.get("sparat", "0")))

        for r in self.rorelser:
            try:
                ar = int(r.get("ar"))
                manad = _tolka_rorelse_manad(r)
                konto = int(r.get("konto", 0))
                belopp = int(r.get("belopp", 0))
            except (TypeError, ValueError):
                continue
            if str(r.get("kalla") or "") == "overskott":
                continue
            if konto < 1 or konto > ANTAL_KONTON:
                continue
            if _manad_nyckel(ar, manad) > till:
                continue
            if _manad_nyckel(ar, manad) == till and _tolka_dag(r, ar, manad) > till_dag:
                continue
            if r.get("typ") == "insattning":
                saldon[konto - 1] += belopp
            else:
                saldon[konto - 1] -= belopp

        if not inkludera_overforingar:
            return self._satt_aktie_saldo(saldon)

        for o in self.overforingar:
            try:
                ar = int(heltal_varde(str(o.get("ar", self.start_ar))))
                manad = _tolka_rorelse_manad(o)
                fran = int(heltal_varde(str(o.get("fran_konto", "0"))))
                till_konto = int(heltal_varde(str(o.get("till_konto", "0"))))
                belopp = heltal_varde(str(o.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            if _manad_nyckel(ar, manad) > till or belopp <= 0:
                continue
            if _manad_nyckel(ar, manad) == till and _tolka_dag(o, ar, manad) > till_dag:
                continue
            if fran < 1 or fran > ANTAL_KONTON or till_konto < 1 or till_konto > ANTAL_KONTON:
                continue
            if fran == till_konto:
                continue
            # Skippa ogiltiga överföringar så fallback inte ljuger
            if saldon[fran - 1] < belopp:
                continue
            saldon[fran - 1] -= belopp
            saldon[till_konto - 1] += belopp
        return self._satt_aktie_saldo(saldon)

    def _las_rante_andringar(self, raw: list) -> list[Ranteandring]:
        resultat: list[Ranteandring] = []
        for a in raw or []:
            if not isinstance(a, dict):
                continue
            try:
                ar = int(heltal_varde(str(a.get("ar", self.start_ar))))
                manad = _tolka_rorelse_manad(a)
                ranta = decimal_varde(str(a.get("ranta", "2.4")), 2.4)
                skatt = decimal_varde(str(a.get("skatt", "30")), 30.0)
            except ValueError:
                continue
            resultat.append(Ranteandring(
                ar=ar, manad=manad, ranta_procent=ranta, skatt_pa_ranta_procent=skatt,
            ))
        return resultat

    def _rorelser_for_config(self) -> tuple[list[int], list[Engangsinsattning], list[Engangsuttag], list[Overforing]]:
        """Rörelser före planstart bäddas in i startsaldot så de inte tappas bort."""
        start_tal = _manad_nyckel(self.start_ar, self.start_manad)
        justering = [0] * ANTAL_KONTON
        insattningar: list[Engangsinsattning] = []
        uttag: list[Engangsuttag] = []
        overforingar: list[Overforing] = []

        for r in self.rorelser:
            try:
                ar = int(r.get("ar"))
                manad = _tolka_rorelse_manad(r)
                konto = int(r.get("konto", 0))
                belopp = int(r.get("belopp", 0))
            except (TypeError, ValueError):
                continue
            if str(r.get("kalla") or "") == "overskott":
                continue
            if konto < 1 or konto > ANTAL_KONTON or belopp == 0:
                continue
            dag = _tolka_dag(r, ar, manad)
            if _manad_nyckel(ar, manad) < start_tal:
                if r.get("typ") == "insattning":
                    justering[konto - 1] += belopp
                else:
                    justering[konto - 1] -= belopp
                continue
            if r.get("typ") == "insattning":
                insattningar.append(Engangsinsattning(ar=ar, manad=manad, belopp=belopp, konto=konto, dag=dag))
            else:
                uttag.append(Engangsuttag(ar=ar, manad=manad, belopp=belopp, konto=konto, dag=dag))

        for o in self.overforingar:
            try:
                ar = int(heltal_varde(str(o.get("ar", self.start_ar))))
                manad = _tolka_rorelse_manad(o)
                fran = int(heltal_varde(str(o.get("fran_konto", "1"))))
                till_konto = int(heltal_varde(str(o.get("till_konto", "1"))))
                belopp = heltal_varde(str(o.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            if belopp <= 0 or fran == till_konto:
                continue
            dag = _tolka_dag(o, ar, manad)
            if _manad_nyckel(ar, manad) < start_tal:
                if 1 <= fran <= ANTAL_KONTON:
                    justering[fran - 1] -= belopp
                if 1 <= till_konto <= ANTAL_KONTON:
                    justering[till_konto - 1] += belopp
                continue
            overforingar.append(Overforing(
                ar=ar, manad=manad, fran_konto=fran, till_konto=till_konto, belopp=belopp, dag=dag,
            ))
        return justering, insattningar, uttag, overforingar

    def insatt_till_aktiekonto(self) -> int:
        """Summan av överföringar och insättningar till Aktiekonto. Räknas inte in i värdet."""
        return self.insatt_till_konto(self._aktiekonto_index())

    def insatt_till_konto(self, idx: int | None) -> int:
        if idx is None:
            return 0
        nr = idx + 1
        summa = 0
        for post in self.overforingar:
            try:
                till = int(heltal_varde(str(post.get("till_konto", "0"))))
                belopp = heltal_varde(str(post.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            if till == nr and belopp > 0:
                summa += belopp
        for post in self.rorelser:
            if str(post.get("typ") or "") != "insattning" or not post.get("kontanter_kopplad"):
                continue
            try:
                konto = int(heltal_varde(str(post.get("konto", "0"))))
                belopp = heltal_varde(str(post.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            if konto == nr and belopp > 0:
                summa += belopp
        return summa

    def _sparkonto_index(self) -> int | None:
        """Kontot som är valt för framtida överskott och underskott."""
        for i, k in enumerate(self.konton):
            if i != 0 and k.get("overskott") and konto_ar_aktivt(k) and not self._ar_borskonto(i):
                return i
        return None

    def overskott_text(self) -> str:
        idx = self._sparkonto_index()
        namn = konto_visningsnamn(self.konton, (idx if idx is not None else 0) + 1)
        return f"Framtida överskott och underskott räknas på {namn}"

    def _ar_framtida_overskott(self, rad: dict) -> bool:
        return rad.get("post") is None and (rad["ar"], rad["manad"]) >= self._automatik_fran()

    def _overskott_visas_pa(self, rad: dict, konto_index: int) -> bool:
        if self._ar_framtida_overskott(rad):
            return konto_index == self._sparkonto_index()
        return konto_index == 0

    def _overskott_konto_nr(self, rad: dict) -> int:
        if self._ar_framtida_overskott(rad):
            idx = self._sparkonto_index()
            if idx is not None:
                return idx + 1
        return 1

    def _konto_med_typ(self, typ: str) -> int | None:
        for i, k in enumerate(self.konton):
            if k.get("borstyp") == typ and konto_ar_aktivt(k):
                return i
        return None

    def _aktiekonto_index(self) -> int | None:
        return self._konto_med_typ(UTDELNINGSKONTO)

    def _aktier_index(self) -> int | None:
        return self._konto_med_typ(KURSVINSTKONTO)

    def _ar_borskonto(self, idx: int | None) -> bool:
        return idx is not None and idx in (self._aktiekonto_index(), self._aktier_index())

    def _borskonto_index(self) -> list[int]:
        return [i for i in (self._aktiekonto_index(), self._aktier_index()) if i is not None]

    def _las_aktier_data(self) -> dict:
        idx = self._aktiekonto_index()
        if idx is None:
            return {"stocks": [], "cash": 0, "dividends": []}
        raw = self.konton[idx].get("aktier")
        if not isinstance(raw, dict):
            raw = {}
        return {
            "stocks": list(raw.get("stocks") or []),
            "cash": raw.get("cash") or 0,
            "dividends": list(raw.get("dividends") or []),
        }

    def _skriv_aktier_data(self, data: dict) -> None:
        if self._skriver_aktier:
            return
        idx = self._aktiekonto_index()
        if idx is None:
            return
        self._skriver_aktier = True
        try:
            k = self.konton[idx]
            befintlig = k.get("aktier") if isinstance(k.get("aktier"), dict) else {}
            kontanter = data["kontanter"] if "kontanter" in data else befintlig.get("kontanter", 0)
            k["aktier"] = {
                "stocks": data.get("stocks") or [],
                "cash": data.get("cash") or 0,
                "dividends": data.get("dividends") or [],
                "kontanter": kontanter,
            }
            self._synka_aktie_siffror(k)
            if not self._laddar:
                self._schemalagd_sparning()
                self._uppdatera_oversikt()
        finally:
            self._skriver_aktier = False

    def _las_vardeaktier(self) -> dict:
        idx = self._aktier_index()
        if idx is None:
            return {"stocks": [], "cash": 0, "dividends": []}
        raw = self.konton[idx].get("aktier")
        if not isinstance(raw, dict):
            raw = {}
        return {
            "stocks": list(raw.get("stocks") or []),
            "cash": raw.get("cash") or 0,
            "dividends": list(raw.get("dividends") or []),
        }

    def _skriv_vardeaktier(self, data: dict) -> None:
        if self._skriver_aktier:
            return
        idx = self._aktier_index()
        if idx is None:
            return
        self._skriver_aktier = True
        try:
            k = self.konton[idx]
            befintlig = k.get("aktier") if isinstance(k.get("aktier"), dict) else {}
            kontanter = data["kontanter"] if "kontanter" in data else befintlig.get("kontanter", 0)
            k["aktier"] = {
                "stocks": data.get("stocks") or [],
                "cash": data.get("cash") or 0,
                "dividends": data.get("dividends") or [],
                "kontanter": kontanter,
            }
            self._synka_vardeaktier(k)
            if not self._laddar:
                self._schemalagd_sparning()
                self._uppdatera_oversikt()
        finally:
            self._skriver_aktier = False

    def _kontanter_belopp(self, k: dict | None = None) -> float:
        if k is None:
            idx = self._aktiekonto_index()
            if idx is None:
                return 0.0
            k = self.konton[idx]
        try:
            return round(float((k.get("aktier") or {}).get("kontanter") or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    def kontantkassa(self) -> float:
        return self._kontanter_belopp()

    def satt_kontantkassa(self, belopp: float) -> None:
        self._satt_kontanter_pa(self._aktiekonto_index(), belopp)

    def aktier_kontantkassa(self) -> float:
        idx = self._aktier_index()
        if idx is None:
            return 0.0
        return self._kontanter_belopp(self.konton[idx])

    def satt_aktier_kontanter(self, belopp: float) -> None:
        self._satt_kontanter_pa(self._aktier_index(), belopp)

    def _satt_kontanter_pa(self, idx: int | None, belopp: float) -> None:
        if idx is None:
            return
        k = self.konton[idx]
        aktier = k.get("aktier")
        if not isinstance(aktier, dict):
            aktier = {"stocks": [], "cash": 0, "dividends": []}
            k["aktier"] = aktier
        aktier["kontanter"] = round(float(belopp), 2)
        if idx == self._aktier_index():
            self._synka_vardeaktier(k)
        else:
            self._synka_aktie_siffror(k)
        if not self._laddar:
            self._schemalagd_sparning()
            self._uppdatera_oversikt()

    def _aktie_tal(self, k: dict) -> tuple[int, float, float]:
        """Saldo (börs plus båda kassorna), visad ränta på grundinsatsen, motorränta utan ränta på kassorna."""
        siffror = utdelning_core.portfolj_siffror(k.get("aktier") or {})
        kontanter = self._kontanter_belopp(k) + float(siffror["kassa"])
        bors = int(siffror["borsvarde"])
        totalt = int(round(bors + kontanter))
        yoc = float(siffror["ranta"])
        if totalt > 0 and bors > 0:
            motor = yoc * bors / totalt
        elif totalt > 0:
            motor = 0.0
        else:
            motor = yoc
        return totalt, yoc, motor

    def _delta_mot_konto(self, post: dict | None, nr: int) -> float:
        if not post:
            return 0.0
        belopp = heltal_varde(str(post.get("belopp") or 0))
        fran = int(heltal_varde(str(post.get("fran_konto") or 0)))
        till = int(heltal_varde(str(post.get("till_konto") or 0)))
        delta = 0
        if till == nr:
            delta += belopp
        if fran == nr:
            delta -= belopp
        return float(delta)

    def _insattning_belopp_pa(self, post: dict | None, idx: int) -> int:
        if not post or not post.get("kontanter_kopplad"):
            return 0
        if str(post.get("typ") or "") != "insattning":
            return 0
        try:
            nr = int(heltal_varde(str(post.get("konto") or 0)))
            belopp = heltal_varde(str(post.get("belopp") or 0))
        except (TypeError, ValueError):
            return 0
        if nr != idx + 1:
            return 0
        return int(belopp)

    def _andra_kontanter_fran_insattning(self, fore: dict | None, efter: dict | None) -> None:
        for idx in self._borskonto_index():
            delta = self._insattning_belopp_pa(efter, idx) - self._insattning_belopp_pa(fore, idx)
            if delta:
                self._satt_kontanter_pa(idx, self._kontanter_belopp(self.konton[idx]) + delta)

    def _andra_kontanter_fran_overforing(self, fore: dict | None, efter: dict | None) -> None:
        for idx in self._borskonto_index():
            nr = idx + 1
            delta = self._delta_mot_konto(efter, nr) - self._delta_mot_konto(fore, nr)
            if delta:
                self._satt_kontanter_pa(idx, self._kontanter_belopp(self.konton[idx]) + delta)

    def _synka_aktie_siffror(self, k: dict) -> bool:
        totalt, yoc, _motor = self._aktie_tal(k)
        sparat = str(totalt)
        ranta = f"{yoc:.2f}"
        andrad = (
            str(k.get("sparat", "")) != sparat
            or str(k.get("ranta", "")) != ranta
            or bool(k.get("rante_andringar"))
        )
        k["sparat"] = sparat
        k["ranta"] = ranta
        k["rante_andringar"] = []
        k["aktiv"] = True
        return andrad

    def _varde_tal(self, k: dict) -> tuple[int, float]:
        """Saldo (börs plus kassa) och plus eller minus mot det som betalats."""
        siffror = utdelning_core.varde_siffror(k.get("aktier") or {})
        kontanter = self._kontanter_belopp(k)
        totalt = int(round(int(siffror["borsvarde"]) + kontanter))
        return totalt, float(siffror["plus"])

    def _synka_vardeaktier(self, k: dict) -> bool:
        totalt, _plus = self._varde_tal(k)
        sparat = str(totalt)
        andrad = str(k.get("sparat", "")) != sparat or str(k.get("ranta", "")) != "0" or bool(k.get("rante_andringar"))
        k["sparat"] = sparat
        k["ranta"] = "0"
        k["rante_andringar"] = []
        k["aktiv"] = True
        return andrad

    def _las_extern_portfolj(self) -> dict | None:
        kandidater = [self.katalog / "portfolj.json"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            kandidater.append(Path(appdata) / "Utdelning" / "portfolj.json")
        bast = None
        bast_antal = 0
        for sokvag in kandidater:
            data = ladda_data(sokvag)
            if not isinstance(data, dict):
                continue
            antal = len(data.get("stocks") or [])
            if antal > bast_antal:
                bast = data
                bast_antal = antal
        if not bast:
            return None
        return {
            "stocks": list(bast.get("stocks") or []),
            "cash": bast.get("cash") or 0,
            "dividends": list(bast.get("dividends") or []),
        }

    def _importera_portfolj_om_tom(self) -> None:
        idx = self._aktiekonto_index()
        if idx is None:
            return
        k = self.konton[idx]
        aktier = k.get("aktier")
        har_data = isinstance(aktier, dict) and (
            aktier.get("stocks") or aktier.get("dividends") or aktier.get("cash")
        )
        if not har_data and self.aktiv_plan == hamta_aktiv_plan(self.katalog):
            extern = self._las_extern_portfolj()
            if extern:
                k["aktier"] = extern
                har_data = True
        if har_data and self._synka_aktie_siffror(k):
            self._aktier_behover_sparning = True
        self._sakerstall_varde_kassa()

    def _sakerstall_varde_kassa(self) -> None:
        """Första gången blir det sparade saldot kontantkassan, så startbeloppet finns kvar."""
        idx = self._aktier_index()
        if idx is None:
            return
        k = self.konton[idx]
        raw = k.get("aktier")
        if isinstance(raw, dict) and ("kontanter" in raw or raw.get("stocks")):
            if self._synka_vardeaktier(k):
                self._aktier_behover_sparning = True
            return
        if not isinstance(raw, dict):
            raw = {"stocks": [], "cash": 0, "dividends": []}
            k["aktier"] = raw
        raw["kontanter"] = float(heltal_varde(str(k.get("sparat", "0"))))
        if self._synka_vardeaktier(k):
            self._aktier_behover_sparning = True

    def _satt_aktie_saldo(self, saldon: list[int]) -> list[int]:
        for idx in self._borskonto_index():
            if 0 <= idx < len(saldon):
                if idx == self._aktier_index():
                    saldon[idx] = self._varde_tal(self.konton[idx])[0]
                else:
                    saldon[idx] = self._aktie_tal(self.konton[idx])[0]
        return saldon

    def _rorelser_utan_aktie_kredit(self):
        """Börskontonas saldo är värdet. Pengar som flyttats dit dras bara från avsändaren."""
        justering, insattningar, uttag, overforingar = self._rorelser_for_config()
        nrs = [i + 1 for i in self._borskonto_index()]
        if not nrs:
            return justering, insattningar, uttag, overforingar
        for nr in nrs:
            justering[nr - 1] = 0
        insattningar = [post for post in insattningar if post.konto not in nrs]
        uttag = [post for post in uttag if post.konto not in nrs]
        kvar: list[Overforing] = []
        for post in overforingar:
            till_bors = post.till_konto in nrs
            fran_bors = post.fran_konto in nrs
            if till_bors and fran_bors:
                continue
            if till_bors:
                uttag.append(Engangsuttag(
                    ar=post.ar, manad=post.manad, belopp=post.belopp, konto=post.fran_konto, dag=post.dag,
                ))
            elif fran_bors:
                insattningar.append(Engangsinsattning(
                    ar=post.ar, manad=post.manad, belopp=post.belopp, konto=post.till_konto, dag=post.dag,
                ))
            else:
                kvar.append(post)
        return justering, insattningar, uttag, kvar

    def _automatik_fran(self) -> tuple[int, int]:
        """Första månaden där ränta och överskott bara är en framtidsuträkning."""
        idag = date.today()
        if idag.month == 12:
            return idag.year + 1, 1
        return idag.year, idag.month + 1

    def _overskott_karta(self) -> dict[tuple[int, int], int]:
        """Det som blir över efter lön och räkningar, per månad."""
        karta: dict[tuple[int, int], int] = {}
        for p in self.perioder:
            try:
                ar_fran = int(p.get("ar_fran") or self.start_ar)
                ar_till = int(p.get("ar_till") or ar_fran)
            except ValueError:
                continue
            m_fran = MANAD_NAMN_TILL_NUMMER.get(str(p.get("manad_fran", "jan")), 1)
            m_till = MANAD_NAMN_TILL_NUMMER.get(str(p.get("manad_till", "dec")), 12)
            person1 = heltal_varde(str(p.get("person1", "0")))
            person2 = heltal_varde(str(p.get("person2", "0"))) if self.antal_personer == 2 else 0
            behov = heltal_varde(str(p.get("behov", "0")))
            over = person1 + person2 - behov
            if over <= 0:
                continue
            for ar, manad in generera_manader(ar_fran, ar_till, m_fran, m_till):
                karta[(ar, manad)] = over
        return karta

    def _sparad_overskott(self, ar: int, manad: int) -> dict | None:
        for post in self.rorelser:
            if str(post.get("kalla") or "") != "overskott":
                continue
            try:
                if int(post.get("ar")) == ar and _tolka_rorelse_manad(post) == manad:
                    return post
            except (TypeError, ValueError):
                continue
        return None

    def _overskott_ersattning(self) -> dict[tuple[int, int], int]:
        ersatt: dict[tuple[int, int], int] = {}
        for post in self.rorelser:
            if str(post.get("kalla") or "") != "overskott":
                continue
            try:
                ar = int(post.get("ar"))
                manad = _tolka_rorelse_manad(post)
                belopp = heltal_varde(str(post.get("belopp", "0")))
            except (TypeError, ValueError):
                continue
            ersatt[(ar, manad)] = belopp
        return ersatt

    def synliga_overskott(self) -> list[dict]:
        """Överskott t.o.m. visat datum. Osparade rader har post=None."""
        till = self.visnings_ar * 12 + self.visnings_manad
        start = self.start_ar * 12 + self.start_manad
        rader: list[dict] = []
        sedda: set[tuple[int, int]] = set()
        for (ar, manad), raknat in sorted(self._overskott_karta().items()):
            tal = ar * 12 + manad
            if tal < start or tal > till:
                continue
            sparad = self._sparad_overskott(ar, manad)
            sedda.add((ar, manad))
            if sparad is None and (ar, manad) < self._automatik_fran():
                continue
            rader.append(self._overskott_rad(ar, manad, raknat, sparad))
        for (ar, manad), belopp in self._overskott_ersattning().items():
            if (ar, manad) in sedda:
                continue
            tal = ar * 12 + manad
            if tal < start or tal > till:
                continue
            rader.append(self._overskott_rad(ar, manad, belopp, self._sparad_overskott(ar, manad)))
        rader.sort(key=lambda rad: (rad["ar"], rad["manad"], rad["dag"]))
        return rader

    def _overskott_rad(self, ar: int, manad: int, raknat: int, sparad: dict | None) -> dict:
        if sparad:
            dag = _tolka_dag(sparad, ar, manad)
            belopp = heltal_varde(str(sparad.get("belopp", "0")))
            anteckning = str(sparad.get("anteckning", "")).strip()
        else:
            dag = 1
            belopp = raknat
            anteckning = ""
        return {
            "ar": ar,
            "manad": manad,
            "dag": dag,
            "belopp": belopp,
            "anteckning": anteckning,
            "post": sparad,
        }

    def redigera_overskott(self, parent: tk.Misc, ar: int, manad: int) -> bool:
        sparad = self._sparad_overskott(ar, manad)
        raknat = self._overskott_karta().get((ar, manad), 0)
        if sparad:
            dag = _tolka_dag(sparad, ar, manad)
            belopp = heltal_varde(str(sparad.get("belopp", "0")))
            anteckning = str(sparad.get("anteckning", "")).strip()
        else:
            dag = 1
            belopp = raknat
            anteckning = ""
        dialog = RorelseDialog(
            parent,
            "Kvar efter lön och räkningar",
            "insattning",
            ar,
            manad,
            dag,
            befintlig={"belopp": belopp, "anteckning": anteckning, "dag": dag},
        )
        parent.wait_window(dialog)
        if not dialog.result:
            return False
        post = dialog.result
        post["konto"] = 1
        post["typ"] = "insattning"
        post["kalla"] = "overskott"
        if sparad:
            sparad.clear()
            sparad.update(post)
        else:
            self.rorelser.append(post)
        self.rorelser.sort(key=_rorelse_sortering)
        self._spara_allt(force=True)
        self.uppdatera_alla_fonster()
        return True

    def nolla_overskott(self, ar: int, manad: int) -> None:
        sparad = self._sparad_overskott(ar, manad)
        if sparad and heltal_varde(str(sparad.get("belopp", "0"))) == 0:
            self.rorelser = [post for post in self.rorelser if post is not sparad]
        elif sparad:
            sparad["belopp"] = 0
        else:
            self.rorelser.append({
                "konto": 1,
                "typ": "insattning",
                "kalla": "overskott",
                "ar": ar,
                "manad": manad,
                "dag": 1,
                "belopp": 0,
                "anteckning": "",
            })
        self.rorelser.sort(key=_rorelse_sortering)
        self._spara_allt(force=True)
        self.uppdatera_alla_fonster()

    def saldo_per_konto(self, ar: int | None = None, manad: int | None = None, dag: int | None = None) -> list[int]:
        """Saldo per konto t.o.m. vald dag (översiktens datum som standard)."""
        ar = self.visnings_ar if ar is None else ar
        manad = self.visnings_manad if manad is None else manad
        if dag is None:
            dag = self.visnings_dag if (ar, manad) == (self.visnings_ar, self.visnings_manad) else 31
        self.senaste_varning = ""
        try:
            config = self._las_config(slut_ar=ar, slut_manad=manad, slut_dag=dag)
            korning = kora_plan_med_transaktioner(config)
            self.senaste_resultat = korning.manader
            self.senaste_transaktioner = korning.transaktioner
            self.senaste_fel = ""
            trad = None
            for rad in korning.manader:
                if rad.ar == ar and rad.manad == manad:
                    trad = rad
                    break
            if trad is None:
                for rad in korning.manader:
                    if (rad.ar, rad.manad) <= (ar, manad):
                        trad = rad
            if trad:
                if trad.krav_overforing:
                    self.senaste_varning = trad.varning_text or (
                        f"Pengarna tar slut {trad.manad_namn} {trad.ar}."
                    )
                elif korning.manader and korning.manader[-1].krav_overforing:
                    sista = korning.manader[-1]
                    if (ar, manad) > (sista.ar, sista.manad):
                        self.senaste_varning = (
                            f"{sista.varning_text or 'Pengarna tar slut.'} "
                            f"Visar saldo t.o.m. {sista.manad_namn} {sista.ar}."
                        )
                        trad = sista
                return [trad.konto_efter(i + 1) for i in range(ANTAL_KONTON)]
            if korning.manader:
                sista = korning.manader[-1]
                if sista.krav_overforing:
                    self.senaste_varning = sista.varning_text or "Pengarna tar slut."
                return [sista.konto_efter(i + 1) for i in range(ANTAL_KONTON)]
        except ValueError as err:
            self.senaste_fel = str(err)
            self.senaste_resultat = []
            self.senaste_transaktioner = []
            # Tillämpa inte ogiltiga överföringar i fallback
            return self._bokfort_saldo(ar, manad, inkludera_overforingar=True, till_dag=dag)
        return self._bokfort_saldo(ar, manad, till_dag=dag)

    def saldo_for_konto(self, konto_nr: int, ar: int | None = None, manad: int | None = None) -> int:
        saldon = self.saldo_per_konto(ar, manad)
        if 1 <= konto_nr <= len(saldon):
            return saldon[konto_nr - 1]
        return 0

    def _las_config(
        self,
        slut_ar: int | None = None,
        slut_manad: int | None = None,
        slut_dag: int | None = None,
    ) -> PlanConfig:
        justering, insattningar, uttag, overforingar = self._rorelser_utan_aktie_kredit()
        aktie_idx = self._aktiekonto_index()
        konton: list[KontoConfig] = []
        for i, k in enumerate(self.konton):
            if not konto_ar_aktivt(k):
                konton.append(KontoConfig())
                continue
            if i == aktie_idx:
                totalt, _yoc, motor = self._aktie_tal(k)
                konton.append(KontoConfig(
                    sparat_kr=totalt,
                    ranta_procent=motor,
                    skatt_pa_ranta_procent=decimal_varde(k.get("skatt", "30"), 30.0),
                    ranta_andringar=[],
                    namn=str(k.get("namn", "")).strip(),
                ))
                continue
            if i == self._aktier_index():
                totalt, _plus = self._varde_tal(k)
                konton.append(KontoConfig(
                    sparat_kr=totalt,
                    ranta_procent=0.0,
                    skatt_pa_ranta_procent=decimal_varde(k.get("skatt", "30"), 30.0),
                    ranta_andringar=[],
                    namn=str(k.get("namn", "")).strip(),
                ))
                continue
            konton.append(KontoConfig(
                sparat_kr=heltal_varde(k.get("sparat", "0")) + justering[i],
                ranta_procent=decimal_varde(k.get("ranta", "2.4"), 2.4),
                skatt_pa_ranta_procent=decimal_varde(k.get("skatt", "30"), 30.0),
                ranta_andringar=self._las_rante_andringar(k.get("rante_andringar") or []),
                namn=str(k.get("namn", "")).strip(),
                overskott=bool(k.get("overskott")) and i != 0,
                manadsranta=bool(k.get("manadsranta")),
            ))
        while len(konton) < ANTAL_KONTON:
            konton.append(KontoConfig())

        manadsvarden: dict[tuple[int, int], dict[str, int]] = {}
        for p in self.perioder:
            try:
                ar_fran = int(p.get("ar_fran") or self.start_ar)
                ar_till = int(p.get("ar_till") or ar_fran)
            except ValueError:
                continue
            m_fran = MANAD_NAMN_TILL_NUMMER.get(str(p.get("manad_fran", "jan")), 1)
            m_till = MANAD_NAMN_TILL_NUMMER.get(str(p.get("manad_till", "dec")), 12)
            rad = {
                "person1": heltal_varde(str(p.get("person1", "0"))),
                "person2": heltal_varde(str(p.get("person2", "0"))) if self.antal_personer == 2 else 0,
                "behov": heltal_varde(str(p.get("behov", "0"))),
            }
            for ar, manad in generera_manader(ar_fran, ar_till, m_fran, m_till):
                manadsvarden[(ar, manad)] = rad


        beraknad_slut_ar = self._slut_ar() if slut_ar is None else slut_ar
        beraknad_slut_manad = 12 if slut_manad is None else slut_manad
        if self.visnings_ar > beraknad_slut_ar or (
            self.visnings_ar == beraknad_slut_ar and self.visnings_manad > beraknad_slut_manad
        ):
            beraknad_slut_ar = self.visnings_ar
            beraknad_slut_manad = self.visnings_manad
        if slut_ar is not None:
            beraknad_slut_ar = max(beraknad_slut_ar, slut_ar)
            if slut_manad is not None and beraknad_slut_ar == slut_ar:
                beraknad_slut_manad = max(beraknad_slut_manad, slut_manad)

        return PlanConfig(
            start_ar=self.start_ar,
            start_manad=self.start_manad,
            slut_ar=beraknad_slut_ar,
            slut_manad=beraknad_slut_manad,
            slut_dag=slut_dag,
            konton=konton,
            manadsvarden=manadsvarden,
            engangsinsattningar=insattningar,
            engangsuttag=uttag,
            overforingar=overforingar,
            overskott_ersattning=self._overskott_ersattning(),
            auto_overfor_uttag_konto2=False,
            automatik_fran=self._automatik_fran(),
        )


    def _satt_konto_rutnat(self, antal: int) -> int:
        """Lika breda rutor. Upp till tio konton blir två rader, så alla syns."""
        if antal <= 1:
            kolumner = 1
        elif antal <= 5:
            kolumner = antal
        elif antal <= 10:
            kolumner = 5
        else:
            kolumner = 6
        rader = max(1, (antal + kolumner - 1) // kolumner) if antal else 1
        for c in range(12):
            self.konto_rad.columnconfigure(c, weight=1 if c < kolumner else 0, uniform="konto" if c < kolumner else "")
        for r in range(4):
            self.konto_rad.rowconfigure(r, weight=1 if r < rader else 0, uniform="kontorad" if r < rader else "")
        return kolumner

    def _uppdatera_oversikt(self) -> None:
        self.plan_titel.configure(text=self.aktiv_plan or "Ingen plan")
        aktiva = [i for i, k in enumerate(self.konton) if konto_ar_aktivt(k)]
        totalt = 0
        per_konto: list[tuple[int, str, int]] = []
        status = "Lägg till konton i sidopanelen för att börja."

        if aktiva:
            saldon = self.saldo_per_konto(self.visnings_ar, self.visnings_manad)
            for i in aktiva:
                belopp = saldon[i]
                per_konto.append((i, konto_visningsnamn(self.konton, i + 1), belopp))
                totalt += belopp
            if self.senaste_fel:
                status = self.senaste_fel
            elif self.senaste_varning:
                status = self.senaste_varning
            else:
                status = formatera_datum(self.visnings_ar, self.visnings_manad, self.visnings_dag)
        else:
            self.senaste_resultat = []
            self.senaste_transaktioner = []
            self.senaste_fel = ""
            self.senaste_varning = ""

        self._animera_belopp(totalt)
        farg = TEMA["fara"] if (self.senaste_fel or self.senaste_varning) else TEMA["accent_mork"]
        self.status_label.configure(text=status, fg=farg)
        self._uppdatera_planvarningar(bool(aktiva))
        self._uppdatera_ranta_ar()
        for w in self.konto_rad.winfo_children():
            w.destroy()
        kolumner = self._satt_konto_rutnat(len(per_konto))
        for n, (idx, namn, belopp) in enumerate(per_konto):
            pill = tk.Frame(self.konto_rad, bg="#E7F4F1", padx=8, pady=8, cursor="hand2")
            pill.grid(row=n // kolumner, column=n % kolumner, padx=4, pady=4, sticky="nsew")
            inre = tk.Frame(pill, bg="#E7F4F1")
            inre.pack(expand=True, fill=tk.BOTH)
            tk.Frame(inre, bg="#E7F4F1").pack(expand=True)
            namn_lbl = tk.Label(
                inre, text=namn, bg="#E7F4F1", fg=TEMA["muted"],
                font=("Segoe UI", 8), wraplength=150, justify=tk.CENTER,
            )
            namn_lbl.pack()
            belopp_lbl = tk.Label(
                inre, text=formatera_kr(belopp), bg="#E7F4F1", fg=TEMA["pengar"],
                font=("Segoe UI", 11, "bold"),
            )
            belopp_lbl.pack(pady=(2, 0))
            extra = " "
            extra_farg = TEMA["accent_mork"]
            if self._aktiekonto_index() == idx:
                siffror = utdelning_core.portfolj_siffror(self._las_aktier_data())
                extra = f"{siffror['ranta']:.2f} %".replace(".", ",")
            elif self._aktier_index() == idx:
                plus = utdelning_core.varde_siffror(self._las_vardeaktier())["plus"]
                extra = f"{plus:+.2f} %".replace(".", ",")
                if plus < 0:
                    extra_farg = TEMA["fara"]
            extra_lbl = tk.Label(
                inre, text=extra, bg="#E7F4F1", fg=extra_farg, font=("Segoe UI", 8),
            )
            extra_lbl.pack()
            tk.Frame(inre, bg="#E7F4F1").pack(expand=True)

            def _oppna(_e: tk.Event | None = None, konto=idx) -> None:
                self._oppna_konton(konto)

            def _bind_klick(widget: tk.Misc) -> None:
                widget.bind("<Button-1>", _oppna)
                for barn in widget.winfo_children():
                    _bind_klick(barn)

            _bind_klick(pill)
        antal = len(aktiva)
        if antal:
            text = f"på {antal} konto" + ("n" if antal != 1 else "") + " tillsammans"
        else:
            text = "på alla konton tillsammans"
        if (self.visnings_ar, self.visnings_manad) >= self._automatik_fran():
            text += ". Ränta, överskott och underskott är med i uträkningen"
        self.under_label.configure(text=text)

    def planvarningar(self) -> list[str]:
        """Varningar för hela planen, oavsett vilket datum som visas."""
        try:
            return kora_plan_med_transaktioner(self._las_config()).varningar
        except ValueError as err:
            return [str(err)]

    def _uppdatera_planvarningar(self, har_konton: bool = True) -> None:
        varningar = self.planvarningar() if har_konton else []
        if not varningar:
            self.varning_label.configure(text="")
            self.varning_label.pack_forget()
            return
        text = "⚠ " + varningar[0]
        if len(varningar) > 1:
            text += f"\n… och {len(varningar) - 1} till (se Händelser)"
        self.varning_label.configure(text=text)
        if not self.varning_label.winfo_manager():
            self.varning_label.pack(pady=(0, 4), before=self.konto_rad)

    def _uppdatera_ranta_ar(self) -> None:
        """Visa samlad nettoränta t.o.m. den månad som är vald."""
        if not any(konto_ar_aktivt(k) for k in self.konton):
            self.ranta_label.configure(text="")
            return
        ar = self.visnings_ar
        manad = self.visnings_manad
        if (ar, manad) < (self.start_ar, self.start_manad):
            self.ranta_label.configure(text="")
            return
        sista = calendar.monthrange(ar, manad)[1]
        try:
            config = self._las_config(slut_ar=ar + 1, slut_manad=1, slut_dag=31)
            korning = kora_plan_med_transaktioner(config)
        except ValueError:
            self.ranta_label.configure(text="")
            return
        ranta_totalt = samlad_ranta_visad(
            korning.manader, ar, manad, self._automatik_fran(),
        )
        self.ranta_label.configure(
            text=f"Samlad ränta t.o.m. {sista} {MANADER[manad - 1]} {ar}  ·  {formatera_kr(ranta_totalt)} netto",
            fg=TEMA["pengar"] if ranta_totalt > 0 else TEMA["muted"],
        )

    def _animera_belopp(self, mal: int) -> None:
        self._belopp_mal = mal
        if self._belopp_job:
            self.after_cancel(self._belopp_job)
        self._tick_belopp()

    def _tick_belopp(self) -> None:
        delta = self._belopp_mal - self._belopp_visat
        if abs(delta) < 8:
            self._belopp_visat = float(self._belopp_mal)
            self.belopp_label.configure(text=formatera_kr(self._belopp_mal))
            self._belopp_job = None
            return
        self._belopp_visat += delta * 0.22
        self.belopp_label.configure(text=formatera_kr(int(self._belopp_visat)))
        self._belopp_job = self.after(16, self._tick_belopp)

    def _stang(self) -> None:
        if self._save_job:
            self.after_cancel(self._save_job)
        self._spara_allt()
        self.destroy()


def main() -> None:
    app = PensionsplanApp()
    if app._start_avbruten:
        try:
            app.destroy()
        except tk.TclError:
            pass
        return
    app.after(80, app._visa_startval)
    app.mainloop()


if __name__ == "__main__":
    main()
 