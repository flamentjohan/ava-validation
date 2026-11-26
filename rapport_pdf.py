"""Génération du PDF « Dashboard AVA » (mode reporting, 12 ou 24 mois glissants)."""
import re
from datetime import datetime, timedelta, date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, String, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, PageBreak)


NAVY = colors.HexColor("#1f3a5f")
NAVY_DARK = colors.HexColor("#16293f")
TEAL = colors.HexColor("#0e7490")
GREEN = colors.HexColor("#2e7d32")
ORANGE = colors.HexColor("#ef6c00")
LIGHT = colors.HexColor("#f5f7fa")
BORDER = colors.HexColor("#dde4ea")
MUTED = colors.HexColor("#6b7a87")
MINUS = 0.000001


def _parse_gain(value):
    if not value:
        return 0.0
    cleaned = re.sub(r"[^\d.,-]", "", str(value)).replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def collect(db, mois):
    start = date.today() - timedelta(days=int(round(mois * 30.44)))
    projects = [p for p in db.execute(
        "SELECT * FROM projects ORDER BY created_at").fetchall()
        if (c := _parse_dt(p["created_at"])) and c.date() >= start]
    validators = {}
    for v in db.execute("SELECT * FROM validators ORDER BY id").fetchall():
        validators.setdefault(v["project_id"], []).append(v)

    n = len(projects)
    inter_ok = [p for p in projects if p["status"] in ("phase_externe", "valide")]
    exter_ok = [p for p in projects if p["status"] == "valide"]
    refuses = [p for p in projects if p["status"] == "refuse"]
    en_cours = [p for p in projects
                if p["status"] in ("phase_interne", "phase_externe")]

    gain_propose = sum(_parse_gain(p["total_gain"]) for p in projects)
    gain_valide = sum(_parse_gain(p["total_gain"]) for p in exter_ok)

    up_projets, up_gain = {}, {}
    for p in projects:
        key = p["up"] or "Non renseignée"
        up_projets[key] = up_projets.get(key, 0) + 1
        up_gain[key] = up_gain.get(key, 0.0) + _parse_gain(p["total_gain"])

    inter_days, exter_days = [], []
    for p in projects:
        vs = validators.get(p["id"], [])
        created = _parse_dt(p["created_at"])
        inter = [x for x in vs if x["grp"] == "interne_agro" and x["email"]]
        exter = [x for x in vs if x["grp"] == "itmai" and x["email"]]
        inter_dates = sorted(_parse_dt(x["answered_at"]) for x in inter
                             if x["status"] == "valide" and x["answered_at"])
        if created and inter and len(inter_dates) == len(inter) \
                and p["status"] in ("phase_externe", "valide"):
            inter_days.append((inter_dates[-1] - created).days)
        exter_dates = sorted(_parse_dt(x["answered_at"]) for x in exter
                             if x["status"] == "valide" and x["answered_at"])
        if inter_dates and exter and len(exter_dates) == len(exter) \
                and p["status"] == "valide":
            exter_days.append((exter_dates[-1] - inter_dates[-1]).days)

    def avg(days):
        return round(sum(days) / len(days), 1) if days else 0.0

    return {
        "mois": mois,
        "debut": start.strftime("%d/%m/%Y"),
        "fin": date.today().strftime("%d/%m/%Y"),
        "n": n,
        "n_inter": len(inter_ok),
        "pct_inter": round(100 * len(inter_ok) / n, 1) if n else 0.0,
        "n_exter": len(exter_ok),
        "pct_exter": round(100 * len(exter_ok) / n, 1) if n else 0.0,
        "n_refuse": len(refuses),
        "n_encours": len(en_cours),
        "gain_propose": gain_propose,
        "gain_valide": gain_valide,
        "pct_gain": (round(100 * gain_valide / gain_propose, 1)
                     if gain_propose > MINUS else 0.0),
        "up_projets": up_projets,
        "up_gain": up_gain,
        "delai_inter": avg(inter_days),
        "delai_exter": avg(exter_days),
    }


def _st(name, **kw):
    base = {"fontName": "Helvetica", "fontSize": 9, "leading": 12}
    base.update(kw)
    return ParagraphStyle(name, **base)


