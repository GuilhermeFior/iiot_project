"""Executa consultas equivalentes nas coleções MongoDB documental e Time Series."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from time import perf_counter_ns
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from src.ingestion.consume_telemetry import mongo_settings_from_environment
from src.ingestion.repository import MongoTelemetryRepository
from src.publisher.telemetry import PLANT_ID, TANK_ID


SERIES_PROJECTION = {
    "_id": 0,
    "timestamp": 1,
    "measurements.ph": 1,
    "measurements.acid_flow_l_s": 1,
    "measurements.effluent_flow_l_s": 1,
    "anomaly": 1,
}

SOURCE_FILTER = {
    "source.plant_id": PLANT_ID,
    "source.tank_id": TANK_ID,
}

SUMMARY_GROUP = {
    "$group": {
        "_id": None,
        "records": {"$sum": 1},
        "first_timestamp": {"$min": "$timestamp"},
        "last_timestamp": {"$max": "$timestamp"},
        "ph_mean": {"$avg": "$measurements.ph"},
        "ph_min": {"$min": "$measurements.ph"},
        "ph_max": {"$max": "$measurements.ph"},
        "acid_flow_mean": {"$avg": "$measurements.acid_flow_l_s"},
        "acid_flow_min": {"$min": "$measurements.acid_flow_l_s"},
        "acid_flow_max": {"$max": "$measurements.acid_flow_l_s"},
        "process_disturbances": {
            "$sum": {
                "$cond": [
                    {"$eq": ["$anomaly.type", "process_disturbance"]},
                    1,
                    0,
                ]
            }
        },
    }
}


def dataset_filter(run_id: UUID | None, without_experiment: bool) -> dict[str, Any]:
    """Restringe a análise a um experimento ou à base sem metadados de lote."""
    query = SOURCE_FILTER.copy()
    if run_id is not None:
        query["experiment.run_id"] = str(run_id)
    elif without_experiment:
        query["experiment"] = {"$exists": False}
    return query


def summary_pipeline(query: dict[str, Any]) -> list[dict[str, Any]]:
    """Cria um pipeline de resumo para o subconjunto solicitado."""
    return [
        {"$match": query},
        SUMMARY_GROUP,
        {"$project": {"_id": 0}},
    ]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior ou igual a zero")
    return parsed


def parse_window_hours(value: str) -> list[int]:
    """Converte uma lista CSV de janelas temporais positivas em horas."""
    try:
        windows = [int(item.strip()) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "window-hours deve conter inteiros separados por vírgula"
        ) from error
    if not windows or any(window <= 0 for window in windows):
        raise argparse.ArgumentTypeError(
            "window-hours deve conter somente valores positivos"
        )
    if len(set(windows)) != len(windows):
        raise argparse.ArgumentTypeError("window-hours não pode conter duplicidades")
    return windows


def latency_summary(durations_ns: list[int]) -> dict[str, float]:
    """Converte durações em nanossegundos para métricas em milissegundos."""
    if not durations_ns:
        raise ValueError("é necessário informar ao menos uma duração")
    ordered = sorted(durations_ns)
    percentile_index = math.ceil(len(ordered) * 0.95) - 1

    def milliseconds(value: float) -> float:
        return round(value / 1_000_000, 4)

    return {
        "min_ms": milliseconds(ordered[0]),
        "mean_ms": milliseconds(mean(ordered)),
        "median_ms": milliseconds(median(ordered)),
        "p95_ms": milliseconds(ordered[percentile_index]),
        "max_ms": milliseconds(ordered[-1]),
    }


def benchmark_operation(
    operation: Callable[[], list[dict[str, Any]]],
    iterations: int,
    warmup: int,
) -> dict[str, Any]:
    """Executa uma operação, materializando seu cursor e medindo sua latência."""
    for _ in range(warmup):
        operation()

    durations_ns: list[int] = []
    returned_documents = 0
    for _ in range(iterations):
        started_at = perf_counter_ns()
        returned_documents = len(operation())
        durations_ns.append(perf_counter_ns() - started_at)

    return {
        "iterations": iterations,
        "returned_documents": returned_documents,
        "latency": latency_summary(durations_ns),
    }


def summarize_plan(plan: Any) -> list[str]:
    """Extrai os nomes dos estágios presentes em uma resposta de ``explain``."""
    stages: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            stage = value.get("stage")
            if isinstance(stage, str) and stage not in stages:
                stages.append(stage)
            for nested_value in value.values():
                visit(nested_value)
        elif isinstance(value, list):
            for nested_value in value:
                visit(nested_value)

    visit(plan)
    return stages


def find_explain_stages(
    collection: Collection,
    query: dict[str, Any],
    limit: int | None = None,
) -> dict[str, Any]:
    """Obtém uma visão compacta do plano de uma consulta temporal."""
    find_command: dict[str, Any] = {
        "find": collection.name,
        "filter": query,
        "sort": {"timestamp": -1},
        "projection": SERIES_PROJECTION,
    }
    if limit is not None:
        find_command["limit"] = limit
    command = {
        "explain": find_command,
        "verbosity": "queryPlanner",
    }
    try:
        explained = collection.database.command(command)
    except PyMongoError as error:
        return {"error": str(error)}
    return {"stages": summarize_plan(explained)}


def collection_summary(
    collection: Collection, query: dict[str, Any] = SOURCE_FILTER
) -> dict[str, Any]:
    """Retorna estatísticas funcionais de uma coleção de telemetria."""
    result = list(collection.aggregate(summary_pipeline(query)))
    return result[0] if result else {"records": 0}


def time_window_query(
    start: datetime,
    end: datetime,
    source_filter: dict[str, Any] = SOURCE_FILTER,
) -> dict[str, Any]:
    """Monta o filtro por fonte e por intervalo temporal inclusivo."""
    if start > end:
        raise ValueError("o início da janela não pode ser posterior ao fim")
    return {**source_filter, "timestamp": {"$gte": start, "$lte": end}}


def storage_statistics(collection: Collection) -> dict[str, int] | dict[str, str]:
    """Lê indicadores de tamanho lógico, físico e índices da coleção."""
    try:
        stats = collection.database.command({"collStats": collection.name})
    except PyMongoError as error:
        return {"error": str(error)}
    fields = ("count", "size", "storageSize", "totalIndexSize", "avgObjSize")
    return {
        field: stats[field]
        for field in fields
        if isinstance(stats.get(field), (int, float))
    }


def collection_benchmark(
    collection: Collection,
    iterations: int,
    warmup: int,
    series_limit: int,
    window_hours: list[int],
    window_end: datetime,
    source_filter: dict[str, Any] = SOURCE_FILTER,
) -> dict[str, Any]:
    """Mede consultas recentes, rótulos, agregação e janelas temporais."""
    operations: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "recent_telemetry": lambda: list(
            collection.find(source_filter, SERIES_PROJECTION)
            .sort("timestamp", -1)
            .limit(series_limit)
        ),
        "process_disturbances": lambda: list(
            collection.find(
                {**source_filter, "anomaly.type": "process_disturbance"},
                SERIES_PROJECTION,
            )
            .sort("timestamp", 1)
        ),
        "aggregate_summary": lambda: list(
            collection.aggregate(summary_pipeline(source_filter))
        ),
    }
    time_windows: dict[str, dict[str, Any]] = {}
    for hours in window_hours:
        start = window_end - timedelta(hours=hours)
        query = time_window_query(start, window_end, source_filter)
        time_windows[f"{hours}h"] = {
            "start_timestamp": start,
            "end_timestamp": window_end,
            "benchmark": benchmark_operation(
                lambda query=query: list(
                    collection.find(query, SERIES_PROJECTION).sort("timestamp", 1)
                ),
                iterations,
                warmup,
            ),
            "query_plan": find_explain_stages(collection, query),
        }
    return {
        "summary": collection_summary(collection, source_filter),
        "storage": storage_statistics(collection),
        "query_plan": find_explain_stages(collection, source_filter, series_limit),
        "benchmarks": {
            name: benchmark_operation(operation, iterations, warmup)
            for name, operation in operations.items()
        },
        "time_windows": time_windows,
    }


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value).__name__}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara consultas entre MongoDB documental e Time Series."
    )
    parser.add_argument(
        "--iterations",
        type=positive_int,
        default=10,
        help="Número de execuções medidas por consulta.",
    )
    parser.add_argument(
        "--warmup",
        type=non_negative_int,
        default=2,
        help="Número de execuções de aquecimento não medidas.",
    )
    parser.add_argument(
        "--series-limit",
        type=positive_int,
        default=250,
        help="Número máximo de medições na consulta temporal.",
    )
    parser.add_argument(
        "--window-hours",
        type=parse_window_hours,
        default="1,6,24",
        help="Janelas temporais, em horas, separadas por vírgula.",
    )
    dataset_group = parser.add_mutually_exclusive_group()
    dataset_group.add_argument(
        "--run-id",
        type=UUID,
        help="Restringe as consultas a um lote experimental identificado.",
    )
    dataset_group.add_argument(
        "--without-experiment",
        action="store_true",
        help="Restringe as consultas às mensagens anteriores ao uso de run_id.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/analysis/benchmark_results.json"),
        help="Arquivo JSON local que receberá os resultados.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    settings = repository.settings
    source_filter = dataset_filter(arguments.run_id, arguments.without_experiment)

    try:
        repository.client.admin.command("ping")
        collections = {
            "document": repository.database[settings.document_collection],
            "timeseries": repository.database[settings.timeseries_collection],
        }
        reference_summary = collection_summary(collections["document"], source_filter)
        if not reference_summary.get("records"):
            raise ValueError("não há dados para executar o benchmark")
        window_end = reference_summary["last_timestamp"]
        report = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "settings": {
                "iterations": arguments.iterations,
                "warmup": arguments.warmup,
                "series_limit": arguments.series_limit,
                "window_hours": arguments.window_hours,
                "window_end": window_end,
                "dataset_filter": {
                    "run_id": str(arguments.run_id) if arguments.run_id else None,
                    "without_experiment": arguments.without_experiment,
                },
            },
            "collections": {
                name: collection_benchmark(
                    collection,
                    iterations=arguments.iterations,
                    warmup=arguments.warmup,
                    series_limit=arguments.series_limit,
                    window_hours=arguments.window_hours,
                    window_end=window_end,
                    source_filter=source_filter,
                )
                for name, collection in collections.items()
            },
        }
    finally:
        repository.close()

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )
    print(f"Resultados gravados em {arguments.output}")
    for name, result in report["collections"].items():
        summary = result["summary"]
        latency = result["benchmarks"]["recent_telemetry"]["latency"]
        windows = ", ".join(
            f"{label}={window['benchmark']['latency']['mean_ms']}ms"
            for label, window in result["time_windows"].items()
        )
        print(
            f"{name}: records={summary['records']} "
            f"disturbances={summary.get('process_disturbances', 0)} "
            f"recent_telemetry_mean_ms={latency['mean_ms']} windows=[{windows}]"
        )


if __name__ == "__main__":
    main()
