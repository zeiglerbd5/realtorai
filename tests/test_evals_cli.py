"""Exit-code policy for the eval CLI.

    0  passed
    1  real failure — threshold miss, snapshot drift, unexpected miss
    2  could not run — no API key, empty vector store, --min-cases unmet

This distinction is the whole reason the evals can be CI steps. The scripts
these replaced returned 1 for "ANTHROPIC_API_KEY not configured", so a missing
optional secret was indistinguishable from a regression and no workflow could
sensibly branch on the result.
"""

from pathlib import Path

import pytest

from realtorai.evals.cli import EXIT_FAIL, EXIT_OK, EXIT_UNAVAILABLE, main

SNAPSHOT = Path("src/realtorai/evals/snapshots/intake-heuristic.json")


def test_heuristic_backend_passes_today() -> None:
    assert main(["intake", "--backend", "heuristic"]) == EXIT_OK


def test_committed_snapshot_matches_current_behaviour() -> None:
    """If this fails, either the heuristic changed or a case did — both want review."""
    assert main(["intake", "--backend", "heuristic", "--snapshot", str(SNAPSHOT)]) == EXIT_OK


def test_missing_snapshot_fails_rather_than_passing_vacuously(tmp_path: Path) -> None:
    absent = tmp_path / "not-created-yet.json"
    assert main(["intake", "--backend", "heuristic", "--snapshot", str(absent)]) == EXIT_FAIL


def test_unreachable_threshold_fails() -> None:
    assert (
        main(["intake", "--backend", "heuristic", "--metric", "macro_f1", "--threshold", "0.999"])
        == EXIT_FAIL
    )


def test_reachable_threshold_passes() -> None:
    assert (
        main(["intake", "--backend", "heuristic", "--metric", "macro_f1", "--threshold", "0.5"])
        == EXIT_OK
    )


def test_live_backend_without_a_key_is_unavailable_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from realtorai.config.settings import get_settings

    get_settings.cache_clear()
    assert main(["intake", "--backend", "live"]) == EXIT_UNAVAILABLE


def test_min_cases_catches_a_vacuously_green_run() -> None:
    """Filtering to a handful of cases must not pass a --min-cases 20 gate."""
    assert (
        main(["intake", "--backend", "heuristic", "--filter", "closing", "--min-cases", "20"])
        == EXIT_UNAVAILABLE
    )


def test_filter_matches_tags_as_well_as_ids() -> None:
    assert main(["intake", "--backend", "heuristic", "--filter", "hard-negative"]) == EXIT_OK
    assert main(["intake", "--backend", "heuristic", "--filter", "no-such-tag"]) == EXIT_UNAVAILABLE


def test_schema_coverage_subcommand_passes(tmp_path: Path) -> None:
    assert main(["schema-coverage", "--json", str(tmp_path / "coverage.json")]) == EXIT_OK
    assert (tmp_path / "coverage.json").exists()


def test_json_report_is_written_and_parseable(tmp_path: Path) -> None:
    import json

    out = tmp_path / "report.json"
    main(["intake", "--backend", "heuristic", "--json", str(out)])
    report = json.loads(out.read_text())

    assert report["backend"] == "heuristic"
    assert report["metrics"]["majority_baseline"] == 0.4  # 8 `other` of 20
    assert len(report["results"]) == 20
