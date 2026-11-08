"""Spelar in instruktionsfilmen med exempelplanen.

Körs från en kopia av programmet (egen tom planer-mapp), aldrig från den installerade:
    python film_inspelning.py <utfil.mp4>
Kräver: pip install imageio-ffmpeg
"""

from __future__ import annotations

import ctypes
import math
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, simpledialog

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageGrab

import plan2030_app as pa
import utdelning_core

UT = Path(sys.argv[1] if len(sys.argv) > 1 else "instruktionsfilm.mp4")
LOGG = UT.with_suffix(".logg.txt")
LOGG.write_text("", encoding="utf-8")
FPS = 15
B, H = 1600, 900
UT_B, UT_H = 1920, 1080

MORK = (23, 53, 64)
ACCENT = (42, 157, 143)
LJUS = (159, 227, 216)
ROD = (224, 48, 30)
TYPSNITT = Path(r"C:\Windows\Fonts")


def typsnitt(namn: str, storlek: int):
    return ImageFont.truetype(str(TYPSNITT / namn), storlek)


def logga(*delar: object) -> None:
    with LOGG.open("a", encoding="utf-8") as f:
        f.write(" ".join(str(d) for d in delar) + "\n")


messagebox.showinfo = lambda *a, **k: logga("showinfo", a)
messagebox.showwarning = lambda *a, **k: logga("showwarning", a)
messagebox.showerror = lambda *a, **k: logga("showerror", a)
messagebox.askyesno = lambda *a, **k: (logga("askyesno", a), True)[1]
simpledialog.askstring = lambda *a, **k: None
pa.KontoFonster._bredda_borsfonster = lambda self: None


def _ruta(top) -> tuple[int, int, int, int]:
    hwnd = int(top.wm_frame(), 16)
    rect = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)
    ) != 0:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def radbryt(rita: ImageDraw.ImageDraw, text: str, font, bredd: int) -> list[str]:
    rader, rad = [], ""
    for ord_ in text.split():
        prov = f"{rad} {ord_}".strip()
        if rita.textlength(prov, font=font) <= bredd:
            rad = prov
        else:
            rader.append(rad)
            rad = ord_
    if rad:
        rader.append(rad)
    return rader


