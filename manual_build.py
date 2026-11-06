"""Bygg Manual.pdf med skärmbilder från manual_bilder/ (tas med manual_skarmbilder.py)."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).parent
OUT = ROOT / "Manual.pdf"
BILDER = ROOT / "manual_bilder"
FONTER = Path(r"C:\Windows\Fonts")

MORK = colors.HexColor("#17323C")
ACCENT = colors.HexColor("#2A9D8F")
MUTED = colors.HexColor("#6B7C83")
RUTA = colors.HexColor("#E7F4F1")

BREDD = A4[0] - 3.6 * cm
MAX_HOJD = 12.5 * cm
ZOOM_HOJD = 8 * cm
# 0,75 punkter per bildpunkt är bildens naturliga storlek när PDF:en visas i 100 %.
NATURLIG = 0.75
ZOOM_SKALA = 1.0


def _fonter() -> tuple[str, str]:
    try:
        pdfmetrics.registerFont(TTFont("Segoe", str(FONTER / "segoeui.ttf")))
        pdfmetrics.registerFont(TTFont("SegoeB", str(FONTER / "segoeuib.ttf")))
        pdfmetrics.registerFontFamily("Segoe", normal="Segoe", bold="SegoeB")
        return "Segoe", "SegoeB"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


VANLIG, FET = _fonter()
TITEL = ParagraphStyle("Titel", fontName=FET, fontSize=26, leading=32, textColor=MORK, spaceAfter=6)
UNDERTITEL = ParagraphStyle("Under", fontName=VANLIG, fontSize=12, leading=17, textColor=MUTED, spaceAfter=14)
H1 = ParagraphStyle("H1", fontName=FET, fontSize=17, leading=22, textColor=MORK, spaceBefore=6, spaceAfter=6)
H2 = ParagraphStyle("H2", fontName=FET, fontSize=12.5, leading=17, textColor=MORK, spaceBefore=8, spaceAfter=3)
TEXT = ParagraphStyle("Text", fontName=VANLIG, fontSize=10.5, leading=15, spaceAfter=4)
PUNKT = ParagraphStyle("Punkt", parent=TEXT, leftIndent=14, bulletIndent=2, spaceAfter=2)
TIPS = ParagraphStyle("Tips", parent=TEXT, textColor=MORK, spaceAfter=0)
BILDTEXT = ParagraphStyle("Bildtext", fontName=VANLIG, fontSize=9, leading=12, textColor=MUTED, spaceBefore=3, spaceAfter=10)


def p(text: str) -> Paragraph:
    return Paragraph(text, TEXT)


def punkter(*rader: str) -> list[Paragraph]:
    return [Paragraph(r, PUNKT, bulletText="•") for r in rader]


def numrerat(*rader: str) -> list[Paragraph]:
    return [Paragraph(r, PUNKT, bulletText=f"{i}.") for i, r in enumerate(rader, 1)]


def tips(text: str) -> Table:
    t = Table([[Paragraph(f"<b>Tips:</b> {text}", TIPS)]], colWidths=[BREDD])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RUTA),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


class BildBlock(KeepTogether):
    pass


def _ram(sokvag: Path, bredd: float, hojd: float) -> Table:
    ram = Table([[Image(str(sokvag), width=bredd, height=hojd)]], colWidths=[bredd + 2])
    ram.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9D3D6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return ram


def _markeringar() -> dict:
    fil = BILDER / "markeringar.json"
    return json.loads(fil.read_text(encoding="utf-8")) if fil.exists() else {}


MARKERINGAR = _markeringar()


def _utskarningar(namn: str, im: PILImage.Image, bara: tuple[int, ...] = ()) -> list[tuple[int, int, int, int]]:
    """Områden runt markeringarna. Ett gemensamt om de ligger nära varandra, annars ett per markering."""
    rutor = MARKERINGAR.get(namn) or []
    if bara:
        rutor = [r for nr, r in enumerate(rutor, 1) if nr in bara]
    b, h = im.size

    def klampa(r):
        return max(0, r[0] - 10), max(0, r[1] - 10), min(b, r[2] + 10), min(h, r[3] + 10)

    if not rutor:
        return []
    alla = klampa([min(r[0] for r in rutor), min(r[1] for r in rutor), max(r[2] for r in rutor), max(r[3] for r in rutor)])
    if (alla[2] - alla[0]) * (alla[3] - alla[1]) > 0.6 * b * h:
        return []
    if alla[2] - alla[0] <= 900 and alla[3] - alla[1] <= 480:
        return [alla]
    return [klampa(r) for r in rutor]


def bild(namn: str, text: str, utsnitt_av: tuple[int, ...] = ()) -> list:
    """Hela fönstret i naturlig storlek (eller mindre), plus förstorade utskärningar av det markerade.
    `utsnitt_av` begränsar förstoringen till vissa markeringsnummer."""
    sokvag = BILDER / f"{namn}.png"
    delar: list = []
    with PILImage.open(sokvag) as im:
        b, h = im.size
        skala = min(BREDD / b, MAX_HOJD / h, NATURLIG)
        delar.append(_ram(sokvag, b * skala, h * skala))
        rutor = _utskarningar(namn, im, utsnitt_av) if skala < NATURLIG * 0.9 else []
        for nr, ruta in enumerate(rutor, 1):
            utsnitt = im.crop(ruta)
            ut = BILDER / "utsnitt" / f"{namn}_{nr}.png"
            ut.parent.mkdir(exist_ok=True)
            utsnitt.save(ut)
            ub, uh = utsnitt.size
            zs = min(BREDD / ub, ZOOM_HOJD / uh, ZOOM_SKALA)
            delar += [Spacer(1, 0.25 * cm), _ram(ut, ub * zs, uh * zs)]
    delar.append(Paragraph(text, BILDTEXT))
    return [BildBlock(delar)]


def avsnitt(rubrik: str, *delar) -> list:
    """Rubrik och första stycket hålls ihop med första bilden."""
    platt: list = []
    for d in delar:
        platt.extend(d if isinstance(d, list) else [d])
    forsta_bild = next((i for i, d in enumerate(platt) if isinstance(d, BildBlock)), None)
    if forsta_bild is None:
        return [KeepTogether([Paragraph(rubrik, H2), *platt])]
    huvud = platt[: forsta_bild + 1]
    return [KeepTogether([Paragraph(rubrik, H2), *huvud]), *platt[forsta_bild + 1:]]


def _kapitel_ihop(story: list) -> list:
    """En kapitelrubrik får aldrig stå ensam längst ner på en sida."""
    ut: list = []
    i = 0
    while i < len(story):
        d = story[i]
        if isinstance(d, Paragraph) and d.style is H1 and i + 1 < len(story) and isinstance(story[i + 1], KeepTogether):
            ut.append(KeepTogether([d, *story[i + 1]._content]))
            i += 2
            continue
        ut.append(d)
        i += 1
    return ut


def sidfot(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(VANLIG, 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(1.8 * cm, 1.1 * cm, "Spar- och Pensionsplan – Manual")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Sida {doc.page}")
    canvas.restoreState()


def build_manual() -> None:
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        title="Spar- och Pensionsplan – Manual", author="Spar- och Pensionsplan",
    )
    s: list = []

    s += [
        Spacer(1, 1.5 * cm),
        Paragraph("Spar- och Pensionsplan", TITEL),
        Paragraph("Manual – steg för steg från en tom plan", UNDERTITEL),
        p(
            "Spar- och Pensionsplan hjälper dig att hålla koll på dina konton och aktier i dag och att se hur "
            "pengarna räcker och växer framåt, oavsett om du sparar till något eller planerar för pensionen."
        ),
        p(
            "Den här manualen går igenom hela programmet från början. Vi gör en påhittad plan för "
            "<b>Anna och Erik</b>: skapar planen, lägger till konton, sätter in pengar, flyttar pengar till "
            "Nordnet, köper en aktie, registrerar en utdelning, köper gratisaktier för utdelningen och säljer aktier."
        ),
        p(
            "Alla bilder är tagna i programmet. Siffrorna är bara exempel. "
            "<b>Röda ramar</b> visar var du ska titta eller klicka. När en bild har <b>nummer</b> förklaras de i texten."
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("Innehåll", H2),
        *numrerat(
            "Installera och starta programmet",
            "Skapa en ny plan",
            "Lägga till konton",
            "Sätta in pengar",
            "Föra över pengar till Nordnet och Avanza",
            "Nordnet – kontantkassa och Utdelning och vinst",
            "Köpa en aktie",
            "Registrera en utdelning",
            "Köpa gratisaktier för utdelningen",
            "Sälja aktier",
            "Ändra eller ta bort köp och försäljningar",
            "Avanza – plus och minus",
            "Översikten, kurser och PDF",
            "Inkomster",
            "Händelser",
            "Idag och framtiden",
            "Ränta, planer, inställningar och hjälp",
            "Vanliga frågor",
        ),
        Spacer(1, 0.6 * cm),
        tips(
            "Programmet sparar automatiskt hela tiden. Du behöver aldrig trycka på något för att spara."
        ),
        Spacer(1, 0.3 * cm),
        tips("Programmet är gratis. Gillar du det? Swisha gärna 100 kr till <b>070-091 33 10</b>. Tack!"),
        PageBreak(),
    ]

    s.append(Paragraph("1. Installera och starta programmet", H1))
    s += avsnitt(
        "Installera",
        p("Dubbelklicka på filen <b>SparOchPensionsplan_Setup_1.0.exe</b>."),
        p(
            "Windows kan då visa en blå ruta: <b>Windows skyddade datorn</b>. Det beror på att programmet inte är "
            "köpt via en butik eller signerat med ett betalt certifikat. Det betyder inte att något är fel."
        ),
        numrerat(
            "Klicka på <b>Mer info</b> i den blå rutan.",
            "Klicka på knappen <b>Kör ändå</b> som då visas.",
            "Följ installationen. Kryssa gärna i <b>Skapa en genväg på skrivbordet</b>.",
        ),
        tips(
            "Programmet installeras i din egen programmapp och behöver inte administratörslösenord. "
            "Det tas bort som vanligt under <b>Inställningar → Appar</b> i Windows."
        ),
    )
    s += avsnitt(
        "Öppna Spar- och Pensionsplan",
        p(
            "Dubbelklicka på <b>Spar- och Pensionsplan</b> på skrivbordet eller i Start-menyn. Så länge det inte finns "
            "någon plan öppnas den här manualen, och du får skapa din första plan. Sedan öppnar programmet den plan du använde senast och visar "
            "<b>dagens datum</b>. Börskurserna hämtas automatiskt när programmet startar."
        ),
        bild("01_oversikt_start", "Översikten. Knappen Ny plan sitter längst ner till vänster."),
        p("<b>Menyn till vänster:</b>"),
        punkter(
            "<b>Översikt</b> – totalsumman och alla konton för det datum du väljer.",
            "<b>Konton</b> – lägg till konton, sätt in, ta ut och för över pengar. Här finns även Nordnet och Avanza.",
            "<b>Inkomster</b> – lön, pension och vad ni behöver varje månad.",
            "<b>Händelser</b> – alla insättningar, uttag och överföringar i en lista.",
            "<b>Plan</b> – välj vilken plan som visas. Under den finns <b>Ny plan</b>, <b>Spara kopia…</b>, "
            "<b>Öppna från fil…</b>, <b>Ta bort plan</b>, <b>Inställningar</b> och <b>Hjälp</b>.",
        ),
    )

    s.append(Paragraph("2. Skapa en ny plan", H1))
    s += avsnitt(
        "Fyll i namn och personer",
        p("Klicka på <b>Ny plan</b>. En ruta öppnas:"),
        bild("02_ny_plan", "Skriv planens namn, välj en eller två personer och skriv namnen."),
        *numrerat(
            "Skriv ett namn på planen, till exempel <i>Exempelplan</i>.",
            "Välj <b>En</b> eller <b>Två</b> personer.",
            "Skriv namnen. De används som rubriker under Inkomster.",
            "Klicka på <b>Skapa plan</b>.",
        ),
        p("Manualen öppnas automatiskt när du klickar på Ny plan, så att du kan följa den. Rutan för den nya planen ligger framför."),
    )
    s += avsnitt(
        "Den nya planen",
        p(
            "En ny plan börjar på 0 kr. Två tomma börskonton finns med från start: <b>Nordnet</b>, som är ett "
            "<b>utdelningskonto</b>, och <b>Avanza</b>, som är ett <b>kursvinstkonto</b>. Programmet är inte kopplat till "
            "någon bank, så du kan döpa om dem till din egen bank eller ditt eget institut. "
            "Klicka på <b>Konton</b> för att lägga till dina vanliga konton."
        ),
        bild("03_ny_plan_oversikt", "Ny plan: 0 kr, och Avanza och Nordnet är tomma."),
    )

    s.append(PageBreak())
    s.append(Paragraph("3. Lägga till konton", H1))
    s += avsnitt(
        "Fönstret Konton",
        p(
            "Till vänster finns listan med konton. Klicka på ett konto för att se det till höger. "
            "Klicka på <b>+ Lägg till konto</b> för att lägga till ett nytt."
        ),
        bild("04_konton_start", "Konton i en ny plan. Bara Avanza och Nordnet finns."),
    )
    s += avsnitt(
        "Nytt konto",
        bild("05_nytt_konto", "Fyll i kontots uppgifter och klicka på Lägg till."),
        punkter(
            "<b>Namn</b> – det som visas i listan och på översikten, till exempel <i>Lönekonto</i>.",
            "<b>Saldo nu</b> – hur mycket som finns på kontot i dag.",
            "<b>Ränta</b> – räntan i procent per år, till exempel 3.5.",
            "<b>Skatt på ränta</b> – normalt 30.",
        ),
        tips(
            "Det första kontot du lägger till blir <b>konto 1, plånboken</b>. Inkomster och utgifter går via det. "
            "Det andra blir <b>konto 2, bufferten</b>. Om plånboken inte räcker en månad fylls den på därifrån."
        ),
    )
    s += avsnitt(
        "Kontots sida",
        bild("06_lonekonto", "Lönekontot är tillagt. Knapparna 1–3 används för att flytta pengar."),
        numrerat(
            "<b>+ Insättning</b> – pengar som kommer in på kontot.",
            "<b>− Uttag</b> – pengar som tas ut.",
            "<b>Överför</b> – flytta pengar till ett annat konto.",
        ),
        punkter(
            "Namn, startsaldo, ränta och skatt kan ändras direkt i fälten. Det sparas av sig självt.",
            "<b>Ränteändringar</b> – om räntan ändras längre fram, lägg till den nya räntan från en viss månad.",
            "Du kan <b>dra</b> konton i listan till vänster för att ändra ordning (inte plånboken).",
            "<b>Ta bort konto</b> finns till höger. Plånboken kan inte tas bort.",
        ),
    )
    s += avsnitt(
        "Ränta varje månad och var överskottet hamnar",
        p(
            "I exemplet lägger vi till ett konto till, <b>Sparkonto</b> med 100 000 kr och 3,5 % ränta. "
            "Det blir konto 2, bufferten. På kontots sida finns två kryssrutor:"
        ),
        bild("06b_kontoval", "Sparkontot är valt som kontot där framtida överskott och underskott räknas."),
        numrerat(
            "<b>Ränta varje månad</b> – kryssa i om banken betalar ränta varje månad, så att det blir ränta på ränta. "
            "Utan kryss kommer räntan för hela året i januari året efter.",
            "<b>Framtida överskott och underskott räknas på det här kontot</b> – när inkomsten är större än behovet "
            "läggs det som blir över här, och när den är mindre tas det härifrån. Bara ett konto kan vara valt.",
            "Rubriken överst visar vilket konto som är valt.",
        ),
        tips(
            "Har du inte valt något konto räknas överskott och underskott på konto 1, plånboken. "
            "Nordnet och Avanza kan inte väljas."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("4. Sätta in pengar", H1))
    s += avsnitt(
        "Insättning på ett konto",
        p("Välj kontot i listan och klicka på <b>+ Insättning</b>."),
        bild("07_insattning", "Välj datum, skriv beloppet och en anteckning om du vill."),
        numrerat(
            "Välj <b>dag, månad och år</b>. Det kan vara i dag eller längre fram.",
            "Skriv <b>beloppet</b> i kronor.",
            "Skriv en <b>anteckning</b> om du vill, till exempel <i>Julbonus</i>.",
            "Klicka på <b>Spara</b>.",
        ),
        p("Du får en påminnelse en vecka innan och dagen innan, när programmet är öppet."),
    )
    s += avsnitt(
        "Insättningen syns på kontot",
        bild("08_sparkonto_med_insattning", "Insättningen ligger i listan Insättningar och uttag."),
        p(
            "Saldot ändras från och med datumet för insättningen. I bilden är saldot den 6 november fortfarande 100 000 kr, "
            "eftersom insättningen görs den 25 december. Klicka på <b>ändra</b> eller <b>ta bort</b> på raden för att ändra den."
        ),
        p("<b>Uttag</b> fungerar på samma sätt, men pengarna dras från kontot."),
    )

    s.append(Paragraph("5. Föra över pengar till Nordnet och Avanza", H1))
    s += avsnitt(
        "Överföring",
        p("Välj kontot pengarna ska tas från och klicka på <b>Överför</b>."),
        bild("09_overfor", "Från Sparkonto till Nordnet, 40 000 kr."),
        numrerat(
            "<b>Från</b> – kontot pengarna tas från.",
            "<b>Till</b> – kontot pengarna ska till.",
            "Välj datum och skriv beloppet.",
            "Klicka på <b>Överför</b>.",
        ),
        tips(
            "En överföring till Nordnet eller Avanza hamnar i det kontots <b>kontantkassa</b>. "
            "Där används pengarna sedan till att köpa aktier. I exemplet förs även 10 000 kr över till Avanza."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("6. Nordnet – kontantkassa och Utdelning och vinst", H1))
    s += avsnitt(
        "Nordnets sida",
        p("Klicka på <b>Nordnet</b> i listan. Nordnet är kontot för <b>utdelningsaktier</b>."),
        bild("10_nordnet_start", "Nordnet efter överföringen. De två kassorna finns längst ner till vänster."),
        punkter(
            "<b>Hela innehavet</b> (överst) – börsvärde, grundinsats, utdelning per år och avkastning på insatsen för alla aktier. "
            "På raden under står <b>Plus/minus nu</b> (börsvärdet minus grundinsatsen, i kronor och procent) och "
            "<b>Resultat sålda</b> (vinst eller förlust på allt du har sålt).",
            "<b>Sök aktie</b> – här letar du upp aktier att köpa.",
            "<b>Listan</b> – dina aktier. Klicka på en aktie för att se den till höger.",
        ),
        numrerat(
            "<b>Kontantkassa</b> – pengar som inte sitter i aktier. Köp dras härifrån. "
            "<b>Rätta</b> ändrar beloppet så att det stämmer med Nordnet. <b>Insättning</b> sätter in pengar utifrån.",
            "<b>Utdelning och vinst</b> – utdelningar och vinst från sålda aktier hamnar här. "
            "Härifrån köper du gratisaktier.",
        ),
        p("Båda kassorna räknas in i kontots värde på översikten."),
        tips(
            "Överst står <b>Kontots namn</b>. Skriv ditt eget namn där, till exempel <i>SEB Depå</i>. "
            "Kontot fungerar likadant oavsett namn. Aktierna, kassorna och kurserna påverkas inte. "
            "Kurserna hämtas från internet och har inget med din bank att göra."
        ),
    )
    s += avsnitt(
        "Insättning direkt på Nordnet",
        p(
            "Om pengar kommer från ett konto som inte finns i planen klickar du på <b>Insättning</b> i kontantkassan. "
            "Beloppet läggs i kontantkassan och dras inte från något annat konto."
        ),
        bild("11_nordnet_insattning", "Insättning på 5 000 kr direkt till Nordnets kontantkassa."),
    )

    s.append(PageBreak())
    s.append(Paragraph("7. Köpa en aktie", H1))
    s += avsnitt(
        "Sök fram aktien",
        p(
            "Skriv namnet i rutan <b>Sök aktie</b>, till exempel <i>Telia</i>. Träffarna kommer upp efter en kort stund "
            "(datorn måste vara uppkopplad mot internet)."
        ),
        bild("12_sok_aktie", "1: sökrutan. 2: träffarna."),
        tips("Välj aktien som slutar på <b>.ST</b> och där det står <b>Stockholm</b>. Det är den svenska aktien i kronor."),
    )
    s += avsnitt(
        "Antal och kurs",
        bild("13_kop_aktie", "Telia är vald. Skriv antal och klicka på Lägg till."),
        numrerat(
            "Här ser du vilken aktie som är vald.",
            "Skriv <b>antal aktier</b>. Lämnar du <b>Köpkurs per aktie</b> tom används dagens kurs. "
            "Skriv kursen om du köpte till ett annat pris.",
            "Klicka på <b>Lägg till</b>.",
        ),
        p(
            "<b>Courtage</b> på 0,25 % (minst 1 kr) räknas med automatiskt. Det läggs på grundinsatsen och "
            "dras från kontantkassan tillsammans med köpet."
        ),
    )
    s += avsnitt(
        "Aktien är köpt",
        bild("14_aktie_kopt", "Telia finns i listan och kontantkassan har minskat med köpet."),
        numrerat(
            "<b>Listan</b>: Ticker, namn, antal, <b>Grundbelopp</b> (det du betalat inklusive courtage), "
            "<b>På insatsen</b> (utdelningen i procent av det du betalat) och <b>Sålt</b> (vinst eller förlust när du sålt).",
            "<b>Kontantkassan</b> har minskat med köpet: 45 000 kr blev 5 870,42 kr.",
        ),
        p(
            "Till höger visas den valda aktien: <b>Avkastning på investerat kapital</b>, <b>Direktavkastning på kursen</b>, "
            "antal, snittkurs och utdelning per år. Vill du köpa fler av samma aktie använder du "
            "<b>Lägg till aktier du betalar för</b> till höger. <b>Fråga ChatGPT</b> öppnar ChatGPT med en färdig fråga om aktien."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("8. Registrera en utdelning", H1))
    s += avsnitt(
        "Lägg in utdelningen",
        p("När en utdelning har kommit in på Nordnet skriver du in den längst ner till vänster."),
        bild("15_utdelning", "Utdelning på 500 kr från Telia."),
        numrerat(
            "Skriv beloppet vid <b>Ny utdelning</b>. Datumet fylls i med dagens datum, men du kan ändra det.",
            "Välj vilken aktie utdelningen kom <b>från</b>.",
            "Klicka på <b>Lägg till</b>.",
        ),
    )
    s += avsnitt(
        "Utdelningen ligger i kassan",
        bild("16_utdelning_inlagd", "Utdelning och vinst är nu 500 kr."),
        punkter(
            "<b>Historik</b> visar alla utdelningar du lagt in. Där kan de också tas bort.",
            "<b>Utdelningskalender</b> visar väntade utdelningar de närmaste 12 månaderna.",
            "<b>Rätta saldo</b> sätter Utdelning och vinst till beloppet du skriver i rutan Ny utdelning.",
        ),
    )

    s.append(Paragraph("9. Köpa gratisaktier för utdelningen", H1))
    s += avsnitt(
        "Köp för pengarna i Utdelning och vinst",
        p(
            "Aktier som köps för utdelningspengar kallas <b>gratisaktier</b>. De höjer inte grundinsatsen, "
            "eftersom det inte är dina egna pengar. Därför stiger <b>På insatsen</b> när du köper dem."
        ),
        bild("17_gratisaktier", "10 gratisaktier i Telia. Kursen lämnas tom, så dagens kurs används."),
        numrerat(
            "Skriv antal aktier under <b>Köp gratisaktier för utdelningen</b>. Tom kurs betyder dagens kurs.",
            "Klicka på <b>Lägg till gratis</b>.",
        ),
    )
    s += avsnitt(
        "Efter köpet",
        bild("18_gratis_kopta", "Antalet har ökat till 810. Kostnaden har dragits från Utdelning och vinst."),
        p(
            "Kostnaden plus courtage dras från <b>Utdelning och vinst</b>. Räcker inte pengarna där får du ett meddelande "
            "och inget köp görs."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("10. Sälja aktier", H1))
    s += avsnitt(
        "Sälj",
        bild("19_salj", "300 aktier säljs till 53,67 kr."),
        numrerat(
            "Skriv hur många aktier du säljer.",
            "Skriv <b>försäljningskursen</b>.",
            "Klicka på <b>Sälj betalda</b>. Säljer du gratisaktier klickar du på <b>Sälj gratis</b>.",
        ),
    )
    s += avsnitt(
        "Vart pengarna tar vägen",
        bild("20_salt", "Försäljningen är gjord. Vinsten hamnade i Utdelning och vinst."),
        numrerat(
            "Kolumnen <b>Sålt</b> visar vinsten (grön) eller förlusten (röd) för aktien. Summan för alla aktier står "
            "vid <b>Resultat sålda</b> överst, och för den valda aktien till höger.",
            "<b>Vinsten</b> läggs i <b>Utdelning och vinst</b>. Den kan användas till gratisaktier precis som utdelningar.",
            "Det du ursprungligen betalade för aktierna går tillbaka till <b>kontantkassan</b>.",
        ),
        tips(
            "Blir det förlust dras förlusten från Utdelning och vinst, men aldrig så att kassan blir mindre än 0 kr. "
            "Courtaget för försäljningen räknas också med automatiskt."
        ),
    )

    s.append(Paragraph("11. Ändra eller ta bort köp och försäljningar", H1))
    s += avsnitt(
        "Transaktioner",
        p("Markera aktien i listan och klicka på <b>Transaktioner</b> längst ner till höger."),
        bild("21_transaktioner", "Alla köp, gratisköp och försäljningar för Telia."),
        p(
            "Ändra antal eller kurs och klicka på <b>Spara</b>, eller klicka på <b>Ta bort</b>. "
            "Kontantkassan och Utdelning och vinst rättas automatiskt. Tar du bort ett gratisköp kommer pengarna "
            "tillbaka till Utdelning och vinst."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("12. Avanza – plus och minus", H1))
    s += avsnitt(
        "Avanzas sida",
        p(
            "Avanza fungerar som Nordnet när man söker och köper aktier: sök, välj, skriv antal och klicka på <b>Lägg till</b>. "
            "Skillnaden är att Avanza visar hur mycket aktierna har gått <b>upp eller ner</b> mot det du betalat. "
            "Avanza har ingen utdelningskassa. Även det här kontot kan du döpa om under <b>Kontots namn</b> överst."
        ),
        bild("22_avanza", "25 Volvo B köpta på Avanza."),
        numrerat(
            "Listan med dina aktier och <b>+/−</b> för varje aktie.",
            "<b>Plus eller minus</b> i procent och <b>Mot det du betalat</b> i kronor för den valda aktien.",
        ),
        p(
            "<b>Kontantkassan</b> ligger överst. <b>Köp fler</b> och <b>Sälj</b> finns till höger. "
            "När du säljer på Avanza går hela beloppet (minus courtage) till kontantkassan."
        ),
    )

    s.append(Paragraph("13. Översikten, kurser och PDF", H1))
    s += avsnitt(
        "Hela planen på en gång",
        p("Klicka på <b>← Översikt</b> för att gå tillbaka. Nu syns alla konton och totalsumman."),
        bild("23_oversikt_klar", "Exempelplanen: 121 805 kr på 4 konton."),
        numrerat(
            "<b>Datumhjulen</b> – rulla dag, månad och år, eller klicka på <b>förra</b> och <b>nästa</b>. "
            "Då ser du saldot vilken dag som helst, även långt fram i tiden.",
            "<b>Uppdatera alla kurser</b> – hämtar dagens börskurser för Nordnet och Avanza. Det görs också när programmet startar.",
            "<b>Spara PDF för valt datum</b> – sparar en PDF med alla konton och totalsumman för datumet i hjulen. "
            "Den sparas i mappen <i>Dokument\\Spar- och Pensionsplan</i>, om du inte valt en annan mapp under "
            "<b>Inställningar</b>. De 5 senaste för varje plan sparas.",
        ),
        p(
            "Klicka på ett konto längst ner för att öppna det direkt. Under Nordnet visas avkastningen på insatsen "
            "och under Avanza plus eller minus i procent."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("14. Inkomster", H1))
    s += avsnitt(
        "Lön, pension och behov",
        p("Klicka på <b>Inkomster</b> i menyn. Här lägger du in vad som kommer in och vad ni behöver varje månad."),
        bild("24_inkomster", "Två perioder: när båda jobbar och när båda har pension."),
        punkter(
            "Klicka på <b>+ Lägg till period</b>. Välj <b>från</b> år och månad och <b>till</b> år och månad.",
            "Skriv inkomsten för varje person (efter skatt) och <b>Behov / mån</b>, det ni behöver i månaden.",
            "<b>Över/under</b> räknas fram av sig självt: grönt när inkomsten räcker, rött när den inte räcker.",
            "Skriv en <b>anteckning</b> om du vill. <b>X</b> tar bort perioden och <b>Ångra borttagen</b> lägger tillbaka den.",
        ),
        tips("Lägg en ny period varje gång inkomsten eller behovet ändras, till exempel när någon går i pension."),
    )

    s.append(Paragraph("15. Händelser", H1))
    s += avsnitt(
        "Allt som händer, i datumordning",
        p("Klicka på <b>Händelser</b> i menyn. Här finns alla insättningar, uttag och överföringar, med den senaste överst."),
        bild("25_handelser", "Alla händelser i exempelplanen."),
        p(
            "Klicka på <b>Ändra</b> för att ändra datum eller belopp, eller på <b>Ta bort</b>. "
            "<b>Ångra borttagen</b> lägger tillbaka det du senast tog bort."
        ),
    )

    s.append(PageBreak())
    s.append(Paragraph("16. Idag och framtiden", H1))
    s += avsnitt(
        "Dagens datum – det du har nu",
        p(
            "När programmet öppnas står hjulen på <b>dagens datum</b>. Då visar översikten dina tillgångar <b>i dag</b>: "
            "startsaldon, insättningar, uttag, överföringar och aktier, alltså bara det du själv har lagt in."
        ),
        p(
            "För tiden fram till och med den här månaden lägger programmet <b>aldrig</b> till ränta eller överskott av sig självt. "
            "Det är du som bestämmer vad som verkligen har hänt."
        ),
    )
    s += avsnitt(
        "Snurra fram – framtidsutsikter",
        p(
            "När du snurrar hjulen framåt, från och med <b>nästa månad</b>, visar översikten en <b>prognos</b>. "
            "Då räknar programmet själv med:"
        ),
        punkter(
            "<b>Ränta</b> på kontona, varje månad om kontot har <b>Ränta varje månad</b> ikryssat, annars i januari året efter.",
            "<b>Överskott och underskott</b> från Inkomster. De hamnar på kontot du valt för överskott.",
            "<b>Planerade</b> insättningar, uttag och överföringar som du lagt in med ett datum längre fram.",
        ),
    )
    s += avsnitt(
        "Det du gör för hand",
        p(
            "När något verkligen har hänt lägger du in det, med banken som facit. Programmet lägger aldrig in sådant själv "
            "för tid som redan har varit:"
        ),
        punkter(
            "<b>Räntan</b> – när banken har betalat ut räntan, varje månad eller en gång om året, lägger du in den "
            "som en <b>Insättning</b> på kontot.",
            "<b>Överskott</b> – pengar som verkligen blev över och sattes in på ett konto lägger du in som en insättning eller överföring.",
            "<b>Utdelningar</b> på börskontot lägger du in under <b>Ny utdelning</b>.",
        ),
        tips(
            "Stämmer inte saldot med banken kan du också ändra kontots <b>startsaldo</b> så att dagens saldo blir rätt."
        ),
    )
    s += avsnitt(
        "Exempel: samma plan om några år",
        p(
            "I dag är summan 121 805 kr. Den 1 januari 2031 är den 368 823 kr, eftersom överskottet från Inkomster och räntan "
            "har lagts på Sparkontot. Under summan står det <i>Ränta, överskott och underskott är med i uträkningen</i> när det du ser är en prognos. Är behovet större än inkomsten blir det ett <b>underskott</b> varje månad, och då minskar summan i stället framåt i tiden."
        ),
        numrerat(
            "Hjulen står på ett datum i framtiden.",
            "<b>Samlad ränta</b> visar hur mycket ränta som är beräknad fram till det datumet.",
        ),
        bild("23b_framtid", "Samma plan den 1 januari 2031. Ränta, överskott och underskott är med i uträkningen.", utsnitt_av=(2,)),
    )

    s.append(PageBreak())
    s.append(Paragraph("17. Ränta, planer, inställningar och hjälp", H1))
    s += avsnitt(
        "Ränta",
        punkter(
            "Räntan för ett år läggs in i <b>januari året efter</b>, efter skatt.",
            "Konton där du kryssat i <b>Ränta varje månad</b> får i stället ränta varje månad (ränta på ränta).",
            "Nordnet och Avanza har ingen vanlig ränta. Deras värde räknas fram från aktierna och kassorna.",
        ),
    )
    s += avsnitt(
        "Planer och Hjälp",
        bild("26_hjalp", "1: Inställningar. 2: Hjälp öppnar den här manualen."),
        punkter(
            "Byt plan i listan <b>Plan</b> längst ner till vänster.",
            "<b>Spara kopia…</b> sparar planen som en fil, till exempel som säkerhetskopia.",
            "<b>Öppna från fil…</b> hämtar in en plan som sparats som fil.",
            "<b>Ta bort plan</b> tar bort planen som visas. Du får frågan först.",
            "<b>Hjälp</b> öppnar den här manualen. Den öppnas också automatiskt när du klickar på Ny plan.",
            "Planerna sparas i mappen <i>planer</i> i programmets installationsmapp. "
            "Använd <b>Spara kopia…</b> om du vill ha en säkerhetskopia någon annanstans.",
        ),
    )
    s += avsnitt(
        "Inställningar",
        p("Klicka på <b>Inställningar</b> längst ner till vänster."),
        bild("27_installningar", "Välj var PDF:erna sparas."),
        numrerat(
            "<b>Välj mapp…</b> – mappen där PDF:erna från översikten sparas. Från början är det <i>Dokument\\Spar- och Pensionsplan</i>.",
            "<b>Behåll bara de 5 senaste PDF:erna</b> – äldre PDF:er som programmet sparat för samma plan tas bort. "
            "Andra filer i mappen rörs aldrig.",
        ),
    )

    s.append(Paragraph("18. Vanliga frågor", H1))
    for fraga, svar in (
        ("Måste jag spara?",
         "Nej. Allt sparas automatiskt."),
        ("Måste jag lägga in räntan själv?",
         "Ja, för det som redan har hänt. När banken har betalat ut räntan lägger du in den som en insättning. "
         "För framtiden räknar programmet ut räntan åt dig. Se kapitlet <b>Idag och framtiden</b>."),
        ("Varför är summan större när jag snurrar fram i tiden?",
         "Framåt i tiden är det en prognos med ränta, överskott från Inkomster och planerade händelser. "
         "På dagens datum visas bara det du verkligen har."),
        ("Måste kontona heta Nordnet och Avanza?",
         "Nej. Programmet är inte kopplat till någon bank. Ändra namnet under <b>Kontots namn</b> överst på kontots sida. "
         "Utdelningskontot och kursvinstkontot fungerar likadant oavsett vad de heter."),
        ("Varför stämmer inte kontantkassan med Nordnet?",
         "Klicka på <b>Rätta</b> vid kontantkassan och skriv beloppet Nordnet visar. Därefter räknas köp och insättningar från det."),
        ("Varför ändras inte grundinsatsen när jag köper gratisaktier?",
         "Gratisaktier köps för utdelningspengar, inte för dina egna pengar. Därför höjer de inte grundinsatsen, "
         "men de ger mer utdelning. Då stiger avkastningen på det du själv har satt in."),
        ("Jag har sålt alla betalda aktier men har gratisaktier kvar. Var syns vinsten?",
         "Gratisaktierna har ingen grundinsats, så hela deras värde är plus. Det syns vid <b>Plus/minus nu</b>, "
         "till exempel <i>+2 400 kr (bara gratisaktier)</i>, och vid <b>Värde gratisaktier</b> till höger. "
         "Säljer du dem hamnar hela beloppet (minus courtage) i Utdelning och vinst och syns vid <b>Resultat sålda</b>."),
        ("Jag har sålt alla betalda aktier men har gratisaktier kvar. Var syns vinsten?",
         "Gratisaktierna har ingen grundinsats, så hela deras värde är plus. Det syns vid <b>Plus/minus nu</b>, "
         "till exempel <i>+2 400 kr (bara gratisaktier)</i>, och vid <b>Värde gratisaktier</b> till höger. "
         "Säljer du dem hamnar hela beloppet (minus courtage) i Utdelning och vinst och syns vid <b>Resultat sålda</b>."),
        ("Var hamnar vinsten när jag säljer?",
         "I Utdelning och vinst på Nordnet. Det du betalade för aktierna går tillbaka till kontantkassan."),
        ("Varför syns en röd text på översikten?",
         "Pengarna räcker inte en viss månad, eller så går en överföring eller ett uttag inte ihop. "
         "Kontrollera Inkomster och Händelser."),
        ("Behövs internet?",
         "Bara för att söka aktier och hämta börskurser. Allt annat fungerar utan."),
    ):
        s.append(KeepTogether([Paragraph(f"<b>{fraga}</b>", TEXT), p(svar), Spacer(1, 0.15 * cm)]))

    s += [
        Spacer(1, 0.4 * cm),
        tips("Gillar du programmet? Swisha gärna 100 kr till <b>070-091 33 10</b>. Tack för att du använder det!"),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Programmet är ett planeringsverktyg och inte finansiell rådgivning. Resultaten är uppskattningar "
            "utifrån de värden du anger.",
            BILDTEXT,
        ),
    ]

    doc.build(_kapitel_ihop(s), onFirstPage=sidfot, onLaterPages=sidfot)
    print(f"Skapade {OUT}")


if __name__ == "__main__":
    build_manual()
