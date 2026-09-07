"""Gera tabela Markdown e gráfico SVG para documentar os resultados locais."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo.collection import Collection

from src.ingestion.consume_telemetry import mongo_settings_from_environment
from src.ingestion.repository import MongoTelemetryRepository
from src.publisher.telemetry import PLANT_ID, TANK_ID


SOURCE_FILTER = {
    "source.plant_id": PLANT_ID,
    "source.tank_id": TANK_ID,
}


def scale_values(values: list[float], top: float, height: float) -> list[float]:
    """Converte valores em coordenadas SVG, preservando uma margem vertical."""
    lower = min(values)
    upper = max(values)
    padding = max((upper - lower) * 0.08, 0.05)
    lower -= padding
    upper += padding
    return [top + height * (1 - (value - lower) / (upper - lower)) for value in values]


def polyline_points(values: list[float], left: float, width: float, top: float, height: float) -> str:
    """Gera pontos SVG para uma série ordenada."""
    if len(values) == 1:
        x_values = [left + width / 2]
    else:
        x_values = [left + width * index / (len(values) - 1) for index in range(len(values))]
    y_values = scale_values(values, top, height)
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(x_values, y_values))


def telemetry_from_collection(collection: Collection) -> list[dict[str, Any]]:
    return list(
        collection.find(
            SOURCE_FILTER,
            {
                "_id": 0,
                "timestamp": 1,
                "measurements.ph": 1,
                "measurements.effluent_flow_l_s": 1,
                "measurements.acid_flow_l_s": 1,
                "anomaly.label": 1,
            },
        ).sort("timestamp", 1)
    )


def create_svg(telemetry: list[dict[str, Any]], output: Path) -> None:
    """Desenha pH e vazões ordenados por tempo sem dependências de gráficos."""
    if not telemetry:
        raise ValueError("não há telemetria para gerar o gráfico")

    width, height, left, chart_width = 1200, 660, 85, 1060
    ph_top, chart_height, flow_top = 75, 185, 365
    ph_values = [document["measurements"]["ph"] for document in telemetry]
    effluent_values = [
        document["measurements"]["effluent_flow_l_s"] for document in telemetry
    ]
    acid_values = [document["measurements"]["acid_flow_l_s"] for document in telemetry]
    anomaly_indexes = [
        index for index, document in enumerate(telemetry) if document["anomaly"]["label"]
    ]
    ph_points = polyline_points(ph_values, left, chart_width, ph_top, chart_height)
    effluent_points = polyline_points(
        effluent_values, left, chart_width, flow_top, chart_height
    )
    acid_points = polyline_points(acid_values, left, chart_width, flow_top, chart_height)
    anomaly_width = max(chart_width / len(telemetry), 1.0)
    anomaly_rectangles = "".join(
        f'<rect x="{left + chart_width * index / max(len(telemetry) - 1, 1) - anomaly_width / 2:.2f}" '
        f'y="{ph_top}" width="{anomaly_width:.2f}" height="{flow_top + chart_height - ph_top}" '
        'fill="#ef4444" opacity="0.14"/>'
        for index in anomaly_indexes
    )
    first_timestamp = telemetry[0]["timestamp"].isoformat()
    last_timestamp = telemetry[-1]["timestamp"].isoformat()
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <style>text {{ font-family: Arial, sans-serif; fill: #1f2937; }} .axis {{ stroke: #94a3b8; }} .grid {{ stroke: #e2e8f0; }} </style>
  <text x="{left}" y="32" font-size="21" font-weight="bold">Telemetria simulada: pH, vazões e perturbações</text>
  <text x="{left}" y="55" font-size="12">Período: {escape(first_timestamp)} a {escape(last_timestamp)} · faixas vermelhas = process_disturbance</text>
  <line class="axis" x1="{left}" y1="{ph_top + chart_height}" x2="{left + chart_width}" y2="{ph_top + chart_height}"/>
  <line class="axis" x1="{left}" y1="{flow_top + chart_height}" x2="{left + chart_width}" y2="{flow_top + chart_height}"/>
  <line class="grid" x1="{left}" y1="{ph_top + chart_height / 2}" x2="{left + chart_width}" y2="{ph_top + chart_height / 2}"/>
  <line class="grid" x1="{left}" y1="{flow_top + chart_height / 2}" x2="{left + chart_width}" y2="{flow_top + chart_height / 2}"/>
  {anomaly_rectangles}
  <polyline points="{ph_points}" fill="none" stroke="#2563eb" stroke-width="2"/>
  <polyline points="{effluent_points}" fill="none" stroke="#059669" stroke-width="2"/>
  <polyline points="{acid_points}" fill="none" stroke="#f59e0b" stroke-width="2"/>
  <text x="18" y="{ph_top + 15}" font-size="14" font-weight="bold">pH</text>
  <text x="18" y="{flow_top + 15}" font-size="14" font-weight="bold">Vazão (L/s)</text>
  <text x="{left}" y="{ph_top + chart_height + 25}" font-size="12">Medições ordenadas por timestamp</text>
  <text x="{left + 15}" y="{flow_top - 17}" fill="#059669" font-size="13">— vazão afluente</text>
  <text x="{left + 155}" y="{flow_top - 17}" fill="#f59e0b" font-size="13">— vazão de ácido</text>
</svg>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")


def create_markdown_report(
    benchmark: dict[str, Any], detection: dict[str, Any], output: Path
) -> None:
    document = benchmark["collections"]["document"]
    timeseries = benchmark["collections"]["timeseries"]
    metrics = detection["evaluation"]["metrics"]
    rows = []
    for operation in ("recent_telemetry", "process_disturbances", "aggregate_summary"):
        document_mean = document["benchmarks"][operation]["latency"]["mean_ms"]
        timeseries_mean = timeseries["benchmarks"][operation]["latency"]["mean_ms"]
        rows.append(f"| {operation} | {document_mean:.4f} | {timeseries_mean:.4f} |")
    content = f'''# Resultados preliminares de análise

Base analisada: {document["summary"]["records"]} observações do tanque simulado, com {document["summary"].get("process_disturbances", 0)} rótulos de perturbação de processo. As medições foram executadas localmente com {benchmark["settings"]["iterations"]} repetições e {benchmark["settings"]["warmup"]} aquecimentos; valores não devem ser generalizados para outros ambientes.

## Latência média das consultas

| Consulta | Documental (ms) | Time Series (ms) |
|---|---:|---:|
{chr(10).join(rows)}

Plano da consulta temporal: documental = {", ".join(document["query_plan"].get("stages", [])) or "indisponível"}; Time Series = {", ".join(timeseries["query_plan"].get("stages", [])) or "indisponível"}.

## Detector inicial de perturbação

O detector foi calibrado sem consultar os rótulos, usando mediana e MAD da vazão afluente. O limiar de desvio foi {detection["evaluation"]["threshold_deviation_l_s"]:.4f} L/s em relação à referência de {detection["evaluation"]["baseline_flow_l_s"]:.4f} L/s.

| Métrica | Valor |
|---|---:|
| Verdadeiros positivos | {metrics["true_positive"]} |
| Falsos positivos | {metrics["false_positive"]} |
| Verdadeiros negativos | {metrics["true_negative"]} |
| Falsos negativos | {metrics["false_negative"]} |
| Precisão | {metrics["precision"]:.4f} |
| Revocação | {metrics["recall"]:.4f} |
| F1-score | {metrics["f1_score"]:.4f} |
| Acurácia | {metrics["accuracy"]:.4f} |

O desempenho deste detector é específico da perturbação atualmente simulada, que altera diretamente a vazão afluente. A próxima versão deve incluir ruído de sensor, leituras congeladas e desvios de pH para uma avaliação mais abrangente.
'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera artefatos visuais e tabulares dos resultados de análise."
    )
    parser.add_argument(
        "--benchmark-input",
        type=Path,
        default=Path("artifacts/analysis/benchmark_results.json"),
    )
    parser.add_argument(
        "--detection-input",
        type=Path,
        default=Path("artifacts/analysis/anomaly_detection_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("artifacts/analysis/results_summary.md"),
    )
    parser.add_argument(
        "--svg-output",
        type=Path,
        default=Path("artifacts/analysis/telemetry_overview.svg"),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    benchmark = json.loads(arguments.benchmark_input.read_text(encoding="utf-8"))
    detection = json.loads(arguments.detection_input.read_text(encoding="utf-8"))
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    try:
        telemetry = telemetry_from_collection(
            repository.database[repository.settings.timeseries_collection]
        )
    finally:
        repository.close()

    create_markdown_report(benchmark, detection, arguments.markdown_output)
    create_svg(telemetry, arguments.svg_output)
    print(f"Tabela gravada em {arguments.markdown_output}")
    print(f"Gráfico gravado em {arguments.svg_output}")


if __name__ == "__main__":
    main()
