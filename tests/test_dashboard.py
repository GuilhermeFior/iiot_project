import unittest

from src.analysis.dashboard import build_dashboard_html, serialize_records


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            {
                "sequence": 0,
                "timestamp": "2026-09-12T12:00:00+00:00",
                "measurements": {
                    "ph": 7.0,
                    "effluent_flow_l_s": 10.0,
                    "acid_flow_l_s": 1.0,
                },
                "controller": {"setpoint_ph": 7.0, "error_ph": 0.1},
                "anomaly": {"type": "sensor_stuck"},
            }
        ]

    def test_serialize_records_reconstructs_process_ph(self) -> None:
        result = serialize_records(self.records)

        self.assertEqual(result[0]["estimatedPh"], 6.9)
        self.assertEqual(result[0]["anomaly"], "sensor_stuck")

    def test_dashboard_embeds_run_and_metrics(self) -> None:
        html = build_dashboard_html(
            "run-test",
            self.records,
            {
                "detectors": {
                    "sensor_stuck": {
                        "metrics": {"precision": 1.0, "recall": 0.75, "f1_score": 0.8571}
                    }
                }
            },
        )

        self.assertIn("run-test", html)
        self.assertIn("sensor_stuck", html)
        self.assertIn("0.8571", html)
