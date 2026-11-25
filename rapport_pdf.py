"""Génération du PDF « Dashboard AVA » (mode reporting, 12 ou 24 mois glissants)."""
import re
from datetime import datetime, timedelta, date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)


NAVY = colors.HexColor("#1f3a5f")
GREEN = colors.HexColor("#2e7d32")
ORANGE = colors.HexColor("#ef6c00")
LIGHT = colors.HexColor("#f4f6f8")
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
        "gain_propose": gain_propose,
        "gain_valide": gain_valide,
        "pct_gain": (round(100 * gain_valide / gain_propose, 1)
                     if gain_propose > MINUS else 0.0),
        "up_projets": up_projets,
        "up_gain": up_gain,
        "delai_inter": avg(inter_days),
        "delai_exter": avg(exter_days),
    }


def _kpi(label, value, accent):
    hexa = "#" + accent.hexval()[2:]
    return [Paragraph(f'<font color="#6b7a87">{label}</font>',
                      ParagraphStyle("l", fontSize=8, leading=10)),
            Paragraph(f'<font color="{hexa}"><b>{value}</b></font>',
                      ParagraphStyle("v", fontSize=14, leading=17))]


def _bar_chart(cats, values, title, accent):
    d = Drawing(340, 210)
    chart = VerticalBarChart()
    chart.x, chart.y = 45, 35
    chart.width, chart.height = 270, 140
    chart.categoryAxis.categoryNames = cats
    chart.categoryAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = (max(values) * 1.2 or 1) if values else 1
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = accent
    chart.bars[0].strokeColor = accent
    chart.data = [values or [0]]
    d.add(chart)
    d.add(String(170, 195, title, fontName="Helvetica-Bold", fontSize=10,
                 textAnchor="middle", fillColor=NAVY))
    return d


def build_pdf(db, mois):
    data = collect(db, mois)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm,
                            bottomMargin=15 * mm, leftMargin=15 * mm,
                            rightMargin=15 * mm, title="Dashboard AVA")
    story = []

    header = Paragraph('<font color="white"><b>DASHBOARD AVA</b></font>',
                       ParagraphStyle("h", fontSize=20, leading=24,
                                      alignment=1))
    sub = Paragraph(
        f'<font color="#d7e3f4">Reporting sur {data["mois"]} mois glissants'
        f' — du {data["debut"]} au {data["fin"]}</font>',
        ParagraphStyle("s", fontSize=10, leading=14, alignment=1))
    header_tbl = Table([[header], [sub]], colWidths=[180 * mm])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 8 * mm))

    fmt = lambda g: f"{g:,.0f}".replace(",", " ") + " €"
    kpis = [
        _kpi("Projets créés", data["n"], NAVY),
        _kpi("Validés en interne", f'{data["n_inter"]} ({data["pct_inter"]} %)',
             ORANGE),
        _kpi("Validés (ITMAI)", f'{data["n_exter"]} ({data["pct_exter"]} %)',
             GREEN),
        _kpi("Gain total proposé", fmt(data["gain_propose"]), NAVY),
        _kpi("Gain total validé", fmt(data["gain_valide"]), GREEN),
        _kpi("Gain validé / proposé", f'{data["pct_gain"]} %', GREEN),
        _kpi("Validation interne moyenne", f'{data["delai_inter"]} jours',
             ORANGE),
        _kpi("Validation ITMAI moyenne", f'{data["delai_exter"]} jours',
             ORANGE),
    ]
    grid = [kpis[i:i + 2] for i in range(0, len(kpis), 2)]
    kpi_tbl = Table(grid, colWidths=[90 * mm, 90 * mm])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#dde4ea")),
        ("INNERGRID", (0, 0), (-1, -1), 0.75, colors.HexColor("#dde4ea")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 8 * mm))

    cats = sorted(data["up_projets"], key=lambda c: -data["up_projets"][c])
    story.append(_bar_chart(cats, [data["up_projets"][c] for c in cats],
                            "Nombre de projets par UP", NAVY))
    story.append(Spacer(1, 6 * mm))
    cats2 = sorted(data["up_gain"], key=lambda c: -data["up_gain"][c])
    story.append(_bar_chart(cats2, [round(data["up_gain"][c] / 1000, 1)
                                    for c in cats2],
                            "Gain par UP (en k€)", GREEN))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        '<font size="8" color="#6b7a87">Validés en interne : projets dont tous '
        'les valideurs internes Agro renseignés ont validé. Validés (ITMAI) : '
        'projets validés par l\'ensemble du workflow. Temps moyens calculés à '
        'partir des dates de validation enregistrées.</font>',
        ParagraphStyle("note", fontSize=8, leading=11)))
    doc.build(story)
    buf.seek(0)
    return buf
