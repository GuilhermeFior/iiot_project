import unittest
from uuid import UUID, uuid4

from src.publisher.telemetry import build_telemetry_payload
from src.simulator.neutralization import NeutralizationSimulator


class TelemetryPayloadTests(unittest.TestCase):
    def test_payload_follows_the_initial_contract(self) -> None:
        timestamp = "2026-09-07T15:30:00.000Z"
        payload = build_telemetry_payload(
            sequence=10,
            snapshot=NeutralizationSimulator().step(),
            timestamp=timestamp,
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["sequence"], 10)
        self.assertEqual(payload["timestamp"], timestamp)
        self.assertEqual(payload["source"]["plant_id"], "simulated-plant-01")
        self.assertIn("ph", payload["measurements"])
        self.assertFalse(payload["anomaly"]["label"])
        UUID(payload["message_id"], version=4)

    def test_negative_sequence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_telemetry_payload(
                sequence=-1, snapshot=NeutralizationSimulator().step()
            )

    def test_experiment_metadata_is_added_as_a_batch_identifier(self) -> None:
        run_id = uuid4()
        payload = build_telemetry_payload(
            sequence=0,
            snapshot=NeutralizationSimulator().step(),
            experiment_run_id=run_id,
            experiment_profile="stuck_observable",
        )

        self.assertEqual(payload["experiment"]["run_id"], str(run_id))
        self.assertEqual(payload["experiment"]["profile"], "stuck_observable")
