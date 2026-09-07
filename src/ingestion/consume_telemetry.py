"""Serviço que consome telemetria MQTT, valida o contrato e persiste no MongoDB."""

from __future__ import annotations

import argparse
import os
import sys
from threading import Event

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError, PyMongoError

from .models import TelemetryMessage
from .repository import MongoSettings, MongoTelemetryRepository, StorageMode


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consome e persiste telemetria MQTT no MongoDB."
    )
    parser.add_argument(
        "--max-messages",
        type=positive_int,
        help="Encerra o serviço após persistir esta quantidade de mensagens válidas.",
    )
    return parser.parse_args()


def mongo_settings_from_environment() -> MongoSettings:
    try:
        storage_mode = StorageMode(os.getenv("MONGO_STORAGE_MODE", "dual"))
    except ValueError as error:
        valid_modes = ", ".join(mode.value for mode in StorageMode)
        raise ValueError(f"MONGO_STORAGE_MODE deve ser um de: {valid_modes}") from error

    return MongoSettings(
        host=os.getenv("MONGO_HOST", "localhost"),
        port=int(os.getenv("MONGO_PORT", "27017")),
        username=os.environ["MONGO_ROOT_USERNAME"],
        password=os.environ["MONGO_ROOT_PASSWORD"],
        database=os.getenv("MONGO_DATABASE", "iiot_tcc"),
        auth_database=os.getenv("MONGO_AUTH_DATABASE", "admin"),
        document_collection=os.getenv(
            "MONGO_DOCUMENT_COLLECTION", "telemetry_documents"
        ),
        timeseries_collection=os.getenv(
            "MONGO_TIMESERIES_COLLECTION", "telemetry_timeseries"
        ),
        storage_mode=storage_mode,
    )


def main() -> None:
    arguments = parse_arguments()
    load_dotenv()

    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    repository.initialize()
    successful_messages = 0
    shutdown_requested = Event()
    topic = os.getenv(
        "MQTT_TOPIC_TELEMETRY",
        "tcc/v1/simulated-plant-01/tanks/t-01/telemetry",
    )
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    client_id = os.getenv("MQTT_INGESTION_CLIENT_ID", "tcc-telemetry-ingestion")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )

    def on_connect(
        connected_client: mqtt.Client,
        _userdata: object,
        _connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            print(f"Conexão MQTT recusada: {reason_code}", file=sys.stderr)
            shutdown_requested.set()
            return
        connected_client.subscribe(topic, qos=0)
        print(f"Assinando telemetria em {topic}")

    def on_message(
        message_client: mqtt.Client,
        _userdata: object,
        mqtt_message: mqtt.MQTTMessage,
    ) -> None:
        nonlocal successful_messages
        try:
            telemetry = TelemetryMessage.model_validate_json(mqtt_message.payload)
            inserted = repository.persist(telemetry)
        except ValidationError as error:
            print(f"Mensagem inválida descartada: {error}", file=sys.stderr)
            return
        except DuplicateKeyError:
            print("Mensagem duplicada ignorada na coleção documental.", file=sys.stderr)
            return
        except PyMongoError as error:
            print(f"Falha ao persistir mensagem: {error}", file=sys.stderr)
            return

        successful_messages += 1
        print(
            f"Persistido sequence={telemetry.sequence} "
            f"message_id={telemetry.message_id} destinos={','.join(inserted)}"
        )
        if arguments.max_messages and successful_messages >= arguments.max_messages:
            shutdown_requested.set()
            message_client.disconnect()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        shutdown_requested.wait()
    except KeyboardInterrupt:
        print("Serviço de ingestão interrompido.")
    finally:
        client.loop_stop()
        client.disconnect()
        repository.close()


if __name__ == "__main__":
    main()