class Inspelare:
    def __init__(self) -> None:
        self.ruta = (0, 0, B, H)
        self.text = ""
        self.rutor: list[tuple[int, int, int, int]] = []
        self.igang = False
        self._trad: threading.Thread | None = None
        self.font = typsnitt("seguisb.ttf", 30)
        self.proc = subprocess.Popen(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{B}x{H}", "-r", str(FPS), "-i", "-",
                "-vf", f"scale={UT_B}:{UT_H}:flags=lanczos",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(UT),
            ],
            stdin=subprocess.PIPE,
        )

    def skriv(self, img: Image.Image, antal: int = 1) -> None:
        data = img.tobytes()
        for _ in range(antal):
            self.proc.stdin.write(data)

    def kort(self, rader: list[tuple[str, str, int, tuple]], sek: float, ikon: Path | None = None) -> None:
        img = Image.new("RGB", (B, H), MORK)
        rita = ImageDraw.Draw(img)
        for i in range(H):
            t = i / H
            rita.line([(0, i), (B, i)], fill=tuple(int(MORK[k] * (1 - t * 0.35) + 10 * t) for k in range(3)))
        hojder = [typsnitt(f, s).getbbox(txt)[3] + 26 for txt, f, s, _ in rader]
        y = (H - sum(hojder) - (150 if ikon else 0)) // 2
        if ikon and ikon.exists():
            bild = Image.open(ikon).convert("RGBA").resize((110, 110))
            img.paste(bild, ((B - 110) // 2, y), bild)
            y += 150
        for (txt, f, s, farg), h in zip(rader, hojder):
            rita.text((B // 2, y), txt, font=typsnitt(f, s), fill=farg, anchor="mt")
            y += h
        rita.rectangle((B // 2 - 60, H - 90, B // 2 + 60, H - 86), fill=ACCENT)
        self.skriv(img, int(sek * FPS))

    def _rita(self, img: Image.Image) -> None:
        rita = ImageDraw.Draw(img, "RGBA")
        for x1, y1, x2, y2 in self.rutor:
            rita.rounded_rectangle((x1, y1, x2, y2), radius=10, outline=ROD + (255,), width=5)
        if not self.text:
            return
        rader = radbryt(rita, self.text, self.font, 1300)
        rad_h = 42
        band_h = rad_h * len(rader) + 34
        bredast = max(rita.textlength(r, font=self.font) for r in rader)
        x1 = (B - bredast) // 2 - 34
        x2 = (B + bredast) // 2 + 34
        y1 = H - band_h - 34
        if any(ry2 > y1 - 10 and ry1 < H for _, ry1, _, ry2 in self.rutor):
            y1 = 46
        rita.rounded_rectangle((x1, y1, x2, y1 + band_h), radius=16, fill=MORK + (236,), outline=ACCENT + (255,), width=3)
        for i, rad in enumerate(rader):
            rita.text((B // 2, y1 + 17 + i * rad_h), rad, font=self.font, fill=(255, 255, 255, 255), anchor="mt")

    def _loop(self) -> None:
        start = time.perf_counter()
        n = 0
        while self.igang:
            img = ImageGrab.grab(bbox=self.ruta, all_screens=True).convert("RGB")
            if img.size != (B, H):
                img = img.resize((B, H))
            self._rita(img)
            mal = int((time.perf_counter() - start) * FPS) + 1
            self.skriv(img, max(1, mal - n))
            n = max(n + 1, mal)
            vila = start + n / FPS - time.perf_counter()
            if vila > 0:
                time.sleep(vila)

    def starta(self) -> None:
        self.igang = True
        self._trad = threading.Thread(target=self._loop, daemon=True)
        self._trad.start()

    def stoppa(self) -> None:
        self.igang = False
        if self._trad:
            self._trad.join()

    def avsluta(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


REC = Inspelare()
GEOM = ""


def placera(fonster) -> None:
    fonster.geometry(GEOM)
    overst(fonster)


def overst(*fonster) -> None:
    for f in fonster:
        try:
            f.deiconify()
            f.attributes("-topmost", True)
            f.lift()
            f.update()
        except Exception:
            pass


def ruta_for(w) -> tuple[int, int, int, int]:
    x = w.winfo_rootx() - REC.ruta[0]
    y = w.winfo_rooty() - REC.ruta[1]
    return (x - 7, y - 7, x + w.winfo_width() + 7, y + w.winfo_height() + 7)


def visa(text: str | None = None, widgets=(), tid: int = 2500):
    if text is not None:
        REC.text = text
    rutor = []
    for w in widgets:
        try:
            if w is not None:
                rutor.append(ruta_for(w))
        except Exception:
            pass
    REC.rutor = rutor
    yield tid


def rensa() -> None:
    REC.rutor = []


def skriv_var(var, text, takt: int = 75):
    text = str(text)
    for i in range(1, len(text) + 1):
        var.set(text[:i])
        yield takt


def skriv_entry(entry, text, takt: int = 75):
    entry.delete(0, "end")
    for tecken in str(text):
        entry.insert("end", tecken)
        yield takt


def hitta(rot, text: str):
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


def _alla(rot):
    ut, stack = [], [rot]
    while stack:
        w = stack.pop(0)
        ut.append(w)
        stack.extend(w.winfo_children())
    return ut


def hitta_typ(rot, klass):
    return next((w for w in _alla(rot) if isinstance(w, klass)), None)


def senaste_dialog(app, klass):
    hittade = [w for w in _alla(app) if isinstance(w, klass)]
    return hittade[-1] if hittade else None


def rulla_ner(widget) -> None:
    w = widget
    while w is not None and w.winfo_class() != "Canvas":
        w = w.master
    if w is not None:
        w.yview_moveto(1.0)


def dialog(fonster, klass, oppna):
    fonster.after(10, oppna)
    yield 500
    d = senaste_dialog(fonster, klass)
    overst(d)
    yield 300
    return d


def steg(app):
    global GEOM
    from utdelning_panel import UtdelningApp
    from aktiehandel_panel import AktieHandelApp

    app._skapa_plan_fran_dialog({"plan_namn": "Min plan", "antal": 2, "namn": ["Anna", "Erik"]})
    app._visa_startval()
    yield 800
    x = (app.winfo_screenwidth() - B) // 2
    y = max(0, (app.winfo_screenheight() - 40 - H) // 2)
    hk = H - 32
    for _ in range(3):
        GEOM = f"{B}x{hk}+{x}+{y}"
        app.geometry(GEOM)
        overst(app)
        yield 300
        x1, y1, x2, y2 = _ruta(app)
        if y2 - y1 == H:
            break
        hk += H - (y2 - y1)
    x1, y1, x2, y2 = _ruta(app)
    REC.ruta = (x1 + (x2 - x1 - B) // 2, y1, x1 + (x2 - x1 - B) // 2 + B, y1 + H)
    logga("ruta", REC.ruta, GEOM)

    REC.kort([
        ("Spar- och Pensionsplan", "segoeuib.ttf", 76, (255, 255, 255)),
        ("Så funkar det", "seguisb.ttf", 44, LJUS),
        ("Gratis program för sparande, pension och aktier", "segoeui.ttf", 32, (207, 223, 227)),
    ], 4.5, Path("pension.ico"))
    REC.starta()

    yield from visa("Så här ser programmet ut när du startar det första gången.", tid=3500)
    yield from visa("Börja med att skapa en plan för dig, eller för er två.", [hitta(app, "Ny plan")], 3000)
    d = yield from dialog(app, pa.NyPlanDialog, app._ny_plan)
    rensa()
    yield from skriv_var(d.namn, "Exempelplan")
    yield 300
    d.p1.set("")
    yield from skriv_var(d.p1, "Anna")
    d.p2.set("")
    yield from skriv_var(d.p2, "Erik")
    yield from visa(None, [hitta(d, "Skapa plan")], 1500)
    d._ok()
    rensa()
    yield 800
    placera(app)

    yield from visa("Under Konton lägger du in dina konton.", [hitta(app, "Konton")], 3000)
    app._oppna_konton()
    yield 400
    kf = app._konto_fonster
    placera(kf)
    yield from visa("Från början finns några konton som exempel. Lägg till dina egna med knappen.", [hitta(kf, "+  Lägg till konto")], 3500)

    d = yield from dialog(kf, pa.NyttKontoDialog, kf._nytt)
    rensa()
    REC.text = "Skriv kontots namn, vad som finns på det i dag, räntan och skatten på räntan."
    d.namn.set("")
    yield from skriv_var(d.namn, "Lönekonto")
    d.sparat.set("")
    yield from skriv_var(d.sparat, "15000")
    d.ranta.set("")
    yield from skriv_var(d.ranta, "0")
    d.skatt.set("")
    yield from skriv_var(d.skatt, "30")
    yield from visa(None, [hitta(d, "Lägg till")], 1500)
    d._ok()
    rensa()
    yield 1500

    d = yield from dialog(kf, pa.NyttKontoDialog, kf._nytt)
    REC.text = "Ett sparkonto med 100 000 kr och 3,5 % ränta."
    d.namn.set("")
    yield from skriv_var(d.namn, "Sparkonto")
    d.sparat.set("")
    yield from skriv_var(d.sparat, "100000")
    d.ranta.set("")
    yield from skriv_var(d.ranta, "3.5")
    d.skatt.set("")
    yield from skriv_var(d.skatt, "30")
    yield 600
    d._ok()
    yield 1200
    kryss = hitta(kf, "Framtida överskott och underskott räknas på det här kontot")
    yield from visa("Välj vilket konto som ska få det som blir över, eller saknas, varje månad.", [kryss], 3000)
    kf.overskott_var.set(True)
    kf._spara_val()
    yield 1500
    yield from visa("Kryssa i om räntan kommer varje månad. Annars kommer den en gång om året.",
                    [hitta(kf, "Ränta varje månad (ränta på ränta). Annars kommer räntan i januari året efter.")], 3500)

    yield from visa("Planerade insättningar och uttag läggs in i förväg, till exempel en julbonus.", [hitta(kf, "+ Insättning")], 3000)
    d = yield from dialog(kf, pa.RorelseDialog, lambda: kf._rorelse("insattning"))
    rensa()
    d.ar.set("2026")
    d.manad.set("dec")
    d.dag.set("25")
    d.belopp.set("")
    yield from skriv_var(d.belopp, "5000")
    d.anteckning.set("")
    yield from skriv_var(d.anteckning, "Julbonus")
    yield from visa(None, [hitta(d, "Spara")], 1300)
    d._ok()
    rensa()
    yield 2000

    nordnet = app._aktiekonto_index()
    avanza = app._aktier_index()
    yield from visa("Med Överför flyttar du pengar mellan kontona, till exempel till aktiekontot.", [hitta(kf, "Överför")], 3000)
    d = yield from dialog(kf, pa.OverforDialog, kf._overfor)
    rensa()
    d.till.set(pa.konto_visningsnamn(app.konton, nordnet + 1))
    yield 500
    d.belopp.set("")
    yield from skriv_var(d.belopp, "40000")
    d.anteckning.set("")
    yield from skriv_var(d.anteckning, "Till aktier")
    yield 700
    d._ok()
    yield 600
    kf.after(10, kf._overfor)
    yield 500
    d = senaste_dialog(kf, pa.OverforDialog)
    d.till.set(pa.konto_visningsnamn(app.konton, avanza + 1))
    d.belopp.set("10000")
    d._ok()
    yield 800

    kf._valj(nordnet)
    yield 400
    placera(kf)
    yield 900
    panel = hitta_typ(kf, UtdelningApp)
    namnruta = hitta(kf, "Kontots namn")
    yield from visa("Nordnet är ett utdelningskonto. Namnet kan du ändra till din egen bank.",
                    [namnruta.master if namnruta else None], 4000)
    REC.text = "Sök upp en aktie. Kursen hämtas från internet."
    yield from visa(None, [panel.query], 800)
    yield from skriv_entry(panel.query, "Telia", 110)
    panel.search_now()
    for _ in range(60):
        if panel.results.size():
            break
        yield 300
    yield from visa(None, [panel.results], 1800)
    traffar = [h["symbol"] for h in panel.hits]
    i = traffar.index("TELIA.ST") if "TELIA.ST" in traffar else 0
    panel.results.selection_clear(0, "end")
    panel.results.selection_set(i)
    panel.pick_hit(None)
    yield 800
    REC.text = "Skriv hur många aktier du köpt. Lämnar du kursen tom används dagens kurs."
    yield from visa(None, [panel.shares], 600)
    yield from skriv_entry(panel.shares, "800", 150)
    panel.price.delete(0, "end")
    yield from visa(None, [panel.add_btn], 1800)
    panel.add_stock()
    rensa()
    for _ in range(80):
        if panel.tree.get_children():
            break
        yield 300
    yield 800
    yield from visa("Aktien hamnar i listan. Till höger syns avkastningen på det du betalat.", [panel.tree], 4500)

    pris = float(utdelning_core.load()["stocks"][0].get("price") or 40)
    REC.text = "När utdelningen kommer skriver du in den här."
    yield from visa(None, [panel.cash], 800)
    yield from skriv_entry(panel.cash, "500", 150)
    varden = list(panel.cash_source.cget("values"))
    if varden:
        panel.cash_source.set(varden[-1])
    yield from visa(None, [panel.cash, panel.cash_source, hitta(panel.cash.master, "Lägg till")], 2200)
    panel.add_cash()
    rensa()
    yield 800
    yield from visa("Utdelningen samlas i rutan Utdelning och vinst.", [panel.cash_label.master], 3500)

    pott = float(utdelning_core.load().get("cash") or 0)
    antal = max(1, math.floor(pott / (pris * 1.0025 + 0.01)))
    REC.text = "För utdelningen kan du köpa gratisaktier. De höjer inte det du har betalat."
    yield from visa(None, [panel.free_shares], 800)
    yield from skriv_entry(panel.free_shares, antal, 150)
    panel.free_price.delete(0, "end")
    yield from visa(None, [panel.free_shares, hitta(panel, "Lägg till gratis")], 2500)
    panel.buy("dividend")
    rensa()
    yield 1200
    yield from visa(None, [panel.tree], 2500)

    rulla_ner(panel.sell_shares)
    yield 500
    REC.text = "Säljer du aktier räknas resultatet ut automatiskt."
    yield from visa(None, [panel.sell_shares], 600)
    yield from skriv_entry(panel.sell_shares, "300", 150)
    yield from skriv_entry(panel.sell_price, f"{pris * 1.10:.2f}".replace(".", ","), 110)
    yield from visa(None, [panel.sell_shares, panel.sell_price, hitta(panel, "Sälj betalda")], 2200)
    panel.sell("paid")
    rensa()
    yield 1200
    yield from visa("Vinsten hamnar i Utdelning och vinst, och Resultat sålda visas överst.", [panel.cash_label.master], 4500)
    REC.text = "Nu byter vi till Avanza-kontot."
    rensa()

    kf._valj(avanza)
    yield 400
    placera(kf)
    for _ in range(40):
        av = hitta_typ(kf, AktieHandelApp)
        if av is not None and av.winfo_ismapped():
            break
        yield 250
    yield 1500
    yield from visa("Avanza är ett kursvinstkonto. Det visar plus och minus mot det du har betalat.", [], 3500)
    yield from visa(None, [av.query], 600)
    yield from skriv_entry(av.query, "Volvo", 110)
    av.search_now()
    for _ in range(60):
        if av.results.size():
            break
        yield 300
    yield 900
    traffar = [h["symbol"] for h in av.hits]
    i = traffar.index("VOLV-B.ST") if "VOLV-B.ST" in traffar else 0
    av.results.selection_clear(0, "end")
    av.results.selection_set(i)
    av.pick_hit(None)
    yield 600
    yield from skriv_entry(av.shares, "25", 150)
    av.price.delete(0, "end")
    yield 500
    av.add_stock()
    for _ in range(80):
        if av.tree.get_children():
            break
        yield 300
    yield 800
    yield from visa(None, [av.tree, av.plus_value.master], 4000)
    rensa()

    kf._valj(0)
    yield 500
    REC.text = "Tillbaka till översikten."
    yield from visa(None, [hitta(kf, "←  Översikt")], 2000)
    kf._tillbaka()
    yield 500
    app._uppdatera_oversikt()
    placera(app)
    yield from visa("Översikten visar vad du har på alla konton i dag.", [], 4000)

    yield from visa("Under Inkomster lägger du in lön, pension och vad ni behöver per månad.", [hitta(app, "Inkomster")], 3500)
    app._oppna_inkomster()
    yield 400
    iw = app._inkomst_fonster
    placera(iw)
    yield 600
    iw._ny_period()
    app.perioder[-1].update({
        "ar_fran": "2027", "manad_fran": "jan", "ar_till": "2029", "manad_till": "dec",
        "person1": "24000", "person2": "19000", "behov": "36000", "anteckning": "Båda jobbar",
    })
    iw._rita_perioder()
    yield 1500
    iw._ny_period()
    app.perioder[-1].update({
        "ar_fran": "2030", "manad_fran": "jan", "ar_till": "2040", "manad_till": "dec",
        "person1": "16000", "person2": "14000", "behov": "33000", "anteckning": "Pension",
    })
    iw._rita_perioder()
    yield 600
    yield from visa("Programmet visar direkt om det blir pengar över eller om det saknas varje månad.", [], 4500)
    iw._tillbaka()
    yield 500
    placera(app)

    yield from visa("Snurra på hjulen för att se hur det ser ut längre fram.", [app.datum_valjare], 3000)
    dv = app.datum_valjare
    for ar in range(app.visnings_ar + 1, 2032):
        app.visnings_ar, app.visnings_manad, app.visnings_dag = ar, 1, 1
        dv.ar_hjul.satt_index(dv.ar_varden.index(ar), animera=True, tyst=True)
        if ar == app.visnings_ar and dv.manad != 1:
            dv.manad_hjul.satt_index(0, animera=True, tyst=True)
        dv.ar, dv.manad, dv.dag = ar, 1, 1
        dv._synka_dagar()
        yield 450
        app._uppdatera_oversikt()
        yield 600
    yield from visa("I framtiden räknas ränta, överskott och underskott med.", [], 4500)
    yield from visa("Spara en PDF med alla konton för det datum du har valt.", [hitta(app, "Spara PDF för valt datum")], 3500)
    app._visa_idag()
    yield 300
    app._uppdatera_oversikt()
    yield from visa("På dagens datum visas det du faktiskt har just nu.", [], 3500)
    yield from visa("Manualen finns alltid under Hjälp.", [hitta(app, "Hjälp")], 3500)
    REC.text = ""
    rensa()
    yield 600
    REC.stoppa()
    REC.kort([
        ("Ladda ner gratis", "segoeuib.ttf", 70, (255, 255, 255)),
        ("magnusbaa.github.io/spar-och-pensionsplan", "seguisb.ttf", 44, LJUS),
        ("För Windows 10 och 11", "segoeui.ttf", 32, (207, 223, 227)),
        (" ", "segoeui.ttf", 20, (0, 0, 0)),
        ("Gillar du programmet? Swisha gärna 100 kr till 070-091 33 10", "segoeui.ttf", 32, (207, 223, 227)),
    ], 7, Path("pension.ico"))
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
            REC.avsluta()
            app.after(300, app._stang)
            return
        except Exception:
            logga("FEL", traceback.format_exc())
            REC.stoppa()
            REC.avsluta()
            app.after(300, app._stang)
            return
        app.after(int(vant), nasta)

    app.after(300, nasta)
    app.mainloop()


if __name__ == "__main__":
    main()
