"""Modelos de validação das mensagens recebidas pelo serviço de ingestão."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnomalyType(StrEnum):
    PROCESS_DISTURBANCE = "process_disturbance"
    SENSOR_NOISE = "sensor_noise"
    SENSOR_STUCK = "sensor_stuck"
    SENSOR_OUT_OF_RANGE = "sensor_out_of_range"
    COMMUNICATION_DELAY = "communication_delay"


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plant_id: str = Field(min_length=1)
    tank_id: str = Field(min_length=1)
    sensor_group: str = Field(min_length=1)


class Measurements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ph: float = Field(ge=0, le=14)
    effluent_flow_l_s: float = Field(ge=0)
    acid_flow_l_s: float = Field(ge=0)
    temperature_c: float
    level_m: float = Field(ge=0)
    valve_position_pct: float = Field(ge=0, le=100)


class ControllerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setpoint_ph: float = Field(ge=0, le=14)
    error_ph: float
    delta_error_ph: float


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: bool
    type: AnomalyType | None

    @model_validator(mode="after")
    def validate_label_and_type(self) -> "Anomaly":
        if self.label and self.type is None:
            raise ValueError("anomaly.type é obrigatório quando anomaly.label é true")
        if not self.label and self.type is not None:
            raise ValueError("anomaly.type deve ser null quando anomaly.label é false")
        return self


class TelemetryMessage(BaseModel):
    """Mensagem de telemetria na versão inicial do contrato MQTT."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    message_id: UUID
    sequence: int = Field(ge=0)
    timestamp: datetime
    source: Source
    measurements: Measurements
    controller: ControllerState
    anomaly: Anomaly

    def to_mongo_document(self, received_at: datetime | None = None) -> dict:
        """Converte a mensagem para tipos BSON compatíveis com o MongoDB."""
        document = self.model_dump(mode="python")
        document["message_id"] = str(self.message_id)
        document["received_at"] = received_at or datetime.now(timezone.utc)
        return document
