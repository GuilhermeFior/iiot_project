"""Detector inicial de perturbação de processo e avaliação contra rótulos."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
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


@dataclass(frozen=True)
class FlowObservation:
    """Vazão afluente e rótulo de referência de uma observação."""

    effluent_flow_l_s: float
    is_process_disturbance: bool


@dataclass(frozen=True)
class ClassificationMetrics:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    f1_score: float
    accuracy: float


def median_absolute_deviation(values: list[float], center: float) -> float:
    """Calcula o MAD, medida robusta de dispersão em torno da mediana."""
    return median([abs(value - center) for value in values])


def derive_flow_threshold(
    values: list[float], minimum_deviation_l_s: float, robust_z: float
) -> tuple[float, float, float]:
    """Retorna a referência robusta, MAD e limiar de desvio para a vazão."""
    if not values:
        raise ValueError("a série de vazão não pode estar vazia")
    if minimum_deviation_l_s <= 0 or robust_z <= 0:
        raise ValueError("minimum_deviation_l_s e robust_z devem ser positivos")

    center = median(values)
    mad = median_absolute_deviation(values, center)
    robust_standard_deviation = 1.4826 * mad
    threshold = max(minimum_deviation_l_s, robust_z * robust_standard_deviation)
    return center, mad, threshold


def classification_metrics(
    actual: list[bool], predicted: list[bool]
) -> ClassificationMetrics:
    """Calcula a matriz de confusão e métricas binárias sem dependências externas."""
    if len(actual) != len(predicted):
        raise ValueError("actual e predicted devem ter o mesmo tamanho")
    if not actual:
        raise ValueError("é necessário avaliar ao menos uma observação")

    true_positive = sum(a and p for a, p in zip(actual, predicted, strict=True))
    false_positive = sum(
        not a and p for a, p in zip(actual, predicted, strict=True)
    )
    true_negative = sum(
        not a and not p for a, p in zip(actual, predicted, strict=True)
    )
    false_negative = sum(
        a and not p for a, p in zip(actual, predicted, strict=True)
    )
    precision = true_positive / (true_positive + false_positive) if (
        true_positive + false_positive
    ) else 0.0
    recall = true_positive / (true_positive + false_negative) if (
        true_positive + false_negative
    ) else 0.0
    f1_score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (true_positive + true_negative) / len(actual)
    return ClassificationMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        true_negative=true_negative,
        false_negative=false_negative,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1_score, 4),
        accuracy=round(accuracy, 4),
    )


def evaluate_flow_detector(
    observations: list[FlowObservation],
    minimum_deviation_l_s: float,
    robust_z: float,
) -> dict[str, Any]:
    """Detecta desvios de vazão sem usar rótulos para estimar o limiar."""
    values = [observation.effluent_flow_l_s for observation in observations]
    baseline, mad, threshold = derive_flow_threshold(
        values, minimum_deviation_l_s, robust_z
    )
    predicted = [abs(value - baseline) > threshold for value in values]
    actual = [observation.is_process_disturbance for observation in observations]
    return {
        "observations": len(observations),
        "baseline_flow_l_s": baseline,
        "mad_flow_l_s": mad,
        "threshold_deviation_l_s": threshold,
        "metrics": asdict(classification_metrics(actual, predicted)),
    }


def observations_from_collection(collection: Collection) -> list[FlowObservation]:
    """Carrega apenas os campos necessários para o detector."""
    cursor = collection.find(
        SOURCE_FILTER,
        {
            "_id": 0,
            "measurements.effluent_flow_l_s": 1,
            "anomaly.type": 1,
        },
    ).sort("timestamp", 1)
    return [
        FlowObservation(
            effluent_flow_l_s=document["measurements"]["effluent_flow_l_s"],
            is_process_disturbance=(
                document.get("anomaly", {}).get("type") == "process_disturbance"
            ),
        )
        for document in cursor
    ]


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Avalia um detector robusto de perturbação na vazão afluente."
    )
    parser.add_argument(
        "--collection",
        choices=("document", "timeseries"),
        default="timeseries",
        help="Coleção da qual as observações serão lidas.",
    )
    parser.add_argument(
        "--minimum-deviation",
        type=positive_float,
        default=0.25,
        help="Desvio mínimo de vazão, em L/s, para disparar uma detecção.",
    )
    parser.add_argument(
        "--robust-z",
        type=positive_float,
        default=3.5,
        help="Multiplicador aplicado ao desvio-padrão robusto estimado por MAD.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/analysis/anomaly_detection_results.json"),
        help="Arquivo JSON local que receberá a avaliação.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    settings = repository.settings
    collection_name = (
        settings.document_collection
        if arguments.collection == "document"
        else settings.timeseries_collection
    )

    try:
        repository.client.admin.command("ping")
        observations = observations_from_collection(
            repository.database[collection_name]
        )
    finally:
        repository.close()

    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "collection": collection_name,
        "method": "robust_flow_deviation",
        "minimum_deviation_l_s": arguments.minimum_deviation,
        "robust_z": arguments.robust_z,
        "evaluation": evaluate_flow_detector(
            observations,
            minimum_deviation_l_s=arguments.minimum_deviation,
            robust_z=arguments.robust_z,
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics = result["evaluation"]["metrics"]
    print(f"Resultados gravados em {arguments.output}")
    print(
        f"precision={metrics['precision']:.4f} recall={metrics['recall']:.4f} "
        f"f1={metrics['f1_score']:.4f} accuracy={metrics['accuracy']:.4f}"
    )


if __name__ == "__main__":
    main()
