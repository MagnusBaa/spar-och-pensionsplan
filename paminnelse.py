"""Påminnelser en vecka och en dag före insättning, uttag och överföring."""

from __future__ import annotations

import calendar
import json
from datetime import date
from pathlib import Path

from plan_engine import MANAD_NAMN_TILL_NUMMER, MANADER, formatera_kr
from plan_save import hamta_aktiv_plan, ladda_data, plan_fil, planer_katalog, uppgradera_plan_data

_VISADE_FIL = "_paminnelser.json"


def _manad(post: dict) -> int:
    raw = post.get("manad", 1)
    if isinstance(raw, int) and 1 <= raw <= 12:
        return raw
    text = str(raw).strip()
    if text in MANAD_NAMN_TILL_NUMMER:
        return MANAD_NAMN_TILL_NUMMER[text]
    try:
        nr = int(str(text).split()[0])
        return nr if 1 <= nr <= 12 else 1
    except ValueError:
        return 1


def _dag(ar: int, manad: int, post: dict) -> int:
    try:
        dag = int(str(post.get("dag", 1)).strip())
    except ValueError:
        dag = 1
    return min(max(dag, 1), calendar.monthrange(ar, manad)[1])


def _konto_namn(konton: list, nr: int) -> str:
    i = nr - 1
    if 0 <= i < len(konton) and isinstance(konton[i], dict):
        namn = str(konton[i].get("namn") or "").strip()
        if namn:
            return namn
    return f"Konto {nr}"


def _datum_text(ar: int, manad: int, dag: int) -> str:
    return f"{dag} {MANADER[manad - 1]} {ar}"


def samla_paminnelser(data: dict, idag: date | None = None) -> list[dict]:
    """Händelser som infaller om 7 dagar eller i morgon."""
    idag = idag or date.today()
    g = data.get("gemensamt") or {}
    konton = g.get("konton") or []
    traffar: list[dict] = []

    def lagg(nar: date, nyckel: str, rubrik: str, text: str, dagar: int) -> None:
        traffar.append({
            "nyckel": f"{idag.isoformat()}|{nyckel}|{dagar}",
            "dagar": dagar,
            "rubrik": rubrik,
            "text": text,
            "nar": nar,
        })

    for post in g.get("konto_rorelser") or []:
        if not isinstance(post, dict):
            continue
        try:
            ar = int(post.get("ar"))
            belopp = int(post.get("belopp") or 0)
            konto = int(post.get("konto") or 0)
        except (TypeError, ValueError):
            continue
        manad = _manad(post)
        dag = _dag(ar, manad, post)
        try:
            nar = date(ar, manad, dag)
        except ValueError:
            continue
        kvar = (nar - idag).days
        if kvar not in (1, 7):
            continue
        typ = str(post.get("typ") or "")
        namn = _konto_namn(konton, konto)
        anteckning = str(post.get("anteckning") or "").strip()
        when = "I morgon" if kvar == 1 else "Om en vecka"
        if typ == "insattning":
            rad = f"{when}, {_datum_text(ar, manad, dag)}: insättning {formatera_kr(belopp)} på {namn}."
        else:
            rad = (
                f"{when}, {_datum_text(ar, manad, dag)}: uttag {formatera_kr(belopp)} från {namn}. "
                "För över pengar så det finns på kontot."
            )
        if anteckning:
            rad = f"{rad}\n{anteckning}"
        lagg(nar, f"rorelse|{ar}|{manad}|{dag}|{konto}|{belopp}|{typ}", when, rad, kvar)

    for post in g.get("overforingar") or []:
        if not isinstance(post, dict):
            continue
        try:
            ar = int(str(post.get("ar")).strip())
            belopp = int(str(post.get("belopp") or "0").replace(" ", ""))
            fran = int(str(post.get("fran_konto") or "0"))
            till = int(str(post.get("till_konto") or "0"))
        except (TypeError, ValueError):
            continue
        manad = _manad(post)
        dag = _dag(ar, manad, post)
        try:
            nar = date(ar, manad, dag)
        except ValueError:
            continue
        kvar = (nar - idag).days
        if kvar not in (1, 7):
            continue
        anteckning = str(post.get("anteckning") or "").strip()
        when = "I morgon" if kvar == 1 else "Om en vecka"
        rad = (
            f"{when}, {_datum_text(ar, manad, dag)}: överföring {formatera_kr(belopp)} "
            f"från {_konto_namn(konton, fran)} till {_konto_namn(konton, till)}. "
            "Se till att pengarna finns på kontot du för över från."
        )
        if anteckning:
            rad = f"{rad}\n{anteckning}"
        lagg(nar, f"over|{ar}|{manad}|{dag}|{fran}|{till}|{belopp}", when, rad, kvar)

    traffar.sort(key=lambda t: (t["nar"], t["text"]))
    return traffar


def _visade(katalog: Path) -> set[str]:
    sokvag = planer_katalog(katalog) / _VISADE_FIL
    if not sokvag.is_file():
        return set()
    try:
        data = json.loads(sokvag.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    idag = date.today().isoformat()
    return {n for n in data.get("visade") or [] if str(n).startswith(idag)}


def _markera(katalog: Path, nycklar: list[str]) -> None:
    sokvag = planer_katalog(katalog) / _VISADE_FIL
    tidigare = _visade(katalog)
    tidigare.update(nycklar)
    sokvag.write_text(
        json.dumps({"visade": sorted(tidigare)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def texter_att_visa(katalog: Path, idag: date | None = None, data: dict | None = None) -> list[str]:
    """Påminnelser som inte redan visats idag. Markerar dem som visade."""
    if data is None:
        namn = hamta_aktiv_plan(katalog)
        if not namn:
            return []
        data = ladda_data(plan_fil(katalog, namn))
        if not data:
            return []
    data = uppgradera_plan_data(data)
    redan = _visade(katalog)
    nya = [p for p in samla_paminnelser(data, idag) if p["nyckel"] not in redan]
    if not nya:
        return []
    _markera(katalog, [p["nyckel"] for p in nya])
    return [p["text"] for p in nya]
