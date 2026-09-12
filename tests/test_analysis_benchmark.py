"""Testes de utilitários puros do benchmark de consultas."""

from datetime import datetime, timezone
import unittest

from src.analysis.benchmark_queries import (
    dataset_filter,
    latency_summary,
    parse_window_hours,
    summarize_plan,
    time_window_query,
)


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

    def test_parse_window_hours_accepts_distinct_positive_csv_values(self) -> None:
        self.assertEqual(parse_window_hours("1, 6,24"), [1, 6, 24])

    def test_time_window_query_includes_source_and_bounds(self) -> None:
        start = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        end = datetime(2026, 9, 7, 13, tzinfo=timezone.utc)

        query = time_window_query(start, end)

        self.assertEqual(query["timestamp"], {"$gte": start, "$lte": end})
        self.assertEqual(query["source.plant_id"], "simulated-plant-01")

    def test_dataset_filter_can_select_only_legacy_records(self) -> None:
        query = dataset_filter(run_id=None, without_experiment=True)

        self.assertEqual(query["experiment"], {"$exists": False})
