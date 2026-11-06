"""PDF med alla konton, saldot och summan för ett valt datum."""

from __future__ import annotations

from pathlib import Path

from plan_engine import formatera_kr

_FONT_KLAR = False
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

_BLA = "#16343F"
_GRON = "#2A9D8F"
_GRON_MORK = "#1E7A70"
_TEXT = "#17323C"
_MUTED = "#6B7C83"
_LINJE = "#E4DCCB"
_RAD = "#F7F4EE"
_SUMMA = "#E7F4F1"
_VIT = "#FFFFFF"


def _pdf_text(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _sakerstall_font() -> tuple[str, str]:
    global _FONT_KLAR, _FONT, _FONT_BOLD
    if _FONT_KLAR:
        return _FONT, _FONT_BOLD
    _FONT_KLAR = True
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    par = [
        (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf")),
        (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
    ]
    for regular, bold in par:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("PP", str(regular)))
            pdfmetrics.registerFont(TTFont("PP-Bold", str(bold)))
            _FONT, _FONT_BOLD = "PP", "PP-Bold"
            break
    return _FONT, _FONT_BOLD


def skriv_kontoutdrag_pdf(
    sokvag: Path,
    *,
    plan_namn: str,
    datum_text: str,
    konton: list[tuple[int, str, int]],
    varning: str = "",
) -> None:
    """Skriv en sida med kontona, saldot på vart och ett, och summan."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, font_bold = _sakerstall_font()
    sokvag = Path(sokvag)
    sokvag.parent.mkdir(parents=True, exist_ok=True)
    bla = colors.HexColor(_BLA)
    gron = colors.HexColor(_GRON)
    textfarg = colors.HexColor(_TEXT)
    muted = colors.HexColor(_MUTED)
    linje = colors.HexColor(_LINJE)
    radfarg = colors.HexColor(_RAD)
    summafarg = colors.HexColor(_SUMMA)
    vit = colors.HexColor(_VIT)

    def stil(namn: str, **kwargs) -> ParagraphStyle:
        bas = {"fontName": font, "textColor": textfarg, "leading": 14}
        bas.update(kwargs)
        return ParagraphStyle(namn, **bas)

    huvud_v = stil("HuvudV", fontName=font_bold, fontSize=9, leading=12, textColor=vit)
    huvud_h = stil("HuvudH", fontName=font_bold, fontSize=9, leading=12, textColor=vit, alignment=2)
    namn_stil = stil("Namn", fontSize=11, leading=14)
    belopp_stil = stil("Belopp", fontSize=11, leading=14, alignment=2)
    summa_namn = stil("SummaNamn", fontName=font_bold, fontSize=13, leading=16, textColor=bla)
    summa_belopp = stil("SummaBelopp", fontName=font_bold, fontSize=13, leading=16, textColor=bla, alignment=2)
    varning_stil = stil("Varning", fontSize=9, leading=12, textColor=colors.HexColor("#B03A2E"), spaceBefore=2, spaceAfter=8)

    def p(text: str, style: ParagraphStyle) -> Paragraph:
        return Paragraph(_pdf_text(text), style)

    total = sum(saldo for _nr, _namn, saldo in konton)
    data = [[p("KONTO", huvud_v), p("SALDO", huvud_h)]]
    for _nr, namn, saldo in konton:
        data.append([p(namn, namn_stil), p(formatera_kr(saldo), belopp_stil)])
    data.append([p("Summa", summa_namn), p(formatera_kr(total), summa_belopp)])

    bredd = A4[0] - 3.6 * cm
    tabell = Table(data, colWidths=[bredd * 0.68, bredd * 0.32])
    kommandon = [
        ("BACKGROUND", (0, 0), (-1, 0), bla),
        ("BACKGROUND", (0, -1), (-1, -1), summafarg),
        ("TEXTCOLOR", (0, 0), (-1, 0), vit),
        ("LINEBELOW", (0, 0), (-1, 0), 0, bla),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, gron),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, linje),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -2), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 9),
        ("TOPPADDING", (0, -1), (-1, -1), 12),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            kommandon.append(("BACKGROUND", (0, i), (-1, i), radfarg))
        else:
            kommandon.append(("BACKGROUND", (0, i), (-1, i), vit))
    tabell.setStyle(TableStyle(kommandon))

    story = []
    if varning.strip():
        story.append(p(varning.strip(), varning_stil))
    story.append(tabell)
    story.append(Spacer(1, 0.45 * cm))
    story.append(p(
        f"{len(konton)} konton  ·  {datum_text}",
        stil("Fotnot", fontSize=9, leading=12, textColor=muted),
    ))

    def sidhuvud(canvas, _doc) -> None:
        canvas.saveState()
        bredd_sida, hojd = A4
        canvas.setFillColor(bla)
        canvas.rect(0, hojd - 3.35 * cm, bredd_sida, 3.35 * cm, fill=1, stroke=0)
        canvas.setFillColor(gron)
        canvas.rect(0, hojd - 3.5 * cm, bredd_sida, 0.15 * cm, fill=1, stroke=0)
        canvas.setFillColor(vit)
        canvas.setFont(font_bold, 9)
        canvas.drawString(1.8 * cm, hojd - 1.15 * cm, "PENSIONSPLAN")
        canvas.setFont(font_bold, 16)
        canvas.drawString(1.8 * cm, hojd - 1.9 * cm, plan_namn)
        canvas.setFillColor(colors.HexColor("#D7EBE7"))
        canvas.setFont(font, 11)
        canvas.drawString(1.8 * cm, hojd - 2.65 * cm, datum_text)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(sokvag),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=4.2 * cm,
        bottomMargin=1.8 * cm,
        title=f"Konton {datum_text}",
        author="Spar- och Pensionsplan",
    )
    doc.build(story, onFirstPage=sidhuvud, onLaterPages=sidhuvud)
