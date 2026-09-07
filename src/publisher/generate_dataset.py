"""Gera e publica, em lote, telemetria para avaliação da arquitetura IIoT."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Iterator

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from src.publisher.telemetry import build_telemetry_payload
from src.simulator.neutralization import NeutralizationConfig, NeutralizationSimulator


@dataclass(frozen=True)
class BatchScenario:
    """Configura uma série com período normal, perturbação e recuperação."""

    count: int
    normal_before_messages: int
    disturbance_duration_messages: int
    simulation_step_s: float

    def validate(self) -> None:
        if self.count <= 0:
            raise ValueError("count deve ser maior que zero")
        if self.normal_before_messages < 0:
            raise ValueError("normal_before_messages não pode ser negativo")
        if self.disturbance_duration_messages <= 0:
            raise ValueError("disturbance_duration_messages deve ser maior que zero")
        if self.simulation_step_s <= 0:
            raise ValueError("simulation_step_s deve ser maior que zero")
        disturbance_end = (
            self.normal_before_messages + self.disturbance_duration_messages
        )
        if disturbance_end >= self.count:
            raise ValueError(
                "count deve incluir ao menos uma mensagem de recuperação após a "
                "perturbação"
            )


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

    for sequence in range(scenario.count):
        snapshot = simulator.step(scenario.simulation_step_s)
        simulated_timestamp = first_timestamp + timedelta(
            seconds=(sequence + 1) * scenario.simulation_step_s
        )
        yield build_telemetry_payload(
            sequence=sequence,
            snapshot=snapshot,
            timestamp=format_rfc3339(simulated_timestamp),
        )


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
    anomaly_messages = 0
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
            anomaly_messages += int(payload["anomaly"]["label"])
            if published % arguments.progress_every == 0 or published == scenario.count:
                print(
                    f"Publicado {published}/{scenario.count} mensagens "
                    f"(anomalias={anomaly_messages})"
                )
            if published < scenario.count and arguments.interval:
                time.sleep(arguments.interval)
    finally:
        client.loop_stop()
        client.disconnect()

    print(
        f"Lote concluído: {published} mensagens em {topic}; "
        f"{anomaly_messages} rotuladas como process_disturbance."
    )


if __name__ == "__main__":
    main()
