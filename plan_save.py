"""Spara och ladda planer."""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_PLAN_NAMN = "plan_2030"
INSTÄLLNINGAR_FIL = "_installningar.json"
AKTUELL_VERSION = 15

LEGACY_GEMENSAMT_NYCKLAR = (
    "landstalle",
    "landstalle_ar",
    "landstalle_manad",
    "radhus",
    "radhus_ar",
    "radhus_manad",
)


def planer_katalog(katalog: Path) -> Path:
    mapp = katalog / "planer"
    mapp.mkdir(exist_ok=True)
    return mapp


def normalisera_plan_namn(namn: str) -> str:
    namn = namn.strip()
    if not namn:
        raise ValueError("Ange ett namn för planen.")
    if not re.fullmatch(r"[\w\- åäöÅÄÖ]+", namn, re.UNICODE):
        raise ValueError("Namnet får bara innehålla bokstäver, siffror, mellanslag och bindestreck.")
    return namn


def plan_fil(katalog: Path, namn: str) -> Path:
    return planer_katalog(katalog) / f"{normalisera_plan_namn(namn)}.json"


def plan_csv_fil(katalog: Path, namn: str) -> Path:
    return planer_katalog(katalog) / f"{normalisera_plan_namn(namn)}.csv"


def plan_pdf_fil(katalog: Path, namn: str) -> Path:
    return planer_katalog(katalog) / f"{normalisera_plan_namn(namn)}_sammanfattning.pdf"


def inställningar_fil(katalog: Path) -> Path:
    return planer_katalog(katalog) / INSTÄLLNINGAR_FIL


def manad_nyckel(ar: int, manad: int) -> str:
    return f"{ar}-{manad}"


def spara_data(sokvag: Path, data: dict) -> None:
    sokvag.parent.mkdir(parents=True, exist_ok=True)
    with sokvag.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ladda_data(sokvag: Path) -> dict | None:
    if not sokvag.exists():
        return None
    try:
        with sokvag.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def lista_planer(katalog: Path) -> list[str]:
    mapp = planer_katalog(katalog)
    namn = []
    for fil in sorted(mapp.glob("*.json")):
        if fil.name == INSTÄLLNINGAR_FIL:
            continue
        namn.append(fil.stem)
    return namn


def hamta_aktiv_plan(katalog: Path) -> str:
    data = ladda_data(inställningar_fil(katalog))
    if data and data.get("aktiv_plan"):
        return str(data["aktiv_plan"])
    planer = lista_planer(katalog)
    if planer:
        return planer[0]
    return DEFAULT_PLAN_NAMN


def hamta_installningar(katalog: Path) -> dict:
    return ladda_data(inställningar_fil(katalog)) or {}


def spara_installningar(katalog: Path, uppdatering: dict) -> None:
    data = hamta_installningar(katalog)
    data.update(uppdatering)
    spara_data(inställningar_fil(katalog), data)


def har_gjort_forsta_start(katalog: Path) -> bool:
    return bool(hamta_installningar(katalog).get("forsta_start_klar"))


def markera_forsta_start_klar(katalog: Path) -> None:
    spara_installningar(katalog, {"forsta_start_klar": True})


def har_visat_manual(katalog: Path) -> bool:
    return bool(hamta_installningar(katalog).get("manual_visad"))


def markera_manual_visad(katalog: Path) -> None:
    spara_installningar(katalog, {"manual_visad": True})


def spara_aktiv_plan(katalog: Path, namn: str) -> None:
    spara_installningar(katalog, {"aktiv_plan": normalisera_plan_namn(namn)})


def ta_bort_plan(katalog: Path, namn: str) -> bool:
    """Tar bort planens json- och csv-filer. Returnerar True om json-filen fanns."""
    namn = normalisera_plan_namn(namn)
    json_fil = plan_fil(katalog, namn)
    csv_fil = plan_csv_fil(katalog, namn)
    fanns = json_fil.exists()
    if json_fil.exists():
        json_fil.unlink()
    if csv_fil.exists():
        csv_fil.unlink()
    return fanns


def rensa_legacy_gemensamt(g: dict) -> None:
    """Tar bort gamla landställe/radhus-fält som inte längre används."""
    for nyckel in LEGACY_GEMENSAMT_NYCKLAR:
        g.pop(nyckel, None)



def normalisera_personer(raw: dict | None) -> dict:
    """Returnerar antal (1 eller 2) och namnlista från sparad plan."""
    if not raw:
        return {"antal": 2, "namn": ["", ""]}
    try:
        antal = int(raw.get("antal", 2))
    except (TypeError, ValueError):
        antal = 2
    if antal not in (1, 2):
        antal = 2
    namn_raw = raw.get("namn") or []
    if not isinstance(namn_raw, list):
        namn_raw = []
    if antal == 1:
        namn1 = str(namn_raw[0]).strip() if namn_raw else ""
        return {"antal": 1, "namn": [namn1]}
    namn1 = str(namn_raw[0]).strip() if len(namn_raw) > 0 else ""
    namn2 = str(namn_raw[1]).strip() if len(namn_raw) > 1 else ""
    return {"antal": 2, "namn": [namn1, namn2]}


