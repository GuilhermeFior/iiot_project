"""Publica telemetria mínima no broker MQTT local."""

from __future__ import annotations

import argparse
import json
import os
import time
from threading import Event

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

try:
    from .telemetry import build_telemetry_payload
except ImportError:  # Permite executar este arquivo diretamente.
    from telemetry import build_telemetry_payload

from src.simulator.neutralization import NeutralizationConfig, NeutralizationSimulator


def read_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publica mensagens de telemetria no broker MQTT."
    )
    parser.add_argument(
        "--count",
        type=read_positive_int,
        default=1,
        help="Quantidade de mensagens a publicar.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Intervalo em segundos entre mensagens.",
    )
    parser.add_argument(
        "--simulation-step",
        type=float,
        default=1.0,
        help="Tempo simulado, em segundos, entre duas mensagens.",
    )
    parser.add_argument(
        "--disturbance-start",
        type=float,
        default=None,
        help="Início, em segundos simulados, do aumento de vazão afluente.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.interval < 0:
        raise ValueError("interval deve ser maior ou igual a zero")
    if arguments.simulation_step <= 0:
        raise ValueError("simulation-step deve ser maior que zero")
    if arguments.disturbance_start is not None and arguments.disturbance_start < 0:
        raise ValueError("disturbance-start deve ser maior ou igual a zero")

    load_dotenv()
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    topic = os.getenv(
        "MQTT_TOPIC_TELEMETRY",
        "tcc/v1/simulated-plant-01/tanks/t-01/telemetry",
    )
    client_id = os.getenv("MQTT_CLIENT_ID", "tcc-telemetry-publisher")
    connected = Event()
    simulator = NeutralizationSimulator(
        NeutralizationConfig(disturbance_start_s=arguments.disturbance_start)
    )

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

    try:
        if not connected.wait(timeout=5):
            raise TimeoutError("O broker MQTT não confirmou a conexão em 5 segundos")

        for sequence in range(arguments.count):
            snapshot = simulator.step(arguments.simulation_step)
            payload = build_telemetry_payload(sequence, snapshot)
            result = client.publish(topic, json.dumps(payload), qos=0)
            result.wait_for_publish()
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"Falha ao publicar a mensagem {sequence}: {result.rc}")

            print(
                f"Publicado sequence={sequence} message_id={payload['message_id']} "
                f"pH={payload['measurements']['ph']:.3f} "
                f"acid_flow_l_s={payload['measurements']['acid_flow_l_s']:.3f} "
                f"topic={topic}"
            )
            if sequence < arguments.count - 1:
                time.sleep(arguments.interval)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
