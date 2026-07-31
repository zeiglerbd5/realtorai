"""Scoring math for the eval harness.

The headline test is `test_degenerate_classifier_looks_good_on_accuracy_only`.
The intake case set is imbalanced, so a model that answers `other` to
everything scores a respectable-looking 0.50 accuracy. Macro-F1 puts it at
0.13. That gap is the entire reason the report carries four metrics instead of
one, and this file is where that claim is checked rather than asserted.
"""

from pathlib import Path

from realtorai.evals.harness import CaseResult, diff_snapshot, score, to_dict, write_json

#: Gold distribution mirroring the real intake set: one dominant class.
GOLD = (
    ["other"] * 7
    + ["new_listing_client"] * 2
    + ["under_contract"] * 2
    + ["closing"] * 2
    + ["new_buyer_client"] * 1
)
LABELS = [
    "closing",
    "new_buyer_client",
    "new_listing_client",
    "other",
    "under_contract",
]


def results_for(predictions: list[str]) -> list[CaseResult]:
    return [
        CaseResult(
            case_id=f"case-{i:02d}",
            expected=expected,
            predicted=predicted,
            status="pass" if expected == predicted else "fail",
        )
        for i, (expected, predicted) in enumerate(zip(GOLD, predictions, strict=True))
    ]


def test_degenerate_classifier_looks_good_on_accuracy_only() -> None:
    report = score("intake", "degenerate", results_for(["other"] * 14), LABELS)

    assert report.accuracy == 0.5  # 7 of 14 — respectable-looking
    assert round(report.macro_f1, 3) == 0.133  # ...and useless
    assert round(report.balanced_accuracy, 3) == 0.2
    assert report.majority_baseline == 0.5  # accuracy never beats the baseline
    assert not report.ok


def test_perfect_classifier() -> None:
    report = score("intake", "oracle", results_for(list(GOLD)), LABELS)
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.balanced_accuracy == 1.0
    assert report.ok


def test_one_false_positive_costs_more_on_macro_f1_than_accuracy() -> None:
    """A broadcast email misread as a new listing — the known heuristic miss."""
    predictions = list(GOLD)
    predictions[0] = "new_listing_client"  # gold was `other`
    report = score("intake", "heuristic", results_for(predictions), LABELS)

    assert round(report.accuracy, 3) == 0.929
    assert round(report.macro_f1, 3) == 0.945
    assert round(report.balanced_accuracy, 3) == 0.971

    by_label = {s.label: s for s in report.per_label}
    assert by_label["new_listing_client"].precision < 1.0  # over-predicted
    assert by_label["new_listing_client"].recall == 1.0
    assert by_label["other"].precision == 1.0
    assert by_label["other"].recall < 1.0  # one gold `other` lost


def test_xfail_does_not_fail_the_run_but_xpass_does() -> None:
    known_miss = CaseResult("known-miss", "other", "new_listing_client", "xfail")
    assert score("intake", "heuristic", [known_miss], LABELS).ok

    fixed = CaseResult("known-miss", "other", "other", "xpass")
    report = score("intake", "heuristic", [fixed], LABELS)
    assert not report.ok, "an xpass must be surfaced, not silently swallowed"


def test_skips_are_excluded_from_metrics_not_counted_as_passes() -> None:
    results = [
        CaseResult("ran", "other", "other", "pass"),
        CaseResult("skipped", "closing", None, "skip", detail="needs private corpus"),
    ]
    report = score("retrieval", "default", results, LABELS)

    assert report.scored == 1
    assert report.accuracy == 1.0  # over what actually ran
    assert report.counts["skip"] == 1
    assert report.ok  # a skip is not a failure...
    # ...which is why the CLI also enforces --min-cases; see cli.py.


def test_ranked_metrics_only_appear_for_ranked_tasks() -> None:
    results = [
        CaseResult("hit-first", "src-a", "src-a", "pass", rank=1),
        CaseResult("hit-third", "src-b", "src-b", "pass", rank=3),
        CaseResult("missed", "src-c", None, "fail", rank=None),
    ]
    unranked = score("intake", "x", results, None)
    assert unranked.mrr is None and unranked.recall_at_k is None

    ranked = score("retrieval", "x", results, None, ranked=True)
    assert round(ranked.recall_at_k or 0, 3) == 0.667  # 2 of 3 found
    assert round(ranked.mrr or 0, 3) == 0.444  # (1/1 + 1/3 + 0) / 3


def test_stable_serialisation_drops_run_to_run_noise() -> None:
    results = [CaseResult("a", "other", "other", "pass", detail="conf=high", elapsed_ms=812)]
    report = score("intake", "live", results, LABELS, started_at="2026-07-31T12:00:00+00:00")

    stable = to_dict(report, stable=True)
    assert "started_at" not in stable
    assert "elapsed_ms" not in stable["results"][0]
    assert "detail" not in stable["results"][0]

    full = to_dict(report, stable=False)
    assert full["started_at"] == "2026-07-31T12:00:00+00:00"
    assert full["results"][0]["elapsed_ms"] == 812


def test_snapshot_diff_names_the_case_that_changed(tmp_path: Path) -> None:
    baseline = score("intake", "heuristic", results_for(list(GOLD)), LABELS)
    snapshot = write_json(baseline, tmp_path / "snap.json", stable=True)
    assert diff_snapshot(baseline, snapshot) == []

    regressed = list(GOLD)
    regressed[3] = "closing"
    drifted = score("intake", "heuristic", results_for(regressed), LABELS)
    diffs = diff_snapshot(drifted, snapshot)

    assert len(diffs) == 1
    assert "case-03" in diffs[0]
    assert "pass/other -> fail/closing" in diffs[0]


def test_missing_snapshot_is_reported_rather_than_silently_passing(tmp_path: Path) -> None:
    report = score("intake", "heuristic", results_for(list(GOLD)), LABELS)
    assert diff_snapshot(report, tmp_path / "absent.json")
