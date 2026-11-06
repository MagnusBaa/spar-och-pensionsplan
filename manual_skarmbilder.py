"""Tar skärmbilderna till manualen.

Körs från en kopia av programmet (egen planer-mapp), aldrig från C:\\Pensionsplan:
    python manual_skarmbilder.py <mapp för bilder>
"""

from __future__ import annotations

import ctypes
import json
import math
import sys
import traceback
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, simpledialog

from PIL import ImageDraw, ImageGrab

import plan2030_app as pa
import utdelning_core

BILDER = Path(sys.argv[1] if len(sys.argv) > 1 else "manual_bilder")
BILDER.mkdir(parents=True, exist_ok=True)
LOGG = BILDER / "logg.txt"
LOGG.write_text("", encoding="utf-8")
MARKERINGAR: dict[str, list[list[int]]] = {}


def logga(*delar: object) -> None:
    with LOGG.open("a", encoding="utf-8") as f:
        f.write(" ".join(str(d) for d in delar) + "\n")


messagebox.showinfo = lambda *a, **k: logga("showinfo", a)
messagebox.showwarning = lambda *a, **k: logga("showwarning", a)
messagebox.showerror = lambda *a, **k: logga("showerror", a)
messagebox.askyesno = lambda *a, **k: (logga("askyesno", a), True)[1]
simpledialog.askstring = lambda *a, **k: None


def _ruta(top) -> tuple[int, int, int, int]:
    hwnd = int(top.wm_frame(), 16)
    rect = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)
    ) != 0:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def overst(*fonster) -> None:
    for f in fonster:
        try:
            f.deiconify()
            f.attributes("-topmost", True)
            f.lift()
            f.update()
        except Exception:
            pass


def bild(namn: str, fonster, markera=(), extra=()) -> None:
    """Sparar fönstret (plus ev. dialoger ovanpå) med röda ramar runt `markera`."""
    overst(fonster, *extra)
    fonster.update()
    x1, y1, x2, y2 = _ruta(fonster)
    img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True).convert("RGB")
    rita = ImageDraw.Draw(img)
    rutor = []
    m = 5
    geo = []
    for nr, w in enumerate(markera, 1):
        if w is None:
            continue
        try:
            geo.append((nr, w.winfo_rootx() - x1, w.winfo_rooty() - y1, w.winfo_width(), w.winfo_height()))
        except Exception:
            continue
    ramar = [(wx - m, wy - m, wx + ww + m, wy + wh + m) for _, wx, wy, ww, wh in geo]
    for i, (nr, wx, wy, ww, wh) in enumerate(geo):
        rutor.append([wx - m - 32, wy - m - 16, wx + ww + m + 4, wy + wh + m + 4])
        rita.rounded_rectangle(ramar[i], radius=8, outline="#E0301E", width=4)
        if len(markera) > 1:
            if ww > 150 and wh > 60:
                cx, cy = wx - m, wy - m
            else:
                cx, cy = wx - m - 15, wy + wh // 2
                andra = [r for j, r in enumerate(ramar) if j != i]
                if any(a - 14 <= cx <= c + 14 and b <= cy <= d for a, b, c, d in andra):
                    cx = wx + ww + m + 15
            cx = max(cx, 15)
            rita.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill="#E0301E")
            rita.text((cx, cy), str(nr), fill="white", anchor="mm", font_size=17)
    img.save(BILDER / f"{namn}.png")
    MARKERINGAR[namn] = rutor
    (BILDER / "markeringar.json").write_text(json.dumps(MARKERINGAR, indent=1), encoding="utf-8")
    logga("bild", namn, img.size)


def hitta(rot, text: str):
    """Första widget med exakt den texten."""
    stack = [rot]
    while stack:
        w = stack.pop(0)
        try:
            if str(w.cget("text")) == text:
                return w
        except Exception:
            pass
        stack.extend(w.winfo_children())
    return None


def hitta_typ(rot, klass):
    stack = [rot]
    while stack:
        w = stack.pop(0)
        if isinstance(w, klass):
            return w
        stack.extend(w.winfo_children())
    return None


def senaste_dialog(app, klass):
    hittade = [w for w in _alla(app) if isinstance(w, klass)]
    return hittade[-1] if hittade else None


def _alla(rot):
    ut, stack = [], [rot]
    while stack:
        w = stack.pop(0)
        ut.append(w)
        stack.extend(w.winfo_children())
    return ut


def rulla_ner(widget) -> None:
    w = widget
    while w is not None and w.winfo_class() != "Canvas":
        w = w.master
    if w is not None:
        w.yview_moveto(1.0)


def satt(entry, text) -> None:
    entry.delete(0, "end")
    entry.insert(0, str(text))


