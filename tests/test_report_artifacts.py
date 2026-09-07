"""Testes de funções puras de geração do gráfico SVG."""

import unittest

from src.analysis.report_artifacts import polyline_points, scale_values


class ReportArtifactTests(unittest.TestCase):
    def test_scale_values_inverts_vertical_axis(self) -> None:
        scaled = scale_values([0.0, 10.0], top=10.0, height=100.0)

        self.assertGreater(scaled[0], scaled[1])
        self.assertTrue(all(10.0 <= value <= 110.0 for value in scaled))

    def test_polyline_contains_one_point_for_each_value(self) -> None:
        points = polyline_points([1.0, 2.0, 3.0], 0.0, 100.0, 0.0, 100.0)

        self.assertEqual(len(points.split()), 3)
