"""Testes do detector robusto de perturbação de processo."""

import unittest

from src.analysis.anomaly_detection import (
    FlowObservation,
    classification_metrics,
    derive_flow_threshold,
    evaluate_flow_detector,
)


class AnomalyDetectionTests(unittest.TestCase):
    def test_flow_detector_identifies_large_flow_deviations(self) -> None:
        observations = [
            FlowObservation(10.0, False),
            FlowObservation(10.0, False),
            FlowObservation(11.5, True),
            FlowObservation(10.0, False),
            FlowObservation(11.5, True),
        ]

        result = evaluate_flow_detector(
            observations, minimum_deviation_l_s=0.25, robust_z=3.5
        )

        self.assertEqual(result["baseline_flow_l_s"], 10.0)
        self.assertEqual(result["threshold_deviation_l_s"], 0.25)
        self.assertEqual(result["metrics"]["true_positive"], 2)
        self.assertEqual(result["metrics"]["false_positive"], 0)
        self.assertEqual(result["metrics"]["f1_score"], 1.0)

    def test_metrics_handles_false_negative(self) -> None:
        metrics = classification_metrics([True, False], [False, False])

        self.assertEqual(metrics.true_negative, 1)
        self.assertEqual(metrics.false_negative, 1)
        self.assertEqual(metrics.recall, 0.0)

    def test_threshold_requires_observations(self) -> None:
        with self.assertRaises(ValueError):
            derive_flow_threshold([], minimum_deviation_l_s=0.25, robust_z=3.5)
