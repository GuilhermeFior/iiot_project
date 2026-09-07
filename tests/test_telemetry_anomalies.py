"""Testes de injeção de falhas na telemetria simulada."""

import unittest

from src.simulator.anomalies import AnomalyWindow, TelemetryFaultInjector


def payload() -> dict:
    return {
        "timestamp": "2026-09-07T15:00:00.000Z",
        "measurements": {"ph": 7.0},
        "anomaly": {"label": False, "type": None},
    }


class TelemetryFaultInjectorTests(unittest.TestCase):
    def test_sensor_stuck_keeps_first_observed_ph(self) -> None:
        window = AnomalyWindow("sensor_stuck", start_sequence=1, duration_messages=2)
        injector = TelemetryFaultInjector([window])

        first = injector.apply(payload(), 1)
        next_payload = payload()
        next_payload["measurements"]["ph"] = 7.3
        second = injector.apply(next_payload, 2)

        self.assertEqual(first["measurements"]["ph"], 7.0)
        self.assertEqual(second["measurements"]["ph"], 7.0)
        self.assertEqual(second["anomaly"]["type"], "sensor_stuck")

    def test_out_of_range_value_stays_inside_contract_ph_limits(self) -> None:
        injector = TelemetryFaultInjector(
            [AnomalyWindow("sensor_out_of_range", start_sequence=0, duration_messages=1)]
        )

        changed = injector.apply(payload(), 0)

        self.assertEqual(changed["measurements"]["ph"], 13.5)
        self.assertEqual(changed["anomaly"]["type"], "sensor_out_of_range")

    def test_communication_delay_changes_timestamp(self) -> None:
        injector = TelemetryFaultInjector(
            [AnomalyWindow("communication_delay", start_sequence=0, duration_messages=1)],
            communication_delay_s=30,
        )

        changed = injector.apply(payload(), 0)

        self.assertEqual(changed["timestamp"], "2026-09-07T14:59:30.000Z")
