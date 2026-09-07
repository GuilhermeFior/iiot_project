import unittest

from pydantic import ValidationError

from src.ingestion.models import TelemetryMessage
from src.publisher.telemetry import build_telemetry_payload
from src.simulator.neutralization import NeutralizationSimulator


class TelemetryMessageValidationTests(unittest.TestCase):
    def test_valid_payload_is_converted_to_mongo_document(self) -> None:
        payload = build_telemetry_payload(
            sequence=5,
            snapshot=NeutralizationSimulator().step(),
            timestamp="2026-09-07T15:30:00.000Z",
        )

        message = TelemetryMessage.model_validate(payload)
        document = message.to_mongo_document()

        self.assertEqual(document["sequence"], 5)
        self.assertIsInstance(document["message_id"], str)
        self.assertIn("received_at", document)

    def test_anomaly_type_requires_positive_label(self) -> None:
        payload = build_telemetry_payload(
            sequence=5, snapshot=NeutralizationSimulator().step()
        )
        payload["anomaly"] = {"label": False, "type": "sensor_noise"}

        with self.assertRaises(ValidationError):
            TelemetryMessage.model_validate(payload)

    def test_ph_outside_physical_range_is_rejected(self) -> None:
        payload = build_telemetry_payload(
            sequence=5, snapshot=NeutralizationSimulator().step()
        )
        payload["measurements"]["ph"] = 15.0

        with self.assertRaises(ValidationError):
            TelemetryMessage.model_validate(payload)
