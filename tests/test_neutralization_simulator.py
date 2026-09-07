"""Testes de consistência do modelo de neutralização de pH."""

import unittest

from src.simulator.neutralization import NeutralizationConfig, NeutralizationSimulator


class NeutralizationSimulatorTests(unittest.TestCase):
    def test_nominal_process_remains_near_the_setpoint(self) -> None:
        simulator = NeutralizationSimulator()
        snapshots = [simulator.step() for _ in range(30)]

        self.assertTrue(all(0.0 <= snapshot.ph <= 14.0 for snapshot in snapshots))
        self.assertAlmostEqual(snapshots[-1].ph, 7.0, delta=0.1)
        self.assertTrue(all(not snapshot.anomaly_label for snapshot in snapshots))

    def test_influent_disturbance_increases_acid_control_action(self) -> None:
        simulator = NeutralizationSimulator(
            NeutralizationConfig(disturbance_start_s=0.0, disturbance_duration_s=20.0)
        )
        snapshots = [simulator.step() for _ in range(30)]

        self.assertTrue(any(snapshot.anomaly_label for snapshot in snapshots))
        self.assertTrue(any(snapshot.acid_flow_l_s > 2.0 for snapshot in snapshots))
        self.assertTrue(
            all(0.0 <= snapshot.valve_position_pct <= 100.0 for snapshot in snapshots)
        )