def steg(app):
    from utdelning_panel import UtdelningApp
    from aktiehandel_panel import AktieHandelApp

    # Start: en plan finns redan, översikten visas.
    app._skapa_plan_fran_dialog({"plan_namn": "Min plan", "antal": 2, "namn": ["Anna", "Erik"]})
    app._visa_startval()
    yield 1500
    bild("01_oversikt_start", app, [hitta(app, "Ny plan")])

    # Ny plan
    app.after(10, app._ny_plan)
    yield 600
    d = senaste_dialog(app, pa.NyPlanDialog)
    d.namn.set("Exempelplan")
    d.p1.set("Anna")
    d.p2.set("Erik")
    yield 200
    bild("02_ny_plan", d, [hitta(d, "Skapa plan")])
    d._ok()
    yield 800
    app.update()
    bild("03_ny_plan_oversikt", app, [hitta(app, "Konton")])

    # Konton
    app._oppna_konton()
    yield 900
    kf = app._konto_fonster
    bild("04_konton_start", kf, [hitta(kf, "+  Lägg till konto")])

    kf.after(10, kf._nytt)
    yield 600
    d = senaste_dialog(kf, pa.NyttKontoDialog)
    d.namn.set("Lönekonto")
    d.sparat.set("15000")
    d.ranta.set("0")
    d.skatt.set("30")
    yield 200
    bild("05_nytt_konto", d, [hitta(d, "Lägg till")])
    d._ok()
    yield 800
    bild("06_lonekonto", kf, [hitta(kf, "+ Insättning"), hitta(kf, "− Uttag"), hitta(kf, "Överför")])

    kf.after(10, kf._nytt)
    yield 600
    d = senaste_dialog(kf, pa.NyttKontoDialog)
    d.namn.set("Sparkonto")
    d.sparat.set("100000")
    d.ranta.set("3.5")
    d.skatt.set("30")
    d._ok()
    yield 800
    kf.overskott_var.set(True)
    kf._spara_val()
    yield 800
    bild("06b_kontoval", kf, [
        hitta(kf, "Ränta varje månad (ränta på ränta). Annars kommer räntan i januari året efter."),
        hitta(kf, "Framtida överskott och underskott räknas på det här kontot"),
        getattr(kf, "overskott_lbl", None),
    ])

    kf.after(10, lambda: kf._rorelse("insattning"))
    yield 600
    d = senaste_dialog(kf, pa.RorelseDialog)
    d.ar.set("2026")
    d.manad.set("dec")
    d.dag.set("25")
    d.belopp.set("5000")
    d.anteckning.set("Julbonus")
    yield 200
    bild("07_insattning", d, [hitta(d, "Spara")])
    d._ok()
    yield 800
    bild("08_sparkonto_med_insattning", kf, [hitta(kf, "Insättningar och uttag") or None])

    # Överföring till Nordnet och Avanza
    nordnet = app._aktiekonto_index()
    avanza = app._aktier_index()
    kf.after(10, kf._overfor)
    yield 600
    d = senaste_dialog(kf, pa.OverforDialog)
    d.till.set(pa.konto_visningsnamn(app.konton, nordnet + 1))
    d.belopp.set("40000")
    d.anteckning.set("Till aktier")
    yield 200
    bild("09_overfor", d, [hitta(d, "Överför")])
    d._ok()
    yield 600
    kf.after(10, kf._overfor)
    yield 600
    d = senaste_dialog(kf, pa.OverforDialog)
    d.till.set(pa.konto_visningsnamn(app.konton, avanza + 1))
    d.belopp.set("10000")
    d._ok()
    yield 800

    # Nordnet
    kf._valj(nordnet)
    yield 1200
    panel = hitta_typ(kf, UtdelningApp)
    bild("10_nordnet_start", kf, [panel.kontant_label.master, panel.cash_label.master])

    kf.after(10, panel._gor_insattning)
    yield 600
    d = senaste_dialog(kf, pa.RorelseDialog)
    d.belopp.set("5000")
    d.anteckning.set("Egen insättning")
    yield 200
    bild("11_nordnet_insattning", d, [hitta(d, "Spara")])
    d._ok()
    yield 1000
    panel = hitta_typ(kf, UtdelningApp)

    satt(panel.query, "Telia")
    panel.search_now()
    for _ in range(60):
        if panel.results.size():
            break
        yield 300
    yield 300
    bild("12_sok_aktie", kf, [panel.query, panel.results])
    traffar = [h["symbol"] for h in panel.hits]
    i = traffar.index("TELIA.ST") if "TELIA.ST" in traffar else 0
    panel.results.selection_clear(0, "end")
    panel.results.selection_set(i)
    panel.pick_hit(None)
    satt(panel.shares, "800")
    panel.price.delete(0, "end")
    yield 300
    bild("13_kop_aktie", kf, [panel.chosen_label, panel.shares, panel.add_btn])
    panel.add_stock()
    for _ in range(80):
        if panel.tree.get_children():
            break
        yield 300
    yield 1200
    bild("14_aktie_kopt", kf, [panel.tree, panel.kontant_label.master])

    pris = float(utdelning_core.load()["stocks"][0].get("price") or 40)
    utd = 500
    satt(panel.cash, utd)
    varden = list(panel.cash_source.cget("values"))
    if varden:
        panel.cash_source.set(varden[-1])
    yield 300
    bild("15_utdelning", kf, [panel.cash, panel.cash_source, hitta(panel.cash.master, "Lägg till")])
    panel.add_cash()
    yield 800
    bild("16_utdelning_inlagd", kf, [panel.cash_label.master])

    pott = float(utdelning_core.load().get("cash") or 0)
    antal = max(1, math.floor(pott / (pris * 1.0025 + 0.01)))
    satt(panel.free_shares, antal)
    panel.free_price.delete(0, "end")
    yield 300
    bild("17_gratisaktier", kf, [panel.free_shares, hitta(panel, "Lägg till gratis")])
    panel.buy("dividend")
    yield 1000
    bild("18_gratis_kopta", kf, [panel.tree, panel.cash_label.master])

    satt(panel.sell_shares, 300)
    satt(panel.sell_price, f"{pris * 1.10:.2f}".replace(".", ","))
    rulla_ner(panel.sell_shares)
    yield 300
    bild("19_salj", kf, [panel.sell_shares, panel.sell_price, hitta(panel, "Sälj betalda")])
    panel.sell("paid")
    yield 1000
    bild("20_salt", kf, [panel.tree, panel.cash_label.master, panel.kontant_label.master])

    panel.show_transactions()
    yield 900
    bild("21_transaktioner", panel._trans_window)
    panel._trans_window.destroy()
    panel._trans_window = None
    yield 300

    # Avanza
    kf._valj(avanza)
    yield 1200
    av = hitta_typ(kf, AktieHandelApp)
    satt(av.query, "Volvo")
    av.search_now()
    for _ in range(60):
        if av.results.size():
            break
        yield 300
    traffar = [h["symbol"] for h in av.hits]
    i = traffar.index("VOLV-B.ST") if "VOLV-B.ST" in traffar else 0
    av.results.selection_clear(0, "end")
    av.results.selection_set(i)
    av.pick_hit(None)
    satt(av.shares, "25")
    av.price.delete(0, "end")
    av.add_stock()
    for _ in range(80):
        if av.tree.get_children():
            break
        yield 300
    yield 1200
    bild("22_avanza", kf, [av.tree, av.plus_value.master])

    kf._valj(0)
    yield 600
    kf._tillbaka()
    yield 1000
    app._uppdatera_oversikt()
    yield 500
    bild("23_oversikt_klar", app, [app.datum_valjare, hitta(app, "Uppdatera alla kurser"), hitta(app, "Spara PDF för valt datum")])

    # Inkomster
    app._oppna_inkomster()
    yield 800
    iw = app._inkomst_fonster
    iw._ny_period()
    app.perioder[-1].update({
        "ar_fran": "2027", "manad_fran": "jan", "ar_till": "2029", "manad_till": "dec",
        "person1": "24000", "person2": "19000", "behov": "36000", "anteckning": "Båda jobbar",
    })
    iw._ny_period()
    app.perioder[-1].update({
        "ar_fran": "2030", "manad_fran": "jan", "ar_till": "2040", "manad_till": "dec",
        "person1": "16000", "person2": "14000", "behov": "33000", "anteckning": "Pension",
    })
    iw._rita_perioder()
    yield 600
    bild("24_inkomster", iw, [hitta(iw, "+  Lägg till period")])
    iw._tillbaka()
    yield 500

    app._oppna_handelser()
    yield 900
    hw = app._handelser_fonster
    bild("25_handelser", hw)
    hw._tillbaka() if hasattr(hw, "_tillbaka") else hw.destroy()
    yield 500

    app.visnings_ar, app.visnings_manad, app.visnings_dag = 2031, 1, 1
    app.datum_valjare.satt(2031, 1, 1)
    app._uppdatera_oversikt()
    yield 900
    ranta = next((w for w in _alla(app) if str(getattr(w, "cget", lambda _k: "")("text") if isinstance(w, pa.tk.Label) else "").startswith("Samlad ränta")), None)
    bild("23b_framtid", app, [app.datum_valjare, ranta])
    app._visa_idag()
    yield 600

    app._uppdatera_oversikt()
    yield 500
    bild("26_hjalp", app, [hitta(app, "Inställningar"), hitta(app, "Hjälp")])

    app._plan_mapp = lambda: r"C:\Users\Anna\Documents\Spar- och Pensionsplan"
    app.after(10, app._installningar)
    yield 700
    inst = [w for w in _alla(app) if isinstance(w, pa.tk.Toplevel) and w.title() == "Inställningar"][-1]
    bild("27_installningar", inst, [hitta(inst, "Välj mapp…"), hitta_typ(inst, pa.tk.Checkbutton)])
    inst.destroy()
    logga("KLART")


def main() -> None:
    app = pa.PensionsplanApp()
    app._visa_paminnelser = lambda *a, **k: None
    app._oppna_manual = lambda *a, **k: logga("manual öppnas")

    gen = steg(app)

    def nasta() -> None:
        try:
            vant = next(gen)
        except StopIteration:
            app.after(500, app._stang)
            return
        except Exception:
            logga("FEL", traceback.format_exc())
            app.after(500, app._stang)
            return
        app.after(int(vant), nasta)

    app.after(300, nasta)
    app.mainloop()


if __name__ == "__main__":
    main()
