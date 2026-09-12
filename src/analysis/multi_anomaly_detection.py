"""Linhas de base interpretáveis para cada tipo de anomalia do contrato."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from pymongo.collection import Collection

from src.analysis.anomaly_detection import classification_metrics, derive_flow_threshold
from src.ingestion.consume_telemetry import mongo_settings_from_environment
from src.ingestion.repository import MongoTelemetryRepository
from src.publisher.telemetry import PLANT_ID, TANK_ID


ANOMALY_TYPES = (
    "process_disturbance",
    "sensor_noise",
    "sensor_stuck",
    "sensor_out_of_range",
    "communication_delay",
)
SOURCE_FILTER = {
    "source.plant_id": PLANT_ID,
    "source.tank_id": TANK_ID,
}


@dataclass(frozen=True)
class Observation:
    sequence: int
    timestamp: datetime
    received_at: datetime
    observed_ph: float
    expected_ph: float
    effluent_flow_l_s: float
    anomaly_type: str | None

    @property
    def ph_residual(self) -> float:
        return abs(self.observed_ph - self.expected_ph)


def evaluate_type(
    observations: list[Observation],
    anomaly_type: str,
    predicted: list[bool],
) -> dict:
    """Compara a saída de um detector binário ao rótulo de referência."""
    actual = [item.anomaly_type == anomaly_type for item in observations]
    return asdict(classification_metrics(actual, predicted))


def detect_process_disturbance(
    observations: list[Observation], minimum_deviation_l_s: float
) -> tuple[list[bool], dict[str, float]]:
    values = [item.effluent_flow_l_s for item in observations]
    baseline, mad, threshold = derive_flow_threshold(
        values, minimum_deviation_l_s, robust_z=3.5
    )
    return (
        [abs(value - baseline) > threshold for value in values],
        {
            "baseline_flow_l_s": baseline,
            "mad_flow_l_s": mad,
            "threshold_deviation_l_s": threshold,
        },
    )


def detect_sensor_noise(
    observations: list[Observation], residual_threshold_ph: float
) -> list[bool]:
    """Sinaliza leitura de pH que se afasta do estado estimado pelo controlador."""
    predictions: list[bool] = []
    previous_ph: float | None = None
    for item in observations:
        if item.sequence == 0:
            previous_ph = None
        reading_changes = (
            previous_ph is not None and abs(item.observed_ph - previous_ph) >= 0.0001
        )
        predictions.append(
            item.ph_residual > residual_threshold_ph
            and reading_changes
            and 5.5 < item.observed_ph < 8.5
        )
        previous_ph = item.observed_ph
    return predictions


def detect_sensor_stuck(
    observations: list[Observation],
    minimum_residual_ph: float,
    maximum_residual_ph: float,
) -> list[bool]:
    """Identifica repetição de leitura quando a estimativa do processo se move."""
    predictions: list[bool] = []
    previous_ph: float | None = None
    for item in observations:
        if item.sequence == 0:
            previous_ph = None
        repeated_reading = (
            previous_ph is not None and abs(item.observed_ph - previous_ph) < 0.0001
        )
        predictions.append(
            repeated_reading
            and minimum_residual_ph < item.ph_residual <= maximum_residual_ph
            and 5.5 < item.observed_ph < 8.5
        )
        previous_ph = item.observed_ph
    return predictions


def detect_sensor_out_of_range(observations: list[Observation]) -> list[bool]:
    """Aplica limites operacionais mais estritos que os físicos do contrato."""
    return [item.observed_ph <= 5.5 or item.observed_ph >= 8.5 for item in observations]


def detect_communication_delay(observations: list[Observation]) -> list[bool]:
    """Detecta timestamps atrasados em relação ao relógio nominal de cada lote."""
    predictions: list[bool] = []
    first_timestamp: datetime | None = None
    nominal_step_s: float | None = None
    for item in observations:
        if item.sequence == 0:
            first_timestamp = item.timestamp
            nominal_step_s = None
        if first_timestamp is None:
            predictions.append(False)
            continue
        if item.sequence > 0 and nominal_step_s is None:
            nominal_step_s = (
                item.timestamp - first_timestamp
            ).total_seconds() / item.sequence
        if nominal_step_s is None:
            predictions.append(False)
            continue
        expected_timestamp = first_timestamp.timestamp() + item.sequence * nominal_step_s
        residual_s = item.timestamp.timestamp() - expected_timestamp
        predictions.append(residual_s < -2.0)
    return predictions


def observations_from_collection(
    collection: Collection, run_id: str | None = None
) -> list[Observation]:
    """Lê os campos de telemetria e ordena pelo instante de persistência."""
    query = SOURCE_FILTER.copy()
    if run_id is not None:
        query["experiment.run_id"] = run_id
    cursor = collection.find(
        query,
        {
            "_id": 0,
            "sequence": 1,
            "timestamp": 1,
            "received_at": 1,
            "measurements.ph": 1,
            "measurements.effluent_flow_l_s": 1,
            "controller.setpoint_ph": 1,
            "controller.error_ph": 1,
            "anomaly.type": 1,
        },
    ).sort("received_at", 1)
    return [
        Observation(
            sequence=document["sequence"],
            timestamp=document["timestamp"],
            received_at=document["received_at"],
            observed_ph=document["measurements"]["ph"],
            expected_ph=(
                document["controller"]["setpoint_ph"]
                + document["controller"]["error_ph"]
            ),
            effluent_flow_l_s=document["measurements"]["effluent_flow_l_s"],
            anomaly_type=document.get("anomaly", {}).get("type"),
        )
        for document in cursor
    ]


def run_detectors(
    observations: list[Observation],
    minimum_flow_deviation_l_s: float = 0.25,
    noise_residual_threshold_ph: float = 0.05,
    stuck_minimum_residual_ph: float = 0.005,
    stuck_maximum_residual_ph: float = 0.2,
) -> dict:
    """Executa e avalia os cinco detectores de referência."""
    if not observations:
        raise ValueError("não há observações para avaliar")
    process_predictions, process_parameters = detect_process_disturbance(
        observations, minimum_flow_deviation_l_s
    )
    detector_outputs: dict[str, tuple[list[bool], dict]] = {
        "process_disturbance": (process_predictions, process_parameters),
        "sensor_noise": (
            detect_sensor_noise(observations, noise_residual_threshold_ph),
            {"residual_threshold_ph": noise_residual_threshold_ph},
        ),
        "sensor_stuck": (
            detect_sensor_stuck(
                observations,
                stuck_minimum_residual_ph,
                stuck_maximum_residual_ph,
            ),
            {
                "minimum_residual_ph": stuck_minimum_residual_ph,
                "maximum_residual_ph": stuck_maximum_residual_ph,
            },
        ),
        "sensor_out_of_range": (
            detect_sensor_out_of_range(observations),
            {"operational_range_ph": [5.5, 8.5]},
        ),
        "communication_delay": (
            detect_communication_delay(observations),
            {"negative_timestamp_residual_s": -2.0},
        ),
    }
    return {
        anomaly_type: {
            "parameters": parameters,
            "metrics": evaluate_type(observations, anomaly_type, predictions),
        }
        for anomaly_type, (predictions, parameters) in detector_outputs.items()
    }


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Avalia detectores de referência para todos os tipos de anomalia."
    )
    parser.add_argument(
        "--collection",
        choices=("document", "timeseries"),
        default="timeseries",
    )
    parser.add_argument("--minimum-flow-deviation", type=positive_float, default=0.25)
    parser.add_argument("--noise-residual-threshold", type=positive_float, default=0.05)
    parser.add_argument("--stuck-minimum-residual", type=positive_float, default=0.005)
    parser.add_argument("--stuck-maximum-residual", type=positive_float, default=0.2)
    parser.add_argument(
        "--run-id",
        help="Filtra a avaliação por um UUID de lote experimental.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/analysis/multi_anomaly_detection_results.json"),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    collection_name = (
        repository.settings.document_collection
        if arguments.collection == "document"
        else repository.settings.timeseries_collection
    )
    try:
        observations = observations_from_collection(
            repository.database[collection_name], arguments.run_id
        )
    finally:
        repository.close()

    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "collection": collection_name,
        "run_id": arguments.run_id,
        "observations": len(observations),
        "detectors": run_detectors(
            observations,
            minimum_flow_deviation_l_s=arguments.minimum_flow_deviation,
            noise_residual_threshold_ph=arguments.noise_residual_threshold,
            stuck_minimum_residual_ph=arguments.stuck_minimum_residual,
            stuck_maximum_residual_ph=arguments.stuck_maximum_residual,
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Resultados gravados em {arguments.output}")
    for anomaly_type, result_by_type in result["detectors"].items():
        metrics = result_by_type["metrics"]
        print(
            f"{anomaly_type}: precision={metrics['precision']:.4f} "
            f"recall={metrics['recall']:.4f} f1={metrics['f1_score']:.4f}"
        )


if __name__ == "__main__":
    main()
