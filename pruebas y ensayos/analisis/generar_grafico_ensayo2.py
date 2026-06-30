#!/usr/bin/env python3
"""Genera un PDF con series temporales del segundo ensayo.

El script usa solamente la biblioteca estandar de Python. Lee registros JSONL
de AHT10, XTRA2210 y WindSonic, filtra el segundo ensayo y escribe un PDF
vectorial en la carpeta ``pruebas y ensayos/graficos``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Parametros editables
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PDF = REPORT_DIR / "graficos" / "ensayo2_aht10_xtra2210_windsonic.pdf"

ENSAYO_INICIO = datetime.fromisoformat("2026-06-25T09:50:01-03:00")
ENSAYO_FIN = datetime.fromisoformat("2026-06-29T15:40:29-03:00")
TIMEZONE_LABEL = "UTC-3"

PAGE_WIDTH = 842.0   # A4 horizontal, puntos PDF.
PAGE_HEIGHT = 595.0
MARGIN_LEFT = 64.0
MARGIN_RIGHT = 28.0
MARGIN_TOP = 56.0
MARGIN_BOTTOM = 48.0
PANEL_GAP = 18.0
PANEL_TITLE_GAP = 36.0

TITLE = "Segundo ensayo de integración con panel solar y batería"
SUBTITLE = "25/06/2026 09:50 a 29/06/2026 15:40 (UTC-3)"
FONT_SIZE_TITLE = 18
FONT_SIZE_SUBTITLE = 15
FONT_SIZE_LABEL = 13
FONT_SIZE_TICK = 13

AXIS_COLOR = (0.18, 0.18, 0.18)
GRID_COLOR = (0.82, 0.82, 0.82)
TEXT_COLOR = (0.10, 0.10, 0.10)
LINE_WIDTH = 0.9
AXIS_WIDTH = 0.45
GRID_WIDTH = 0.25

TIME_TICK_HOURS = 6
Y_TICK_COUNT = 4
Y_PADDING_FRACTION = 0.08

COLORS = {
    "aht_temp": (0.70, 0.23, 0.28),
    "aht_humidity": (0.16, 0.47, 0.71),
    "battery_voltage": (0.23, 0.49, 0.27),
    "pv_voltage": (0.85, 0.57, 0.00),
    "load_current": (0.36, 0.30, 0.49),
    "pv_current": (0.78, 0.36, 0.18),
    "battery_soc": (0.18, 0.28, 0.35),
    "wind_speed": (0.00, 0.55, 0.55),
}

# Cada panel puede contener una o mas curvas con la misma unidad.
# Para agregar/quitar curvas, editar esta lista.
PANELS = [
    ##
    #{
    #    "title": "AHT10 - humedad relativa",
    #    "file": "aht10_readings.jsonl",
    #    "ylabel": "%",
    #    "series": [("humidity_rh", "Humedad", COLORS["aht_humidity"])],
    #},
    {
        "title": "XTRA2210 - tensiones",
        "file": "xtra2210_readings.jsonl",
        "ylabel": "V",
        "series": [
            ("battery_voltage_v", "Batería", COLORS["battery_voltage"]),
            ("pv_voltage_v", "Panel", COLORS["pv_voltage"]),
        ],
    },
    {
        "title": "XTRA2210 - corrientes",
        "file": "xtra2210_readings.jsonl",
        "ylabel": "A",
        "series": [
            ("load_current_a", "Carga", COLORS["load_current"]),
            ("pv_current_a", "Panel", COLORS["pv_current"]),
        ],
    },
    {
        "title": "XTRA2210 - estado de carga",
        "file": "xtra2210_readings.jsonl",
        "ylabel": "%",
        "ylim": (0.0, 100.0),
        "series": [("battery_soc_pct", "SoC", COLORS["battery_soc"])],
    },
    #{
    #    "title": "WindSonic - velocidad de viento",
    #    "file": "windsonic_readings.jsonl",
    #    "ylabel": "m/s",
   #     "series": [("wind_speed_mps_avg", "Velocidad media", COLORS["wind_speed"])],
  #  },
]


# ---------------------------------------------------------------------------
# Lectura de datos
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                timestamp = datetime.fromisoformat(item["timestamp"])
                if ENSAYO_INICIO <= timestamp <= ENSAYO_FIN:
                    rows.append({"timestamp": timestamp, **item.get("data", {})})
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ValueError(f"No se pudo leer {path}:{line_number}: {exc}") from exc
    return rows


def extract_series(rows: list[dict], field: str) -> list[tuple[datetime, float]]:
    values: list[tuple[datetime, float]] = []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append((row["timestamp"], number))
    return values


# ---------------------------------------------------------------------------
# Utilidades PDF
# ---------------------------------------------------------------------------

def pdf_escape(text: str) -> str:
    escaped: list[str] = []
    for character in text:
        code = ord(character)
        if character in {"\\", "(", ")"}:
            escaped.append("\\" + character)
        elif 32 <= code <= 126:
            escaped.append(character)
        elif code <= 255:
            escaped.append(f"\\{code:03o}")
        else:
            escaped.append("?")
    return "".join(escaped)


def rgb(color: tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}"


class PdfCanvas:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        self.commands: list[str] = []

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = AXIS_COLOR,
        width: float = AXIS_WIDTH,
    ) -> None:
        self.commands.append(f"{rgb(color)} RG {width:.3f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def polyline(
        self,
        points: list[tuple[float, float]],
        color: tuple[float, float, float],
        width: float = LINE_WIDTH,
    ) -> None:
        if len(points) < 2:
            return
        chunks = [f"{rgb(color)} RG {width:.3f} w {points[0][0]:.2f} {points[0][1]:.2f} m"]
        chunks.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
        chunks.append("S")
        self.commands.append(" ".join(chunks))

    def text(
        self,
        x: float,
        y: float,
        text: str,
        size: float = FONT_SIZE_LABEL,
        color: tuple[float, float, float] = TEXT_COLOR,
        align: str = "left",
    ) -> None:
        safe = pdf_escape(text)
        approx_width = 0.50 * size * len(text)
        if align == "center":
            x -= approx_width / 2
        elif align == "right":
            x -= approx_width
        self.commands.append(f"BT {rgb(color)} rg /F1 {size:.1f} Tf {x:.2f} {y:.2f} Td ({safe}) Tj ET")

    def save(self, path: Path) -> None:
        content = "\n".join(self.commands).encode("latin-1", errors="replace")
        objects: list[bytes] = []
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.width:.0f} {self.height:.0f}] "
            f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ).encode("ascii")
        objects.append(page)
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

        output = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode("ascii"))
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
        )
        path.write_bytes(output)


# ---------------------------------------------------------------------------
# Escalas y dibujo
# ---------------------------------------------------------------------------

def nice_ticks(y_min: float, y_max: float, count: int) -> list[float]:
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0
    step = (y_max - y_min) / max(count, 1)
    return [y_min + i * step for i in range(count + 1)]


def y_limits(series_values: list[list[tuple[datetime, float]]], panel: dict) -> tuple[float, float]:
    if "ylim" in panel:
        return panel["ylim"]
    values = [value for serie in series_values for _, value in serie]
    if not values:
        return 0.0, 1.0
    y_min = min(values)
    y_max = max(values)
    if y_min == y_max:
        return y_min - 1.0, y_max + 1.0
    padding = (y_max - y_min) * Y_PADDING_FRACTION
    return y_min - padding, y_max + padding


def draw_panel(
    canvas: PdfCanvas,
    panel: dict,
    rows_cache: dict[str, list[dict]],
    x0: float,
    y0: float,
    width: float,
    height: float,
    show_x_labels: bool,
) -> None:
    rows = rows_cache[panel["file"]]
    prepared = [(label, color, extract_series(rows, field)) for field, label, color in panel["series"]]
    values = [serie for _, _, serie in prepared]
    y_min, y_max = y_limits(values, panel)

    plot_left = x0 + 44.0
    plot_right = x0 + width
    plot_bottom = y0 + 18.0
    plot_top = y0 + height - PANEL_TITLE_GAP
    plot_width = plot_right - plot_left
    plot_height = plot_top - plot_bottom

    start_s = ENSAYO_INICIO.timestamp()
    span_s = ENSAYO_FIN.timestamp() - start_s

    def map_x(timestamp: datetime) -> float:
        return plot_left + ((timestamp.timestamp() - start_s) / span_s) * plot_width

    def map_y(value: float) -> float:
        return plot_bottom + ((value - y_min) / (y_max - y_min)) * plot_height

    canvas.text(x0, y0 + height - 8.0, panel["title"], size=FONT_SIZE_LABEL + 1)
    canvas.text(x0, plot_top + 8.0, panel["ylabel"], size=FONT_SIZE_TICK)

    for tick in nice_ticks(y_min, y_max, Y_TICK_COUNT):
        y = map_y(tick)
        canvas.line(plot_left, y, plot_right, y, GRID_COLOR, GRID_WIDTH)
        canvas.text(plot_left - 6.0, y - 2.5, f"{tick:.2g}", size=FONT_SIZE_TICK, align="right")

    tick_time = ENSAYO_INICIO.replace(minute=0, second=0, microsecond=0)
    while tick_time < ENSAYO_INICIO:
        tick_time += timedelta(hours=TIME_TICK_HOURS)
    while tick_time <= ENSAYO_FIN:
        x = map_x(tick_time)
        canvas.line(x, plot_bottom, x, plot_top, GRID_COLOR, GRID_WIDTH)
        if show_x_labels:
            canvas.text(x, plot_bottom - 13.0, tick_time.strftime("%d/%m"), size=FONT_SIZE_TICK, align="center")
            canvas.text(x, plot_bottom - 23.0, tick_time.strftime("%H:%M"), size=FONT_SIZE_TICK, align="center")
        tick_time += timedelta(hours=TIME_TICK_HOURS)

    canvas.line(plot_left, plot_bottom, plot_right, plot_bottom, AXIS_COLOR, AXIS_WIDTH)
    canvas.line(plot_left, plot_bottom, plot_left, plot_top, AXIS_COLOR, AXIS_WIDTH)

    legend_x = plot_right - 120.0
    legend_y = plot_top - 8.0
    for index, (label, color, serie) in enumerate(prepared):
        points = [(map_x(timestamp), map_y(value)) for timestamp, value in serie]
        canvas.polyline(points, color)
        y = legend_y - index * 10.0
        canvas.line(legend_x, y + 2.0, legend_x + 14.0, y + 2.0, color, LINE_WIDTH)
        canvas.text(legend_x + 18.0, y, label, size=FONT_SIZE_TICK)


def build_pdf() -> None:
    rows_cache = {panel["file"]: load_jsonl(DATA_DIR / panel["file"]) for panel in PANELS}

    canvas = PdfCanvas(PAGE_WIDTH, PAGE_HEIGHT)
    canvas.text(PAGE_WIDTH / 2, PAGE_HEIGHT - 24.0, TITLE, size=FONT_SIZE_TITLE, align="center")
    canvas.text(PAGE_WIDTH / 2, PAGE_HEIGHT - 39.0, SUBTITLE, size=FONT_SIZE_SUBTITLE, align="center")

    available_height = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - PANEL_GAP * (len(PANELS) - 1)
    panel_height = available_height / len(PANELS)
    panel_width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

    for index, panel in enumerate(PANELS):
        y0 = PAGE_HEIGHT - MARGIN_TOP - (index + 1) * panel_height - index * PANEL_GAP
        draw_panel(
            canvas,
            panel,
            rows_cache,
            MARGIN_LEFT,
            y0,
            panel_width,
            panel_height,
            show_x_labels=index == len(PANELS) - 1,
        )

    canvas.text(PAGE_WIDTH / 2, 18.0, f"Tiempo [{TIMEZONE_LABEL}]", size=FONT_SIZE_LABEL, align="center")
    canvas.save(OUTPUT_PDF)


def main() -> None:
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    build_pdf()
    print(f"PDF generado: {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
