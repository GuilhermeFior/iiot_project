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


def telemetry_from_collection(
    collection: Collection, run_id: str | None = None
) -> list[dict[str, Any]]:
    """Obtém a telemetria da fonte, opcionalmente limitada a um experimento."""
    query = dict(SOURCE_FILTER)
    if run_id:
        query["experiment.run_id"] = run_id
    return list(
        collection.find(
            query,
            {
                "_id": 0,
                "timestamp": 1,
                "measurements.ph": 1,
                "measurements.effluent_flow_l_s": 1,
                "measurements.acid_flow_l_s": 1,
                "controller.setpoint_ph": 1,
                "controller.error_ph": 1,
                "anomaly.label": 1,
                "anomaly.type": 1,
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
    estimated_ph_values = [
        document["controller"]["setpoint_ph"] - document["controller"]["error_ph"]
        for document in telemetry
    ]
    effluent_values = [
        document["measurements"]["effluent_flow_l_s"] for document in telemetry
    ]
    acid_values = [document["measurements"]["acid_flow_l_s"] for document in telemetry]
    anomaly_indexes = [
        index for index, document in enumerate(telemetry) if document["anomaly"]["label"]
    ]
    ph_points = polyline_points(ph_values, left, chart_width, ph_top, chart_height)
    estimated_ph_points = polyline_points(
        estimated_ph_values, left, chart_width, ph_top, chart_height
    )
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
  <text x="{left}" y="32" font-size="21" font-weight="bold">Telemetria simulada: pH, vazões e anomalias</text>
  <text x="{left}" y="55" font-size="12">Período: {escape(first_timestamp)} a {escape(last_timestamp)} · faixas vermelhas = telemetria rotulada como anômala</text>
  <line class="axis" x1="{left}" y1="{ph_top + chart_height}" x2="{left + chart_width}" y2="{ph_top + chart_height}"/>
  <line class="axis" x1="{left}" y1="{flow_top + chart_height}" x2="{left + chart_width}" y2="{flow_top + chart_height}"/>
  <line class="grid" x1="{left}" y1="{ph_top + chart_height / 2}" x2="{left + chart_width}" y2="{ph_top + chart_height / 2}"/>
  <line class="grid" x1="{left}" y1="{flow_top + chart_height / 2}" x2="{left + chart_width}" y2="{flow_top + chart_height / 2}"/>
  {anomaly_rectangles}
  <polyline points="{ph_points}" fill="none" stroke="#2563eb" stroke-width="2"/>
  <polyline points="{estimated_ph_points}" fill="none" stroke="#7c3aed" stroke-width="2" stroke-dasharray="7 4"/>
  <polyline points="{effluent_points}" fill="none" stroke="#059669" stroke-width="2"/>
  <polyline points="{acid_points}" fill="none" stroke="#f59e0b" stroke-width="2"/>
  <text x="18" y="{ph_top + 15}" font-size="14" font-weight="bold">pH</text>
  <text x="{left + 55}" y="{ph_top - 17}" fill="#2563eb" font-size="13">— pH medido</text>
  <text x="{left + 165}" y="{ph_top - 17}" fill="#7c3aed" font-size="13">— pH estimado do processo</text>
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
    for label in document.get("time_windows", {}):
        document_mean = document["time_windows"][label]["benchmark"]["latency"][
            "mean_ms"
        ]
        timeseries_mean = timeseries["time_windows"][label]["benchmark"][
            "latency"
        ]["mean_ms"]
        rows.append(
            f"| janela temporal ({label}) | {document_mean:.4f} | {timeseries_mean:.4f} |"
        )
    document_storage = document.get("storage", {})
    timeseries_storage = timeseries.get("storage", {})
    content = f'''# Resultados preliminares de análise

Base analisada: {document["summary"]["records"]} observações do tanque simulado, com {document["summary"].get("process_disturbances", 0)} rótulos de perturbação de processo. As medições foram executadas localmente com {benchmark["settings"]["iterations"]} repetições e {benchmark["settings"]["warmup"]} aquecimentos; valores não devem ser generalizados para outros ambientes.

## Latência média das consultas

| Consulta | Documental (ms) | Time Series (ms) |
|---|---:|---:|
{chr(10).join(rows)}

Plano da consulta temporal: documental = {", ".join(document["query_plan"].get("stages", [])) or "indisponível"}; Time Series = {", ".join(timeseries["query_plan"].get("stages", [])) or "indisponível"}.

## Armazenamento da coleção

| Indicador | Documental | Time Series |
|---|---:|---:|
| Tamanho lógico (bytes) | {document_storage.get("size", "indisponível")} | {timeseries_storage.get("size", "indisponível")} |
| Tamanho físico (bytes) | {document_storage.get("storageSize", "indisponível")} | {timeseries_storage.get("storageSize", "indisponível")} |
| Índices (bytes) | {document_storage.get("totalIndexSize", "indisponível")} | {timeseries_storage.get("totalIndexSize", "indisponível")} |

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


def multi_detection_markdown(detection: dict[str, Any]) -> str:
    """Formata os resultados um-contra-todos para inserção no relatório."""
    rows = []
    for anomaly_type, result in detection["detectors"].items():
        metrics = result["metrics"]
        rows.append(
            "| "
            f"{anomaly_type} | {metrics['true_positive']} | "
            f"{metrics['false_positive']} | {metrics['false_negative']} | "
            f"{metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['f1_score']:.4f} |"
        )
    run_id = detection.get("run_id", "não informado")
    return f'''# Validação de detecção de anomalias

Experimento: `{run_id}`. Coleção avaliada: `{detection["collection"]}`. Foram
analisadas {detection["observations"]} observações; cada detector foi avaliado
individualmente em esquema um-contra-todos, usando os rótulos apenas para o
cálculo posterior das métricas.

| Tipo de anomalia | VP | FP | FN | Precisão | Revocação | F1-score |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Os parâmetros de cada detector estão registrados no arquivo JSON de origem.
Em particular, resultados com precisão alta e revocação inferior a 1 indicam
um detector conservador: ele evita alarmes espúrios, mas pode deixar de sinalizar
casos limítrofes.
'''


def create_multi_detection_report(detection: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(multi_detection_markdown(detection), encoding="utf-8")


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
    parser.add_argument(
        "--multi-detection-input",
        type=Path,
        help="JSON produzido por multi_anomaly_detection para relatório multianomalia.",
    )
    parser.add_argument(
        "--experiment-markdown-output",
        type=Path,
        default=Path("artifacts/analysis/experiment_detection_summary.md"),
        help="Tabela Markdown usada quando --multi-detection-input for informado.",
    )
    parser.add_argument(
        "--run-id",
        help="Filtra a telemetria visualizada por um experimento identificado.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    multi_detection = None
    if arguments.multi_detection_input:
        multi_detection = json.loads(
            arguments.multi_detection_input.read_text(encoding="utf-8")
        )
        run_id = arguments.run_id or multi_detection.get("run_id")
        if not run_id:
            raise ValueError(
                "--run-id é obrigatório quando o JSON multianomalia não contém run_id"
            )
    else:
        run_id = arguments.run_id
        benchmark = json.loads(arguments.benchmark_input.read_text(encoding="utf-8"))
        detection = json.loads(arguments.detection_input.read_text(encoding="utf-8"))
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    try:
        telemetry = telemetry_from_collection(
            repository.database[repository.settings.timeseries_collection], run_id
        )
    finally:
        repository.close()

    if multi_detection:
        create_multi_detection_report(multi_detection, arguments.experiment_markdown_output)
        print(f"Tabela gravada em {arguments.experiment_markdown_output}")
    else:
        create_markdown_report(benchmark, detection, arguments.markdown_output)
        print(f"Tabela gravada em {arguments.markdown_output}")
    create_svg(telemetry, arguments.svg_output)
    print(f"Gráfico gravado em {arguments.svg_output}")


if __name__ == "__main__":
    main()
