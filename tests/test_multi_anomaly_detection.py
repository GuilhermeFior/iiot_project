"""Testes das linhas de base para múltiplos tipos de anomalia."""

from datetime import datetime, timedelta, timezone
import unittest

from src.analysis.multi_anomaly_detection import (
    Observation,
    detect_communication_delay,
    detect_sensor_out_of_range,
    detect_sensor_stuck,
)


def observation(
    sequence: int,
    timestamp_s: int,
    observed_ph: float = 7.0,
    expected_ph: float = 7.0,
) -> Observation:
    base = datetime(2026, 9, 7, tzinfo=timezone.utc)
    return Observation(
        sequence=sequence,
        timestamp=base + timedelta(seconds=timestamp_s),
        received_at=base + timedelta(seconds=sequence),
        observed_ph=observed_ph,
        expected_ph=expected_ph,
        effluent_flow_l_s=10.0,
        anomaly_type=None,
    )


class MultiAnomalyDetectionTests(unittest.TestCase):
    def test_communication_delay_marks_interval_between_clock_jumps(self) -> None:
        observations = [
            observation(0, 0),
            observation(1, 1),
            observation(2, -28),
            observation(3, -27),
            observation(4, 4),
        ]

        self.assertEqual(
            detect_communication_delay(observations),
            [False, False, True, True, False],
        )

    def test_stuck_detector_requires_repetition_and_process_residual(self) -> None:
        observations = [
            observation(0, 0, observed_ph=7.0, expected_ph=7.0),
            observation(1, 1, observed_ph=7.0, expected_ph=7.05),
            observation(2, 2, observed_ph=7.0, expected_ph=7.08),
        ]

        self.assertEqual(
            detect_sensor_stuck(observations, 0.005, 0.2),
            [False, True, True],
        )

    def test_out_of_range_detector_uses_operational_limits(self) -> None:
        predictions = detect_sensor_out_of_range(
            [observation(0, 0, observed_ph=7.0), observation(1, 1, observed_ph=13.5)]
        )

        self.assertEqual(predictions, [False, True])
