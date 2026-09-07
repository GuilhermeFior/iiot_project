"""Testes de utilitários puros do benchmark de consultas."""

import unittest

from src.analysis.benchmark_queries import latency_summary, summarize_plan


class BenchmarkUtilityTests(unittest.TestCase):
    def test_latency_summary_uses_milliseconds_and_nearest_rank_p95(self) -> None:
        summary = latency_summary([1_000_000, 2_000_000, 3_000_000, 10_000_000])

        self.assertEqual(summary["min_ms"], 1.0)
        self.assertEqual(summary["mean_ms"], 4.0)
        self.assertEqual(summary["median_ms"], 2.5)
        self.assertEqual(summary["p95_ms"], 10.0)
        self.assertEqual(summary["max_ms"], 10.0)

    def test_summarize_plan_collects_unique_stages(self) -> None:
        plan = {
            "queryPlanner": {
                "winningPlan": {
                    "stage": "FETCH",
                    "inputStage": {"stage": "IXSCAN"},
                }
            },
            "executionStats": {"executionStages": {"stage": "FETCH"}},
        }

        self.assertEqual(summarize_plan(plan), ["FETCH", "IXSCAN"])
