"""Update slides 9-11 of Aster_Group_7_Final_v2.pptx (content only)."""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor

ROOT = Path(r"D:\courses\5057\aster_develop")
SRC = ROOT / "slides/Aster_Group_7_Final_v2.pptx"
BACKUP = ROOT / "slides/Aster_Group_7_Final_v2_backup_20261127.pptx"
PROJECT = ROOT / "Aster_5057_whh"


def set_text(slide, name: str, text: str, run_index: int = 0) -> None:
    for shape in slide.shapes:
        if shape.name == name and shape.has_text_frame:
            paragraph = shape.text_frame.paragraphs[0]
            if len(paragraph.runs) > run_index:
                paragraph.runs[run_index].text = text
                return
    raise KeyError(f"shape/run not found: {name}[{run_index}]")


def set_cell(table, row: int, col: int, text: str, run_index: int = 0) -> None:
    paragraph = table.cell(row, col).text_frame.paragraphs[0]
    paragraph.runs[run_index].text = text


def chart_payload():
    import json
    from datetime import datetime

    payload = json.loads(
        (PROJECT / "run/deck_chart_data.json").read_text(encoding="utf-8")
    )
    labels = []
    last_year = None
    for index, value in enumerate(payload["dates"]):
        day = datetime.strptime(value, "%Y-%m-%d")
        if index == 0 or (day.month == 1 and day.year != last_year):
            labels.append(day.strftime("'%y"))
        else:
            labels.append("")
        last_year = day.year
    labels[-1] = datetime.strptime(payload["dates"][-1], "%Y-%m-%d").strftime("'%y")
    return labels, payload["aster"], payload["bench"]


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(SRC, BACKUP)
    presentation = Presentation(SRC)

    # ---------------- Slide 9 ----------------
    slide = presentation.slides[8]
    tables = {shape.name: shape.table for shape in slide.shapes if shape.has_table}
    settings = tables["Table 30"]
    set_cell(settings, 1, 1, "4 Jan 2022 – 23 Nov 2026 · 1,183 trading ", 0)
    set_cell(settings, 1, 1, "dates", 1)
    set_cell(settings, 2, 1, "Market Data; PIT Fiscal Data; Filings; 72-factor library")
    setup = tables["Table 31"]
    set_cell(setup, 2, 1, "CSI 500 (IC) index futures")
    set_cell(setup, 3, 1, "Tactical beta, market-neutral to index-enhanced")
    set_cell(setup, 4, 1, "Net −50% to +20%, gross up to 166%")
    set_cell(setup, 5, 1, "Monthly council, 5-day rebalance")

    # ---------------- Slide 10 ----------------
    slide = presentation.slides[9]
    set_text(slide, "TextBox 10", "72")
    set_text(slide, "TextBox 11", "factors in the library")
    set_text(slide, "TextBox 12", "8")
    set_text(slide, "TextBox 13", "filing-derived factors")
    set_text(slide, "TextBox 14", "From 44 mined and validated QuantaAlpha factors.")
    set_text(slide, "TextBox 16", "COUNCIL'S 2026 CRASH CALL")
    set_text(slide, "TextBox 17", "July 2026")
    set_text(
        slide,
        "TextBox 18",
        "The council cut equity, lifted the hedge and underweighted tech before the CSI 500 fell 17%.",
    )
    set_text(slide, "TextBox 20", "78%")
    set_text(slide, "TextBox 22", "59%")
    set_text(slide, "TextBox 24", "25%")
    set_text(slide, "TextBox 26", "73%")
    set_text(slide, "TextBox 27", "CSI 500: −17% in July 2026.")

    # ---------------- Slide 11 ----------------
    slide = presentation.slides[10]
    set_text(slide, "TextBox 21", "+73.7%")
    set_text(slide, "TextBox 22", "five years, after costs")
    set_text(slide, "TextBox 25", "12.5%")
    set_text(slide, "TextBox 29", "−9.85%")
    set_text(slide, "TextBox 30", "trough 22 Mar 2024")
    set_text(slide, "TextBox 33", "1.14")
    set_text(slide, "TextBox 36", "CSI 500 price  −16.66%   ·   index drawdown  −39.5% (derived)")
    set_text(slide, "TextBox 37", "Price index only; total-return and financing differences are not modelled.")
    set_text(slide, "TextBox 39", "2026 SHOWCASE · 214 SESSIONS · HINDSIGHT REENACTMENT")
    set_text(slide, "TextBox 40", "+16.8%")
    for shape in slide.shapes:
        if shape.name == "TextBox 40" and shape.has_text_frame:
            for run in shape.text_frame.paragraphs[0].runs:
                run.font.color.rgb = RGBColor(0x08, 0x7F, 0x8C)
    set_text(slide, "TextBox 41", "vs CSI 500 −19.89%   ·   max drawdown −6.58%")
    set_text(slide, "TextBox 43", "−0.07")
    set_text(slide, "TextBox 45", "52.2%")
    set_text(slide, "TextBox 47", "165.7%")
    set_text(slide, "TextBox 49", "15.2%")
    set_text(slide, "TextBox 51", "14.7×")
    set_text(
        slide,
        "TextBox 53",
        "Showcase reenactment with hindsight; after trading and roll costs, before fund fees · not live, not audited · AI contribution not isolated.",
    )

    chart = next(shape.chart for shape in slide.shapes if shape.has_chart)
    categories, ast, bench = chart_payload()
    data = CategoryChartData()
    data.categories = categories
    data.add_series("Aster", ast)
    data.add_series("CSI 500 price", bench)
    chart.replace_data(data)
    for series, color in zip(chart.series, ("087F8C", "142D4E")):
        series.format.line.color.rgb = RGBColor.from_string(color)
    chart.value_axis.minimum_scale = 60
    chart.value_axis.maximum_scale = 180
    chart.value_axis.major_unit = 20

    presentation.save(SRC)
    print("saved", SRC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