def _section(num, title):
    t = Table([[
        Paragraph(f'<font color="white"><b>{num}</b></font>',
                  _st("n", fontSize=13, leading=15, alignment=1)),
        Paragraph(f'<font color="#1f3a5f"><b>{title}</b></font>',
                  _st("t", fontSize=13, leading=16)),
    ]], colWidths=[9 * mm, 171 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), NAVY),
        ("BACKGROUND", (1, 0), (1, 0), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _kpi_card(label, value, sub, accent):
    hexa = "#" + accent.hexval()[2:]
    inner = Table([
        [Paragraph(f'<font color="#6b7a87"><b>{label.upper()}</b></font>',
                   _st("kl", fontSize=7, leading=9))],
        [Paragraph(f'<font color="{hexa}"><b>{value}</b></font>',
                   _st("kv", fontSize=17, leading=20))],
        [Paragraph(f'<font color="#6b7a87">{sub}</font>',
                   _st("ks", fontSize=7.5, leading=9))],
    ], colWidths=[41 * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return inner


def _kpi_row(cards):
    row = Table([cards], colWidths=[46 * mm] * len(cards))
    row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return row


def _progress(pct, label_left, label_right, accent):
    pct = min(max(pct, 0), 100)
    d = Drawing(180 * mm, 9 * mm)
    bg = Rect(0, 1, 130 * mm, 5.5 * mm, rx=2.75 * mm, ry=2.75 * mm,
              fillColor=colors.HexColor("#e9eef3"), strokeColor=None)
    fg = Rect(0, 1, 130 * mm * pct / 100, 5.5 * mm, rx=2.75 * mm,
              ry=2.75 * mm, fillColor=accent, strokeColor=None)
    d.add(bg)
    if pct > 0:
        d.add(fg)
    d.add(String(133 * mm, 2.2 * mm, f"{pct} %".replace(".", ","),
                 fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    d.add(String(0, 8 * mm, label_left, fontName="Helvetica-Bold",
                 fontSize=7.5, fillColor=MUTED))
    d.add(String(180 * mm, 8 * mm, label_right, fontName="Helvetica",
                 fontSize=7.5, fillColor=MUTED, textAnchor="end"))
    return d


def _bar_chart(cats, values, title, accent, fmt_labels=None):
    d = Drawing(88 * mm, 66 * mm)
    d.add(Rect(0, 0, 88 * mm, 62 * mm, rx=3 * mm, ry=3 * mm,
               fillColor=colors.white, strokeColor=BORDER, strokeWidth=0.6))
    d.add(String(44 * mm, 60 * mm, title, fontName="Helvetica-Bold",
                 fontSize=9.5, textAnchor="middle", fillColor=NAVY))
    chart = VerticalBarChart()
    chart.x, chart.y = 13 * mm, 12 * mm
    chart.width, chart.height = 68 * mm, 44 * mm
    chart.categoryAxis.categoryNames = cats or ["—"]
    chart.categoryAxis.labels.fontSize = 5.8
    chart.categoryAxis.labels.fillColor = MUTED
    chart.categoryAxis.strokeColor = BORDER
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = (max(values) * 1.25 or 1) if values else 1
    chart.valueAxis.valueStep = max(chart.valueAxis.valueMax / 4, 1)
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.strokeColor = BORDER
    chart.bars[0].fillColor = accent
    chart.bars[0].strokeColor = None
    chart.barLabels.fontSize = 6.5
    chart.barLabels.fillColor = NAVY
    chart.barLabels.nudge = 7
    chart.barLabelFormat = fmt_labels or "%.0f"
    chart.data = [values or [0]]
    d.add(chart)
    return d


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(15 * mm, 12 * mm, 195 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(15 * mm, 8 * mm, "Application AVA — Suivi des projets")
    canvas.drawRightString(
        195 * mm, 8 * mm,
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
    canvas.drawCentredString(105 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(db, mois):
    data = collect(db, mois)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm,
                            bottomMargin=18 * mm, leftMargin=15 * mm,
                            rightMargin=15 * mm, title="Dashboard AVA")
    story = []

    band = Table([[
        Paragraph('<font color="white" size="22"><b>DASHBOARD AVA</b></font>',
                  _st("h", fontSize=22, leading=26)),
        Paragraph(
            f'<font color="#d7e3f4" size="9"><b>Reporting sur '
            f'{data["mois"]} mois glissants</b><br/>'
            f'Du {data["debut"]} au {data["fin"]}</font>',
            _st("hs", fontSize=9, leading=13, alignment=2)),
    ]], colWidths=[120 * mm, 60 * mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 3, ORANGE),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(band)
    story.append(Spacer(1, 5 * mm))

    story.append(_section("1", "Vue d'ensemble de la période"))
    story.append(Spacer(1, 3 * mm))
    story.append(_kpi_row([
        _kpi_card("Projets créés", str(data["n"]), "sur la période", NAVY),
        _kpi_card("Validés en interne",
                  f'{data["n_inter"]}',
                  f'soit {str(data["pct_inter"]).replace(".", ",")} % des '
                  f'projets', ORANGE),
        _kpi_card("Validés ITMAI", str(data["n_exter"]),
                  f'soit {str(data["pct_exter"]).replace(".", ",")} % des '
                  f'projets', GREEN),
        _kpi_card("Refusés", str(data["n_refuse"]),
                  f'{data["n_encours"]} encore en cours',
                  colors.HexColor("#c62828")),
    ]))
    story.append(Spacer(1, 5 * mm))

    story.append(_section("2", "Avancement de la validation"))
    story.append(Spacer(1, 3 * mm))
    t = Table([[Paragraph(
        "Part des projets dont tous les valideurs internes Agro ont validé :",
        _st("p", fontSize=8.5, leading=11))],
        [_progress(data["pct_inter"], "VALIDATION INTERNE AGRO",
                   f'{data["n_inter"]} / {data["n"]} projets', ORANGE)],
        [Paragraph(
            "Part des projets validés par l'ensemble du workflow "
            "(internes + ITMAI) :", _st("p2", fontSize=8.5, leading=11))],
        [_progress(data["pct_exter"], "VALIDATION TOTALE (ITMAI)",
                   f'{data["n_exter"]} / {data["n"]} projets', GREEN)]],
        colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, 3), (-1, 3), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    story.append(_section("3", "Gains"))
    story.append(Spacer(1, 3 * mm))
    fmt_gain = lambda g: f"{g:,.0f}".replace(",", " ") + " €"
    story.append(_kpi_row([
        _kpi_card("Gain total proposé", fmt_gain(data["gain_propose"]),
                  "ensemble des projets", NAVY),
        _kpi_card("Gain total validé", fmt_gain(data["gain_valide"]),
                  "projets validés", GREEN),
        _kpi_card("Gain validé / proposé",
                  f'{str(data["pct_gain"]).replace(".", ",")} %',
                  "part du gain validé", TEAL),
    ]))
    story.append(Spacer(1, 3 * mm))
    story.append(_progress(data["pct_gain"], "CONCRÉTISATION DU GAIN",
                           fmt_gain(data["gain_valide"]), TEAL))
    story.append(PageBreak())

    story.append(_section("4", "Répartition par UP"))
    story.append(Spacer(1, 3 * mm))
    cats = sorted(data["up_projets"], key=lambda c: -data["up_projets"][c])
    cats2 = sorted(data["up_gain"], key=lambda c: -data["up_gain"][c])
    charts = Table(
        [[_bar_chart(cats, [data["up_projets"][c] for c in cats],
                     "Nombre de projets par UP", NAVY),
          _bar_chart(cats2, [round(data["up_gain"][c] / 1000, 1)
                             for c in cats2],
                     "Gain par UP (en k€)", GREEN,
                     fmt_labels="%.0f")]],
        colWidths=[90 * mm, 90 * mm])
    charts.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(charts)
    story.append(Spacer(1, 5 * mm))

    story.append(_section("5", "Réactivité du circuit de validation"))
    story.append(Spacer(1, 3 * mm))
    story.append(_kpi_row([
        _kpi_card("Validation interne",
                  f'{str(data["delai_inter"]).replace(".", ",")} j',
                  "délai moyen jusqu'à validation complète", ORANGE),
        _kpi_card("Validation ITMAI",
                  f'{str(data["delai_exter"]).replace(".", ",")} j',
                  "délai moyen phase externe", ORANGE),
        _kpi_card("Délai total moyen",
                  f'{str(round(data["delai_inter"] + data["delai_exter"], 1)).replace(".", ",")} j',
                  "de la création à la validation finale", NAVY),
    ]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buf.seek(0)
    return buf
