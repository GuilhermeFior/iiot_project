"""Gera e publica, em lote, telemetria para avaliação da arquitetura IIoT."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Iterator

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from src.publisher.telemetry import build_telemetry_payload
from src.simulator.anomalies import AnomalyWindow, TelemetryFaultInjector
from src.simulator.neutralization import NeutralizationConfig, NeutralizationSimulator


@dataclass(frozen=True)
class BatchScenario:
    """Configura uma série com período normal, perturbação e recuperação."""

    count: int
    normal_before_messages: int
    disturbance_duration_messages: int
    simulation_step_s: float
    anomaly_profile: str = "process_only"
    sensor_anomaly_duration_messages: int = 60
    normal_between_anomalies_messages: int = 40
    communication_delay_s: float = 30.0

    def validate(self) -> None:
        if self.count <= 0:
            raise ValueError("count deve ser maior que zero")
        if self.normal_before_messages < 0:
            raise ValueError("normal_before_messages não pode ser negativo")
        if self.disturbance_duration_messages <= 0:
            raise ValueError("disturbance_duration_messages deve ser maior que zero")
        if self.simulation_step_s <= 0:
            raise ValueError("simulation_step_s deve ser maior que zero")
        if self.anomaly_profile not in {"process_only", "all_types"}:
            raise ValueError("anomaly_profile deve ser process_only ou all_types")
        if self.sensor_anomaly_duration_messages <= 0:
            raise ValueError("sensor_anomaly_duration_messages deve ser maior que zero")
        if self.normal_between_anomalies_messages < 0:
            raise ValueError("normal_between_anomalies_messages não pode ser negativo")
        if self.communication_delay_s <= 0:
            raise ValueError("communication_delay_s deve ser maior que zero")
        if anomaly_windows(self)[-1].end_sequence >= self.count:
            raise ValueError(
                "count deve incluir ao menos uma mensagem de recuperação após a "
                "perturbação"
            )


def anomaly_windows(scenario: BatchScenario) -> list[AnomalyWindow]:
    """Define períodos não sobrepostos de anomalias para um perfil de lote."""
    windows = [
        AnomalyWindow(
            anomaly_type="process_disturbance",
            start_sequence=scenario.normal_before_messages,
            duration_messages=scenario.disturbance_duration_messages,
        )
    ]
    if scenario.anomaly_profile == "process_only":
        return windows

    next_start = (
        windows[-1].end_sequence + scenario.normal_between_anomalies_messages
    )
    for anomaly_type in (
        "sensor_noise",
        "sensor_stuck",
        "sensor_out_of_range",
        "communication_delay",
    ):
        windows.append(
            AnomalyWindow(
                anomaly_type=anomaly_type,
                start_sequence=next_start,
                duration_messages=scenario.sensor_anomaly_duration_messages,
            )
        )
        next_start = windows[-1].end_sequence + scenario.normal_between_anomalies_messages
    return windows


def format_rfc3339(timestamp: datetime) -> str:
    """Formata um instante UTC conforme o contrato MQTT."""
    return timestamp.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def generate_batch_payloads(
    scenario: BatchScenario, start_timestamp: datetime | None = None
) -> Iterator[dict]:
    """Produz payloads ordenados com timestamps correspondentes ao tempo simulado."""
    scenario.validate()
    first_timestamp = (start_timestamp or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    )
    simulator = NeutralizationSimulator(
        NeutralizationConfig(
            disturbance_start_s=(
                scenario.normal_before_messages * scenario.simulation_step_s
            ),
            disturbance_duration_s=(
                scenario.disturbance_duration_messages * scenario.simulation_step_s
            ),
        )
    )
    fault_injector = TelemetryFaultInjector(
        [window for window in anomaly_windows(scenario) if window.anomaly_type != "process_disturbance"],
        communication_delay_s=scenario.communication_delay_s,
    )

    for sequence in range(scenario.count):
        snapshot = simulator.step(scenario.simulation_step_s)
        simulated_timestamp = first_timestamp + timedelta(
            seconds=(sequence + 1) * scenario.simulation_step_s
        )
        payload = build_telemetry_payload(
            sequence=sequence,
            snapshot=snapshot,
            timestamp=format_rfc3339(simulated_timestamp),
        )
        yield fault_injector.apply(payload, sequence)


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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gera telemetria em lote com operação normal, perturbação e recuperação."
        )
    )
    parser.add_argument(
        "--count",
        type=positive_int,
        default=1_000,
        help="Número total de mensagens da série.",
    )
    parser.add_argument(
        "--normal-before",
        type=non_negative_int,
        default=300,
        help="Número de medições normais antes da perturbação.",
    )
    parser.add_argument(
        "--disturbance-duration",
        type=positive_int,
        default=120,
        help="Número de medições rotuladas como perturbação de processo.",
    )
    parser.add_argument(
        "--anomaly-profile",
        choices=("process_only", "all_types"),
        default="process_only",
        help="Processa somente perturbação física ou todos os tipos do contrato.",
    )
    parser.add_argument(
        "--sensor-anomaly-duration",
        type=positive_int,
        default=60,
        help="Duração de cada anomalia de sensor ou comunicação.",
    )
    parser.add_argument(
        "--normal-between-anomalies",
        type=non_negative_int,
        default=40,
        help="Medições normais entre períodos de anomalia no perfil all_types.",
    )
    parser.add_argument(
        "--communication-delay",
        type=float,
        default=30.0,
        help="Atraso artificial, em segundos, aplicado ao timestamp da mensagem.",
    )
    parser.add_argument(
        "--simulation-step",
        type=float,
        default=1.0,
        help="Segundos simulados entre duas medições consecutivas.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Espera real, em segundos, entre publicações.",
    )
    parser.add_argument(
        "--progress-every",
        type=positive_int,
        default=100,
        help="Frequência, em mensagens, da saída de progresso.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.interval < 0:
        raise ValueError("interval deve ser maior ou igual a zero")

    scenario = BatchScenario(
        count=arguments.count,
        normal_before_messages=arguments.normal_before,
        disturbance_duration_messages=arguments.disturbance_duration,
        simulation_step_s=arguments.simulation_step,
        anomaly_profile=arguments.anomaly_profile,
        sensor_anomaly_duration_messages=arguments.sensor_anomaly_duration,
        normal_between_anomalies_messages=arguments.normal_between_anomalies,
        communication_delay_s=arguments.communication_delay,
    )
    scenario.validate()

    load_dotenv()
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    topic = os.getenv(
        "MQTT_TOPIC_TELEMETRY",
        "tcc/v1/simulated-plant-01/tanks/t-01/telemetry",
    )
    client_id = os.getenv("MQTT_BATCH_CLIENT_ID", "tcc-batch-telemetry-publisher")
    connected = Event()
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )

    def on_connect(
        _client: mqtt.Client,
        _userdata: object,
        _connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            raise ConnectionError(f"Conexão MQTT recusada: {reason_code}")
        connected.set()

    client.on_connect = on_connect
    client.connect(host, port, keepalive=60)
    client.loop_start()

    published = 0
    anomaly_counts: Counter[str] = Counter()
    try:
        if not connected.wait(timeout=5):
            raise TimeoutError("O broker MQTT não confirmou a conexão em 5 segundos")

        for payload in generate_batch_payloads(scenario):
            result = client.publish(topic, json.dumps(payload), qos=0)
            result.wait_for_publish()
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"Falha ao publicar a mensagem {payload['sequence']}: {result.rc}"
                )

            published += 1
            anomaly_type = payload["anomaly"]["type"]
            if anomaly_type:
                anomaly_counts[anomaly_type] += 1
            if published % arguments.progress_every == 0 or published == scenario.count:
                print(
                    f"Publicado {published}/{scenario.count} mensagens "
                    f"(anomalias={sum(anomaly_counts.values())})"
                )
            if published < scenario.count and arguments.interval:
                time.sleep(arguments.interval)
    finally:
        client.loop_stop()
        client.disconnect()

    anomaly_summary = ", ".join(
        f"{anomaly_type}={count}"
        for anomaly_type, count in sorted(anomaly_counts.items())
    ) or "nenhuma anomalia"
    print(f"Lote concluído: {published} mensagens em {topic}; {anomaly_summary}.")


if __name__ == "__main__":
    main()
