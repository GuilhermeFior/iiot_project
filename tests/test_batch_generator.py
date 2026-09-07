"""Testes do gerador de séries de telemetria em lote."""

from datetime import datetime, timezone
import unittest

from src.publisher.generate_dataset import (
    BatchScenario,
    anomaly_windows,
    generate_batch_payloads,
)


class BatchGeneratorTests(unittest.TestCase):
    def test_generates_normal_disturbance_and_recovery_periods(self) -> None:
        scenario = BatchScenario(
            count=12,
            normal_before_messages=4,
            disturbance_duration_messages=3,
            simulation_step_s=2.0,
        )
        start = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)

        payloads = list(generate_batch_payloads(scenario, start))

        self.assertEqual([payload["sequence"] for payload in payloads], list(range(12)))
        self.assertTrue(all(not payload["anomaly"]["label"] for payload in payloads[:4]))
        self.assertTrue(all(payload["anomaly"]["label"] for payload in payloads[4:7]))
        self.assertTrue(all(not payload["anomaly"]["label"] for payload in payloads[7:]))
        self.assertEqual(
            payloads[0]["timestamp"], "2026-09-07T15:00:02.000Z"
        )
        self.assertEqual(
            payloads[-1]["timestamp"], "2026-09-07T15:00:24.000Z"
        )

    def test_requires_a_recovery_period(self) -> None:
        scenario = BatchScenario(
            count=7,
            normal_before_messages=4,
            disturbance_duration_messages=3,
            simulation_step_s=1.0,
        )

        with self.assertRaises(ValueError):
            list(generate_batch_payloads(scenario))

    def test_all_types_profile_generates_each_contract_anomaly(self) -> None:
        scenario = BatchScenario(
            count=30,
            normal_before_messages=2,
            disturbance_duration_messages=2,
            simulation_step_s=1.0,
            anomaly_profile="all_types",
            sensor_anomaly_duration_messages=2,
            normal_between_anomalies_messages=1,
        )

        payloads = list(generate_batch_payloads(scenario))
        anomaly_types = {payload["anomaly"]["type"] for payload in payloads}

        self.assertEqual(
            anomaly_types - {None},
            {
                "process_disturbance",
                "sensor_noise",
                "sensor_stuck",
                "sensor_out_of_range",
                "communication_delay",
            },
        )
        self.assertEqual(len(anomaly_windows(scenario)), 5)
