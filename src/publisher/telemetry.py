"""Construção de mensagens de telemetria definidas no contrato MQTT."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.simulator.neutralization import ProcessSnapshot


SCHEMA_VERSION = "1.0"
PLANT_ID = "simulated-plant-01"
TANK_ID = "t-01"
SENSOR_GROUP = "process"


def utc_timestamp() -> str:
    """Retorna um timestamp RFC 3339 em UTC com precisão de milissegundos."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def build_telemetry_payload(
    sequence: int, snapshot: ProcessSnapshot, timestamp: str | None = None
) -> dict[str, Any]:
    """Converte um estado do simulador em mensagem do contrato MQTT."""
    if sequence < 0:
        raise ValueError("sequence deve ser um inteiro não negativo")

    return {
        "schema_version": SCHEMA_VERSION,
        "message_id": str(uuid4()),
        "sequence": sequence,
        "timestamp": timestamp or utc_timestamp(),
        "source": {
            "plant_id": PLANT_ID,
            "tank_id": TANK_ID,
            "sensor_group": SENSOR_GROUP,
        },
        "measurements": {
            "ph": round(snapshot.ph, 3),
            "effluent_flow_l_s": round(snapshot.effluent_flow_l_s, 3),
            "acid_flow_l_s": round(snapshot.acid_flow_l_s, 3),
            "temperature_c": round(snapshot.temperature_c, 3),
            "level_m": round(snapshot.level_m, 3),
            "valve_position_pct": round(snapshot.valve_position_pct, 3),
        },
        "controller": {
            "setpoint_ph": round(snapshot.setpoint_ph, 3),
            "error_ph": round(snapshot.error_ph, 3),
            "delta_error_ph": round(snapshot.delta_error_ph, 3),
        },
        "anomaly": {
            "label": snapshot.anomaly_label,
            "type": snapshot.anomaly_type,
        },
    }
