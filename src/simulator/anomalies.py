"""Injeção determinística de anomalias na telemetria observada do processo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sin
from typing import Literal


AnomalyType = Literal[
    "process_disturbance",
    "sensor_noise",
    "sensor_stuck",
    "sensor_out_of_range",
    "communication_delay",
]


@dataclass(frozen=True)
class AnomalyWindow:
    """Janela discreta de ativação de uma anomalia no lote."""

    anomaly_type: AnomalyType
    start_sequence: int
    duration_messages: int

    @property
    def end_sequence(self) -> int:
        return self.start_sequence + self.duration_messages

    def is_active(self, sequence: int) -> bool:
        return self.start_sequence <= sequence < self.end_sequence


class TelemetryFaultInjector:
    """Aplica falhas de medição e atraso a payloads compatíveis com o contrato."""

    def __init__(
        self,
        windows: list[AnomalyWindow],
        noise_amplitude_ph: float = 0.35,
        out_of_range_ph: float = 13.5,
        communication_delay_s: float = 30.0,
    ) -> None:
        if noise_amplitude_ph <= 0:
            raise ValueError("noise_amplitude_ph deve ser maior que zero")
        if not 0 <= out_of_range_ph <= 14:
            raise ValueError("out_of_range_ph deve estar entre 0 e 14")
        if communication_delay_s <= 0:
            raise ValueError("communication_delay_s deve ser maior que zero")
        self.windows = windows
        self.noise_amplitude_ph = noise_amplitude_ph
        self.out_of_range_ph = out_of_range_ph
        self.communication_delay_s = communication_delay_s
        self._validate_windows()
        self._stuck_ph_by_window: dict[AnomalyWindow, float] = {}

    def _validate_windows(self) -> None:
        previous_end = 0
        for window in sorted(self.windows, key=lambda item: item.start_sequence):
            if window.start_sequence < 0 or window.duration_messages <= 0:
                raise ValueError("as janelas devem ter início não negativo e duração positiva")
            if window.start_sequence < previous_end:
                raise ValueError("as janelas de anomalia não podem se sobrepor")
            previous_end = window.end_sequence

    def active_window(self, sequence: int) -> AnomalyWindow | None:
        return next((window for window in self.windows if window.is_active(sequence)), None)

    def apply(self, payload: dict, sequence: int) -> dict:
        """Altera a telemetria observada e atribui o rótulo da falha ativa."""
        window = self.active_window(sequence)
        if window is None:
            return payload

        anomaly_type = window.anomaly_type
        if anomaly_type == "sensor_noise":
            offset = sequence - window.start_sequence
            noise = self.noise_amplitude_ph * (
                sin(offset * 2.17) + 0.5 * sin(offset * 5.31)
            ) / 1.5
            ph = payload["measurements"]["ph"] + noise
            payload["measurements"]["ph"] = round(max(0.0, min(14.0, ph)), 3)
        elif anomaly_type == "sensor_stuck":
            stuck_ph = self._stuck_ph_by_window.setdefault(
                window, payload["measurements"]["ph"]
            )
            payload["measurements"]["ph"] = stuck_ph
        elif anomaly_type == "sensor_out_of_range":
            payload["measurements"]["ph"] = self.out_of_range_ph
        elif anomaly_type == "communication_delay":
            timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
            delayed = timestamp - timedelta(seconds=self.communication_delay_s)
            payload["timestamp"] = delayed.astimezone(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")

        payload["anomaly"] = {"label": True, "type": anomaly_type}
        return payload
