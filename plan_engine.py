"""Beräkningsmotor för pensionsplanering."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_START_AR = 2030
MIN_START_AR = 2000
ANTAL_KONTON = 12
TRANSKONTO = 1
AUTO_OVERFOR_FRAN = 2
AUTO_OVERFOR_TILL = 1
# Räntan betalas ut sista december och bokförs i januari året efter.
# År här får ingen ränta alls.
INGEN_RANTA_AR: frozenset[int] = frozenset()

MANADER = [
    "jan", "feb", "mar", "apr", "maj", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
]

MANAD_NAMN_TILL_NUMMER = {namn: i + 1 for i, namn in enumerate(MANADER)}

# Bakåtkompatibilitet
START_AR = DEFAULT_START_AR


def konto_val() -> list[str]:
    return [f"Konto {i}" for i in range(1, ANTAL_KONTON + 1)]


def konto_visningsnamn(konton: list[dict] | None, nr: int) -> str:
    """Returnerar eget namn eller 'Konto N'. nr är 1-baserat."""
    if konton and 1 <= nr <= len(konton):
        namn = str(konton[nr - 1].get("namn", "")).strip()
        if namn:
            return namn
    return f"Konto {nr}"


def konto_val_fran_data(konton: list[dict] | None) -> list[str]:
    return [konto_visningsnamn(konton, i) for i in range(1, ANTAL_KONTON + 1)]


def konto_nr_fran_visning(text: str, konton: list[dict] | None = None) -> int:
    text = text.strip()
    if konton:
        for i, k in enumerate(konton[:ANTAL_KONTON]):
            if text == konto_visningsnamn(konton, i + 1):
                return i + 1
    try:
        nr = int(text.split()[-1])
        if 1 <= nr <= ANTAL_KONTON:
            return nr
    except (TypeError, ValueError, IndexError):
        pass
    return 1


def konto_tabell_rubrik(konton: list[dict] | None, nr: int, max_len: int = 12) -> str:
    namn = konto_visningsnamn(konton, nr)
    if len(namn) <= max_len:
        return namn
    return namn[: max_len - 1] + "…"


@dataclass
class Engangsuttag:
    ar: int
    manad: int
    belopp: int
    konto: int = 1
    dag: int = 1


@dataclass
class Engangsinsattning:
    ar: int
    manad: int
    belopp: int
    konto: int = 1
    dag: int = 1


@dataclass
class Ranteandring:
    ar: int
    manad: int
    ranta_procent: float
    skatt_pa_ranta_procent: float


@dataclass
class Overforing:
    ar: int
    manad: int
    fran_konto: int
    till_konto: int
    belopp: int
    dag: int = 1


@dataclass
class KontoConfig:
    sparat_kr: int = 0
    ranta_procent: float = 2.4
    skatt_pa_ranta_procent: float = 30.0
    ranta_andringar: list[Ranteandring] = field(default_factory=list)
    namn: str = ""
    overskott: bool = False
    manadsranta: bool = False


def standard_konton() -> list[KontoConfig]:
    return [KontoConfig() for _ in range(ANTAL_KONTON)]


def normalisera_konton(konton: list[KontoConfig]) -> list[KontoConfig]:
    resultat = list(konton)
    while len(resultat) < ANTAL_KONTON:
        resultat.append(KontoConfig())
    return resultat[:ANTAL_KONTON]


@dataclass
class PlanConfig:
    start_ar: int = DEFAULT_START_AR
    start_manad: int = 1
    slut_ar: int = 2045
    slut_manad: int = 12
    slut_dag: int | None = None
    konton: list[KontoConfig] = field(default_factory=standard_konton)
    person1_pension_kr: int = 0
    person2_pension_kr: int = 0
    manadsbehov_kr: int = 0
    manadsvarden: dict[tuple[int, int], dict[str, int]] = field(default_factory=dict)
    engangsuttag: list[Engangsuttag] = field(default_factory=list)
    engangsinsattningar: list[Engangsinsattning] = field(default_factory=list)
    overforingar: list[Overforing] = field(default_factory=list)
    # Månader där överskottet på transaktionskontot är satt för hand.
    overskott_ersattning: dict[tuple[int, int], int] = field(default_factory=dict)
    lagg_overskott_till_sparande: bool = True
    auto_overfor_uttag_konto2: bool = False
    # Ränta, överskott och underskott räknas bara från den här månaden.
    # Tidigare månader är det som lagts in för hand.
    automatik_fran: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        self.konton = normalisera_konton(self.konton)

    @property
    def startkapital(self) -> int:
        return sum(k.sparat_kr for k in self.konton)

    @property
    def sparat_kr(self) -> int:
        return self.konton[0].sparat_kr

    @sparat_kr.setter
    def sparat_kr(self, value: int) -> None:
        self.konton[0].sparat_kr = value

    @property
    def sparat_kr_2(self) -> int:
        return self.konton[1].sparat_kr

    @sparat_kr_2.setter
    def sparat_kr_2(self, value: int) -> None:
        self.konton[1].sparat_kr = value

    @property
    def sparat_kr_3(self) -> int:
        return self.konton[2].sparat_kr

    @sparat_kr_3.setter
    def sparat_kr_3(self, value: int) -> None:
        self.konton[2].sparat_kr = value

    @property
    def ranta_procent(self) -> float:
        return self.konton[0].ranta_procent

    @ranta_procent.setter
    def ranta_procent(self, value: float) -> None:
        self.konton[0].ranta_procent = value

    @property
    def skatt_pa_ranta_procent(self) -> float:
        return self.konton[0].skatt_pa_ranta_procent

    @skatt_pa_ranta_procent.setter
    def skatt_pa_ranta_procent(self, value: float) -> None:
        self.konton[0].skatt_pa_ranta_procent = value

    @property
    def ranta_procent_2(self) -> float:
        return self.konton[1].ranta_procent

    @ranta_procent_2.setter
    def ranta_procent_2(self, value: float) -> None:
        self.konton[1].ranta_procent = value

    @property
    def skatt_pa_ranta_procent_2(self) -> float:
        return self.konton[1].skatt_pa_ranta_procent

    @skatt_pa_ranta_procent_2.setter
    def skatt_pa_ranta_procent_2(self, value: float) -> None:
        self.konton[1].skatt_pa_ranta_procent = value

    @property
    def ranta_procent_3(self) -> float:
        return self.konton[2].ranta_procent

    @ranta_procent_3.setter
    def ranta_procent_3(self, value: float) -> None:
        self.konton[2].ranta_procent = value

    @property
    def skatt_pa_ranta_procent_3(self) -> float:
        return self.konton[2].skatt_pa_ranta_procent

    @skatt_pa_ranta_procent_3.setter
    def skatt_pa_ranta_procent_3(self, value: float) -> None:
        self.konton[2].skatt_pa_ranta_procent = value

    @property
    def ranta_andringar(self) -> list[Ranteandring]:
        return self.konton[0].ranta_andringar

    @ranta_andringar.setter
    def ranta_andringar(self, value: list[Ranteandring]) -> None:
        self.konton[0].ranta_andringar = value

    @property
    def ranta_andringar_2(self) -> list[Ranteandring]:
        return self.konton[1].ranta_andringar

    @ranta_andringar_2.setter
    def ranta_andringar_2(self, value: list[Ranteandring]) -> None:
        self.konton[1].ranta_andringar = value

    @property
    def ranta_andringar_3(self) -> list[Ranteandring]:
        return self.konton[2].ranta_andringar

    @ranta_andringar_3.setter
    def ranta_andringar_3(self, value: list[Ranteandring]) -> None:
        self.konton[2].ranta_andringar = value

    @property
    def har_andra_konto(self) -> bool:
        return self.konton[1].sparat_kr != 0

    @property
    def har_tredje_konto(self) -> bool:
        return self.konton[2].sparat_kr != 0


@dataclass
class KontoTransaktion:
    ar: int
    manad: int
    manad_namn: str
    konto: int
    belopp: int
    saldo_efter: int
    beskrivning: str

    @property
    def datum(self) -> str:
        return f"{self.manad_namn} {self.ar}"


@dataclass
class PlanKorning:
    manader: list[ManadResultat]
    transaktioner: list[KontoTransaktion]
    varningar: list[str] = field(default_factory=list)


@dataclass
class ManadResultat:
    ar: int
    manad: int
    manad_namn: str
    sparande_innan: int
    person1_pension: int
    person2_pension: int
    summa_pension: int
    manadsbehov: int
    effektiv_kostnad: int
    uttag: int
    tillagg: int
    engangsuttag: int
    engangsinsattning: int
    sparande_efter: int
    ranta_netto: int = 0
    ranta_manad: int = 0
    ranta_ar: int = 0
    ranta_slice: int = 0
    konton_efter: list[int] = field(default_factory=list)
    overforing_summa: int = 0
    krav_overforing: bool = False
    varning_text: str = ""

    def __post_init__(self) -> None:
        if not self.konton_efter:
            self.konton_efter = [0] * ANTAL_KONTON
        while len(self.konton_efter) < ANTAL_KONTON:
            self.konton_efter.append(0)
        self.konton_efter = self.konton_efter[:ANTAL_KONTON]

    def konto_efter(self, konto: int) -> int:
        if konto < 1 or konto > len(self.konton_efter):
            return 0
        return self.konton_efter[konto - 1]

    @property
    def konto1_efter(self) -> int:
        return self.konto_efter(1)

    @property
    def konto2_efter(self) -> int:
        return self.konto_efter(2)

    @property
    def konto3_efter(self) -> int:
        return self.konto_efter(3)


def _varde_for_manad(
    config: PlanConfig, ar: int, manad: int, nyckel: str, standard: int
) -> int:
    if (ar, manad) in config.manadsvarden and nyckel in config.manadsvarden[(ar, manad)]:
        return config.manadsvarden[(ar, manad)][nyckel]
    return standard


def _ar_manad_inom_period(config: PlanConfig, ar: int, manad: int) -> bool:
    start = config.start_ar * 12 + config.start_manad
    slut = config.slut_ar * 12 + config.slut_manad
    nu = ar * 12 + manad
    return start <= nu <= slut


def _uttag_for_manad(config: PlanConfig, ar: int, manad: int) -> int:
    person1 = _varde_for_manad(config, ar, manad, "person1", config.person1_pension_kr)
    person2 = _varde_for_manad(config, ar, manad, "person2", config.person2_pension_kr)
    behov = _varde_for_manad(config, ar, manad, "behov", config.manadsbehov_kr)
    if behov > person1 + person2:
        return behov - person1 - person2
    return 0


def _engangsuttag_for_manad(config: PlanConfig, ar: int, manad: int) -> int:
    return sum(eu.belopp for eu in config.engangsuttag if eu.ar == ar and eu.manad == manad)


def _engangsuttag_lista_for_manad(config: PlanConfig, ar: int, manad: int) -> list[Engangsuttag]:
    return [eu for eu in config.engangsuttag if eu.ar == ar and eu.manad == manad]


def _engangsinsattning_for_manad(config: PlanConfig, ar: int, manad: int) -> int:
    return sum(
        ei.belopp for ei in config.engangsinsattningar if ei.ar == ar and ei.manad == manad
    )


def _engangsinsattningar_for_manad(config: PlanConfig, ar: int, manad: int) -> list[Engangsinsattning]:
    return [ei for ei in config.engangsinsattningar if ei.ar == ar and ei.manad == manad]


def _overforingar_for_manad(config: PlanConfig, ar: int, manad: int) -> list[Overforing]:
    return [o for o in config.overforingar if o.ar == ar and o.manad == manad]


def _synlig_dag(config: PlanConfig, ar: int, manad: int) -> int:
    """Sista dag som räknas i månaden. Sista visade månaden kan kapas på ett datum."""
    sista = calendar.monthrange(ar, manad)[1]
    if config.slut_dag and ar == config.slut_ar and manad == config.slut_manad:
        return min(max(int(config.slut_dag), 1), sista)
    return sista


def _manad_tal(ar: int, manad: int) -> int:
    return ar * 12 + manad


def _ranta_med_andringar(
    ar: int,
    manad: int,
    ranta: float,
    skatt: float,
    andringar: list[Ranteandring],
) -> tuple[float, float]:
    nu = _manad_tal(ar, manad)
    for andring in sorted(andringar, key=lambda a: (a.ar, a.manad)):
        if _manad_tal(andring.ar, andring.manad) <= nu:
            ranta = andring.ranta_procent
            skatt = andring.skatt_pa_ranta_procent
    return ranta, skatt


def _ranta_for_konto(config: PlanConfig, konto: int, ar: int, manad: int) -> tuple[float, float]:
    k = config.konton[konto - 1]
    return _ranta_med_andringar(ar, manad, k.ranta_procent, k.skatt_pa_ranta_procent, k.ranta_andringar)


def _justera_konto(saldon: list[int], konto: int, delta: int) -> None:
    if konto < 1 or konto > len(saldon):
        raise ValueError(f"Ogiltigt konto: {konto}.")
    saldon[konto - 1] += delta


def _norm_kontonamn(namn: str) -> str:
    return "".join(
        str(namn).casefold().replace("å", "a").replace("ä", "a").replace("ö", "o").split()
    )


def _sparkonto_for_overskott(config: PlanConfig) -> int:
    """Kontot som är valt för överskott. Är inget valt används transaktionskontot."""
    for i, konto in enumerate(config.konton, start=1):
        if konto.overskott:
            return i
    return TRANSKONTO


def _rakna_lon_pa_sparkonto(
    config: PlanConfig,
    transaktioner: list[KontoTransaktion],
    saldon: list[int],
    ar: int,
    manad: int,
    pension: int,
    behov: int,
) -> int:
    """Framtida överskott läggs på kontot som är valt för överskott.

    Underskott dras därifrån först, sedan från övriga sparkonton.
    Transaktionskontot rörs inte när ett sådant konto är valt.
    Returnerar det belopp som inte kunde täckas.
    """
    mal = _sparkonto_for_overskott(config)
    netto = pension - behov
    if netto > 0:
        _logga_konto(
            transaktioner, saldon, mal, ar, manad, netto,
            "Överskott efter lön och räkningar",
        )
        return 0
    if netto == 0:
        return 0
    saknas = -netto
    ordning = [mal]
    for fran in range(AUTO_OVERFOR_FRAN, ANTAL_KONTON + 1):
        if fran != mal and fran != TRANSKONTO:
            ordning.append(fran)
    if mal == TRANSKONTO and TRANSKONTO not in ordning:
        ordning.insert(0, TRANSKONTO)
    for fran in ordning:
        if saknas <= 0:
            break
        finns = max(saldon[fran - 1], 0)
        if finns <= 0:
            continue
        belopp = min(finns, saknas)
        _logga_konto(
            transaktioner, saldon, fran, ar, manad, -belopp,
            "Underskott efter lön och räkningar",
        )
        saknas -= belopp
    return saknas


def _logga_konto(
    transaktioner: list[KontoTransaktion],
    saldon: list[int],
    konto: int,
    ar: int,
    manad: int,
    delta: int,
    beskrivning: str,
) -> None:
    if delta == 0:
        return
    _justera_konto(saldon, konto, delta)
    transaktioner.append(
        KontoTransaktion(
            ar=ar,
            manad=manad,
            manad_namn=MANADER[manad - 1],
            konto=konto,
            belopp=delta,
            saldo_efter=saldon[konto - 1],
            beskrivning=beskrivning,
        )
    )


def transaktioner_for_konto(
    transaktioner: list[KontoTransaktion],
    konto: int,
) -> list[KontoTransaktion]:
    return [t for t in transaktioner if t.konto == konto]


def _berakna_ranta_netto(saldo: int, ranta_procent: float, skatt_procent: float) -> int:
    if saldo <= 0:
        return 0
    brutto_ranta = round(saldo * ranta_procent / 100)
    skatt = round(brutto_ranta * skatt_procent / 100)
    return brutto_ranta - skatt


def _ar_manadsranta(konto: KontoConfig) -> bool:
    """Ränta varje månad på aktuellt saldo (ränta på ränta)."""
    return konto.manadsranta


def _berakna_manadsranta_netto(saldo: int, ranta_procent: float, skatt_procent: float) -> int:
    """En månads ränta på aktuellt saldo (årsränta/12), netto efter skatt.

    Nästa månad räknas på det nya saldot, så räntan efter skatt ingår.
    """
    if saldo <= 0 or ranta_procent <= 0:
        return 0
    brutto = round(saldo * (ranta_procent / 12) / 100)
    skatt = round(brutto * skatt_procent / 100)
    return brutto - skatt


def _ar_automatik(config: PlanConfig, ar: int, manad: int) -> bool:
    """Framtida månader får ränta och överskott i uträkningen. Tidigare månader inte."""
    start = config.automatik_fran
    if not start:
        return True
    return (ar, manad) >= start


def _namn(config: PlanConfig, nr: int) -> str:
    if 1 <= nr <= len(config.konton) and config.konton[nr - 1].namn:
        return config.konton[nr - 1].namn
    return f"Konto {nr}"


def kora_plan_med_transaktioner(config: PlanConfig) -> PlanKorning:
    saldon = [k.sparat_kr for k in config.konton]
    resultat: list[ManadResultat] = []
    transaktioner: list[KontoTransaktion] = []
    varningar: list[str] = []
    minus_varnat: set[int] = set()
    ar = config.start_ar
    manad = config.start_manad

    for i, konto in enumerate(config.konton, start=1):
        if konto.sparat_kr:
            transaktioner.append(
                KontoTransaktion(
                    ar=config.start_ar,
                    manad=config.start_manad,
                    manad_namn=MANADER[config.start_manad - 1],
                    konto=i,
                    belopp=konto.sparat_kr,
                    saldo_efter=konto.sparat_kr,
                    beskrivning="Startkapital",
                )
            )

    while _ar_manad_inom_period(config, ar, manad):
        person1 = _varde_for_manad(config, ar, manad, "person1", config.person1_pension_kr)
        person2 = _varde_for_manad(config, ar, manad, "person2", config.person2_pension_kr)
        behov = _varde_for_manad(config, ar, manad, "behov", config.manadsbehov_kr)
        effektiv_kostnad = behov

        pension = person1 + person2
        sparande_innan = sum(saldon)
        uttag = _uttag_for_manad(config, ar, manad)
        max_dag = _synlig_dag(config, ar, manad)

        ranta_netto = 0
        ranta_manad = 0
        ranta_ar = 0
        ranta_slice = 0
        start_tal = config.start_ar * 12 + config.start_manad
        nu_tal = ar * 12 + manad
        rakna_automatik = _ar_automatik(config, ar, manad)
        # Månadsränta (konton med ränta varje månad): föregående månads ränta sätts in den 1:a.
        if rakna_automatik and nu_tal > start_tal:
            fore_ar, fore_manad = (ar, manad - 1) if manad > 1 else (ar - 1, 12)
            for konto_idx in range(ANTAL_KONTON):
                if not _ar_manadsranta(config.konton[konto_idx]):
                    continue
                ranta, skatt = _ranta_for_konto(config, konto_idx + 1, fore_ar, fore_manad)
                netto = _berakna_manadsranta_netto(saldon[konto_idx], ranta, skatt)
                ranta_netto += netto
                ranta_manad += netto
                _logga_konto(
                    transaktioner, saldon, konto_idx + 1, ar, manad, netto,
                    f"Månadsränta {MANADER[fore_manad - 1]} {fore_ar} netto ({ranta} %)",
                )
        # Visningsraden får en månads andel av årsräntan. Kontot rörs inte här.
        if rakna_automatik and ar not in INGEN_RANTA_AR and nu_tal > start_tal:
            for konto_idx in range(ANTAL_KONTON):
                if _ar_manadsranta(config.konton[konto_idx]):
                    continue
                ranta, skatt = _ranta_for_konto(config, konto_idx + 1, ar, manad)
                ranta_slice += _berakna_manadsranta_netto(saldon[konto_idx], ranta, skatt)
        # Årsränta för föregående år, utbetald sista december, bokförs i januari.
        if rakna_automatik and manad == 1 and start_tal < nu_tal:
            rante_ar = ar - 1
            if rante_ar not in INGEN_RANTA_AR:
                for konto_idx in range(ANTAL_KONTON):
                    if _ar_manadsranta(config.konton[konto_idx]):
                        continue
                    ranta, skatt = _ranta_for_konto(config, konto_idx + 1, rante_ar, 12)
                    netto = _berakna_ranta_netto(saldon[konto_idx], ranta, skatt)
                    ranta_netto += netto
                    ranta_ar += netto
                    _logga_konto(
                        transaktioner, saldon, konto_idx + 1, ar, manad, netto,
                        f"Ränta {rante_ar} netto ({ranta} %, skatt {skatt} %)",
                    )

        insattningar_nu = [
            ei for ei in _engangsinsattningar_for_manad(config, ar, manad) if ei.dag <= max_dag
        ]
        insattning = sum(ei.belopp for ei in insattningar_nu)
        for ei in insattningar_nu:
            _logga_konto(
                transaktioner, saldon, ei.konto, ar, manad, ei.belopp,
                "Engångsinsättning",
            )

        overforing_summa = 0
        for overforing in _overforingar_for_manad(config, ar, manad):
            if overforing.dag > max_dag:
                continue
            if overforing.fran_konto == overforing.till_konto:
                continue
            if saldon[overforing.fran_konto - 1] < overforing.belopp:
                varningar.append(
                    f"Överföringen {overforing.dag} {MANADER[manad - 1]} {ar} på "
                    f"{formatera_kr(overforing.belopp)} från {_namn(config, overforing.fran_konto)} "
                    f"till {_namn(config, overforing.till_konto)} räknas inte: det finns bara "
                    f"{formatera_kr(max(saldon[overforing.fran_konto - 1], 0))} på kontot."
                )
                continue
            _logga_konto(
                transaktioner, saldon, overforing.fran_konto, ar, manad,
                -overforing.belopp,
                f"Överföring till konto {overforing.till_konto}",
            )
            _logga_konto(
                transaktioner, saldon, overforing.till_konto, ar, manad,
                overforing.belopp,
                f"Överföring från konto {overforing.fran_konto}",
            )
            if overforing.till_konto == TRANSKONTO:
                overforing_summa += overforing.belopp

        tillagg = 0
        if pension > effektiv_kostnad:
            tillagg = pension - effektiv_kostnad

        ersatt = config.overskott_ersattning.get((ar, manad)) if config.overskott_ersattning else None
        saknas_lon = 0
        if ersatt is not None:
            if ersatt:
                _logga_konto(
                    transaktioner, saldon, TRANSKONTO, ar, manad, ersatt,
                    "Kvar efter lön och räkningar",
                )
        elif rakna_automatik:
            saknas_lon = _rakna_lon_pa_sparkonto(
                config, transaktioner, saldon, ar, manad, pension, behov,
            )
        obetalt = max(0, -saldon[TRANSKONTO - 1]) if saldon[TRANSKONTO - 1] < 0 else 0
        obetalt += saknas_lon

        engang = 0
        for eu in _engangsuttag_lista_for_manad(config, ar, manad):
            if eu.dag > max_dag:
                continue
            _logga_konto(
                transaktioner, saldon, eu.konto, ar, manad, -eu.belopp,
                "Engångsuttag",
            )
            engang += eu.belopp
            if saldon[eu.konto - 1] < 0 and eu.konto not in minus_varnat:
                minus_varnat.add(eu.konto)
                varningar.append(
                    f"Uttaget {eu.dag} {MANADER[manad - 1]} {ar} på {formatera_kr(eu.belopp)} "
                    f"gör {_namn(config, eu.konto)} minus "
                    f"({formatera_kr(saldon[eu.konto - 1])}). För över pengar innan."
                )

        krav_overforing = False
        varning_text = ""
        if obetalt > 0 or sum(saldon) < 0:
            krav_overforing = True
            varning_text = f"Pengarna tar slut {MANADER[manad - 1]} {ar}."

        sparande = sum(saldon)

        resultat.append(
            ManadResultat(
                ar=ar,
                manad=manad,
                manad_namn=MANADER[manad - 1],
                sparande_innan=sparande_innan,
                person1_pension=person1,
                person2_pension=person2,
                summa_pension=pension,
                manadsbehov=behov,
                effektiv_kostnad=effektiv_kostnad,
                uttag=uttag,
                tillagg=tillagg,
                engangsuttag=engang,
                engangsinsattning=insattning,
                sparande_efter=sparande,
                ranta_netto=ranta_netto,
                ranta_manad=ranta_manad,
                ranta_ar=ranta_ar,
                ranta_slice=ranta_slice,
                konton_efter=list(saldon),
                overforing_summa=overforing_summa,
                krav_overforing=krav_overforing,
                varning_text=varning_text,
            )
        )

        if krav_overforing:
            break

        manad += 1
        if manad > 12:
            manad = 1
            ar += 1

    return PlanKorning(manader=resultat, transaktioner=transaktioner, varningar=varningar)


def samlad_ranta_visad(
    manader: list[ManadResultat],
    ar: int,
    manad: int,
    automatik_fran: tuple[int, int] | None = None,
) -> int:
    """Ränta t.o.m. vald månad. Årsräntan visas utspridd, utan att bokas förrän i januari."""
    lumps: dict[int, int] = {}
    for rad in manader:
        if rad.manad == 1 and rad.ranta_ar:
            lumps[rad.ar - 1] = rad.ranta_ar
    total = 0
    per_ar: dict[int, list[ManadResultat]] = {}
    for rad in manader:
        if (rad.ar, rad.manad) > (ar, manad):
            continue
        if automatik_fran and (rad.ar, rad.manad) < automatik_fran:
            continue
        total += rad.ranta_manad
        if rad.ar in INGEN_RANTA_AR:
            continue
        per_ar.setdefault(rad.ar, []).append(rad)
    for year, rader in per_ar.items():
        lump = lumps.get(year, 0)
        if lump:
            total += int(round(lump * len(rader) / 12))
        else:
            total += sum(rad.ranta_slice for rad in rader)
    return total


def kora_plan(config: PlanConfig) -> list[ManadResultat]:
    return kora_plan_med_transaktioner(config).manader


def formatera_kr(belopp: int) -> str:
    return f"{belopp:,}".replace(",", " ") + " kr"


def skapa_sammanfattning(
    config: PlanConfig,
    resultat: list[ManadResultat],
    rubrik: str = "SAMMANFATTNING",
    sista_visning: ManadResultat | None = None,
) -> str:
    rader = [rubrik, "=" * 44, ""]
    for i, konto in enumerate(config.konton, start=1):
        if konto.sparat_kr == 0 and i > 3:
            continue
        rader.append(f"Konto {i}:                {formatera_kr(konto.sparat_kr)}")
        rader.append(
            f"  Ränta: {konto.ranta_procent} %/år (skatt {konto.skatt_pa_ranta_procent} %)"
        )
        if konto.ranta_andringar:
            rader.append(f"Ränteändringar (konto {i}):")
            for andring in sorted(konto.ranta_andringar, key=lambda a: (a.ar, a.manad)):
                manad_namn = MANADER[andring.manad - 1]
                rader.append(
                    f"  från {manad_namn} {andring.ar}: "
                    f"{andring.ranta_procent} % (skatt {andring.skatt_pa_ranta_procent} %)"
                )
    rader.append(f"Startkapital totalt:    {formatera_kr(config.startkapital)}")
    mal = _sparkonto_for_overskott(config)
    rader.append(
        "Framtida överskott och underskott räknas på "
        f"{config.konton[mal - 1].namn or f'konto {mal}'}"
    )
    if config.overforingar:
        rader.append("Överföringar mellan konton:")
        for overforing in sorted(
            config.overforingar, key=lambda o: (o.ar, o.manad, o.fran_konto, o.till_konto)
        ):
            manad_namn = MANADER[overforing.manad - 1]
            rader.append(
                f"  {manad_namn} {overforing.ar}: "
                f"{formatera_kr(overforing.belopp)} från konto {overforing.fran_konto} "
                f"till konto {overforing.till_konto}"
            )

    rader.extend([
        f"Period: {config.start_ar} – {config.slut_ar}",
        f"Månader beräknade:      {len(resultat)}",
        "",
    ])

    if not resultat:
        rader.append("Inga månader beräknades.")
        return "\n".join(rader)

    sista = sista_visning if sista_visning is not None else resultat[-1]
    totalt_uttag = sum(r.uttag for r in resultat)
    totalt_engang = sum(r.engangsuttag for r in resultat)
    totalt_insattning = sum(r.engangsinsattning for r in resultat)
    totalt_ranta = sum(r.ranta_netto for r in resultat)
    forvantade_manader = (config.slut_ar - config.start_ar) * 12 + (
        config.slut_manad - config.start_manad + 1
    )

    if sista.krav_overforing:
        rader.append(f"Pengarna tar slut {sista.manad_namn} {sista.ar}")
        if sista.varning_text:
            rader.append(f"  {sista.varning_text}")
    elif len(resultat) < forvantade_manader:
        rader.append(f"VARNING: Avbröts i {sista.manad_namn} {sista.ar}")
    else:
        rader.append("Sparandet räcker hela perioden")

    rader.extend([
        "",
        f"SPARANDE KVAR:          {formatera_kr(max(sista.sparande_efter, 0))}",
        f"  ({sista.manad_namn} {sista.ar})",
        "",
        f"Totalt månadsuttag:     {formatera_kr(totalt_uttag)}",
        f"Totalt engångsuttag:    {formatera_kr(totalt_engang)}",
        f"Totalt engångsinsättn.: {formatera_kr(totalt_insattning)}",
        f"Total nettoränta:       {formatera_kr(totalt_ranta)}",
    ])
    return "\n".join(rader)


def spara_csv(
    sokvag: Path,
    resultat: list[ManadResultat],
    person_namn: list[str] | None = None,
    antal_personer: int = 2,
) -> None:
    namn = person_namn or ["Person 1", "Person 2"]
    konto_rubriker = [f"Konto {i}" for i in range(1, ANTAL_KONTON + 1)]
    if antal_personer == 1:
        rubriker = [
            "År", "Månad", "Sparande innan", namn[0],
            "Summa inkomst", "Behov", "Effektiv kostnad",
            "Uttag", "Tillägg", "Engångsinsättning", "Engångsuttag", "Ränta netto", "Sparande efter",
        ] + konto_rubriker
    else:
        rubriker = [
            "År", "Månad", "Sparande innan", namn[0], namn[1] if len(namn) > 1 else "Person 2",
            "Summa inkomst", "Behov", "Effektiv kostnad",
            "Uttag", "Tillägg", "Engångsinsättning", "Engångsuttag", "Ränta netto", "Sparande efter",
        ] + konto_rubriker
    rader = [rubriker]
    for r in resultat:
        if antal_personer == 1:
            rad = [
                r.ar, r.manad_namn, r.sparande_innan, r.person1_pension,
                r.summa_pension, r.manadsbehov,
                r.effektiv_kostnad,
                r.uttag, r.tillagg, r.engangsinsattning, r.engangsuttag, r.ranta_netto, r.sparande_efter,
            ]
        else:
            rad = [
                r.ar, r.manad_namn, r.sparande_innan, r.person1_pension, r.person2_pension,
                r.summa_pension, r.manadsbehov,
                r.effektiv_kostnad,
                r.uttag, r.tillagg, r.engangsinsattning, r.engangsuttag, r.ranta_netto, r.sparande_efter,
            ]
        rad.extend(r.konton_efter)
        rader.append(rad)
    sokvag.parent.mkdir(parents=True, exist_ok=True)
    with sokvag.open("w", encoding="utf-8-sig") as f:
        for rad in rader:
            f.write(";".join(str(v) for v in rad) + "\n")