def uppgradera_plan_data(data: dict) -> dict:
    """Rensar bort gammal data och migrerar till aktuell version."""
    g = data.setdefault("gemensamt", {})
    rensa_legacy_gemensamt(g)
    version = data.get("version", 1)
    if version < 3:
        g["engangsinsattningar"] = []
        data["version"] = 3
        version = 3
    if version < 4:
        if "personer" not in data:
            data["personer"] = {"antal": 2, "namn": ["", ""]}
        data["version"] = 4
        version = 4
    if version < 5:
        g.setdefault("sparat_3", "0")
        g.setdefault("ranta_3", "2.4")
        g.setdefault("skatt_3", "30")
        g.setdefault("rante_andringar_3", [])
        data["version"] = 5
        version = 5
    if version < 6:
        g.setdefault("overforingar", [])
        data["version"] = 6
        version = 6
    if version < 7:
        insattningar = g.get("engangsinsattningar", [])
        if isinstance(insattningar, list):
            for post in insattningar:
                if isinstance(post, dict):
                    post.setdefault("konto", "1")
        data["version"] = 7
        version = 7
    if version < 8:
        g.setdefault("auto_overfor_uttag_konto2", False)
        data["version"] = 8
        version = 8
    if version < 9:
        _migrera_till_konton(g)
        uttag = g.get("engangsuttag", [])
        if isinstance(uttag, list):
            for post in uttag:
                if isinstance(post, dict):
                    post.setdefault("konto", "1")
        data["version"] = 9
        version = 9
    if version < 10:
        data.setdefault("nuvarande_lage", {})
        data["version"] = 10
        version = 10
    if version < 11:
        # Nuvarande UI använder konto_rorelser i stället för separat nuvarande_lage-fönster
        g.setdefault("konto_rorelser", [])
        data["version"] = 11
        version = 11
    if version < 12:
        plan = data.setdefault("plan", {})
        if isinstance(plan, dict):
            plan.setdefault("uppfoljning", {})
        data["version"] = 12
        version = 12
    if version < 13:
        plan = data.get("plan")
        if isinstance(plan, dict):
            plan.pop("uppfoljning", None)
        data["version"] = 13
        version = 13
    if version < 14:
        konton = g.get("konton")
        if isinstance(konton, list):
            while len(konton) < 12:
                konton.append({
                    "aktiv": False,
                    "namn": "",
                    "sparat": "0",
                    "ranta": "2.4",
                    "skatt": "30",
                    "rante_andringar": [],
                })
        plan = data.setdefault("plan", {})
        if isinstance(plan, dict):
            for p in plan.get("perioder") or []:
                if isinstance(p, dict):
                    p.setdefault("anteckning", "")
        data["version"] = 14
        version = 14
    if version < 15:
        for nyckel in ("konto_rorelser", "overforingar"):
            poster = g.get(nyckel)
            if isinstance(poster, list):
                for post in poster:
                    if isinstance(post, dict):
                        post.setdefault("dag", 1)
        data["version"] = 15
        version = 15
    data["personer"] = normalisera_personer(data.get("personer"))
    return data


def _migrera_till_konton(g: dict) -> None:
    """Migrerar sparat/ränta/skatt från konto 1–3 till konton-lista."""
    if "konton" in g and isinstance(g["konton"], list) and len(g["konton"]) >= 10:
        return
    konton: list[dict] = []
    for i in range(1, 11):
        if i == 1:
            konton.append({
                "sparat": g.get("sparat", "0"),
                "ranta": g.get("ranta", "2.4"),
                "skatt": g.get("skatt", "30"),
                "rante_andringar": g.get("rante_andringar", []),
            })
        elif i == 2:
            konton.append({
                "sparat": g.get("sparat_2", "0"),
                "ranta": g.get("ranta_2", "2.4"),
                "skatt": g.get("skatt_2", "30"),
                "rante_andringar": g.get("rante_andringar_2", []),
            })
        elif i == 3:
            konton.append({
                "sparat": g.get("sparat_3", "0"),
                "ranta": g.get("ranta_3", "2.4"),
                "skatt": g.get("skatt_3", "30"),
                "rante_andringar": g.get("rante_andringar_3", []),
            })
        else:
            konton.append({
                "sparat": "0",
                "ranta": "2.4",
                "skatt": "30",
                "rante_andringar": [],
            })
    g["konton"] = konton


def migrera_gammal_sparfil(katalog: Path) -> None:
    """Flytta plan2030_data.json till planer/plan_2030.json om den finns."""
    gammal = katalog / "plan2030_data.json"
    if not gammal.exists():
        return
    ny = plan_fil(katalog, DEFAULT_PLAN_NAMN)
    if ny.exists():
        return
    data = ladda_data(gammal)
    if data:
        data = uppgradera_plan_data(data)
        spara_data(ny, data)
        spara_aktiv_plan(katalog, DEFAULT_PLAN_NAMN)
