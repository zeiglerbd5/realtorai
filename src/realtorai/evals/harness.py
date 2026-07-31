"""Scoring and reporting shared by every eval.

Three decisions here carry most of the weight:

**Accuracy is never reported alone.** The intake case set is imbalanced — a
classifier that answers `other` to everything scores 0.500 accuracy but 0.133
macro-F1. `EvalReport` therefore always carries accuracy, macro-F1, balanced
accuracy, and the majority-class baseline together, so the flattering number
cannot be quoted on its own.

**Deterministic backends gate on a snapshot, not a threshold.** A float
threshold on a deterministic predictor is a weaker statement than an exact
per-case diff. Thresholds exist for the sampled live backend.

**Unavailable is not failure.** A missing API key or an empty vector store
exits 2, distinct from a real regression at 1. Conflating them is precisely
why the old scripts could never be CI steps.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Container, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["pass", "fail", "xfail", "xpass", "skip", "error"]

#: Statuses that represent a real prediction and therefore feed the metrics.
SCORED: frozenset[str] = frozenset({"pass", "fail", "xfail", "xpass"})

#: Statuses that mean the run should be considered failing.
BAD: frozenset[str] = frozenset({"fail", "error"})


@dataclass(frozen=True, slots=True)
class Case:
    """One scored example."""

    id: str
    inputs: Mapping[str, Any]
    expected: str
    tags: tuple[str, ...] = ()
    #: External resources this case needs; absent -> skip, never fail.
    requires: tuple[str, ...] = ()
    #: Backends known to miss this case. A miss is xfail; a hit is a loud xpass.
    xfail_backends: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str
    detail: str = ""
    #: 1-based rank of the gold hit for ranked tasks; None means "not found".
    rank: int | None = None


Predictor = Callable[[Case], Awaitable[Prediction]]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    expected: str
    predicted: str | None
    status: Status
    detail: str = ""
    rank: int | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class LabelStats:
    label: str
    support: int
    predicted: int
    true_positives: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class EvalReport:
    name: str
    backend: str
    results: tuple[CaseResult, ...]
    per_label: tuple[LabelStats, ...]
    accuracy: float
    macro_f1: float
    balanced_accuracy: float
    majority_baseline: float
    counts: Mapping[str, int]
    mrr: float | None = None
    recall_at_k: float | None = None
    started_at: str = ""

    @property
    def scored(self) -> int:
        return sum(n for status, n in self.counts.items() if status in SCORED)

    @property
    def ok(self) -> bool:
        """True when nothing failed unexpectedly. xfail is fine; xpass is not."""
        return not any(self.counts.get(status, 0) for status in ("fail", "error", "xpass"))

    def metric(self, name: str) -> float:
        value = {
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "balanced_accuracy": self.balanced_accuracy,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
        }.get(name)
        if value is None:
            raise ValueError(f"{name!r} is not available on this report")
        return value


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def score(
    name: str,
    backend: str,
    results: Sequence[CaseResult],
    labels: Sequence[str] | None = None,
    *,
    ranked: bool = False,
    started_at: str = "",
) -> EvalReport:
    """Turn raw results into metrics. Pure — unit-tested directly.

    `ranked` must be passed explicitly for retrieval-style tasks: a missed hit
    has `rank=None`, so inferring rankedness from the data would report "not a
    ranked task" and "ranked task that missed everything" identically.
    """
    scored = [r for r in results if r.status in SCORED]
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    label_set = list(labels) if labels else sorted(
        {r.expected for r in scored} | {r.predicted for r in scored if r.predicted}
    )

    per_label: list[LabelStats] = []
    for label in label_set:
        support = sum(1 for r in scored if r.expected == label)
        predicted = sum(1 for r in scored if r.predicted == label)
        tp = sum(1 for r in scored if r.expected == label and r.predicted == label)
        precision = _safe_div(tp, predicted)
        recall = _safe_div(tp, support)
        per_label.append(
            LabelStats(
                label=label,
                support=support,
                predicted=predicted,
                true_positives=tp,
                precision=precision,
                recall=recall,
                f1=_safe_div(2 * precision * recall, precision + recall),
            )
        )

    correct = sum(1 for r in scored if r.expected == r.predicted)
    gold_counts = [sum(1 for r in scored if r.expected == label) for label in label_set]

    ranks = [r.rank for r in scored if r.rank is not None]

    return EvalReport(
        name=name,
        backend=backend,
        results=tuple(results),
        per_label=tuple(per_label),
        accuracy=_safe_div(correct, len(scored)),
        macro_f1=_safe_div(sum(s.f1 for s in per_label), len(per_label)),
        balanced_accuracy=_safe_div(sum(s.recall for s in per_label), len(per_label)),
        majority_baseline=_safe_div(max(gold_counts, default=0), len(scored)),
        counts=counts,
        mrr=_safe_div(sum(1.0 / r for r in ranks), len(scored)) if ranked else None,
        recall_at_k=_safe_div(len(ranks), len(scored)) if ranked else None,
        started_at=started_at,
    )


async def run_suite(
    name: str,
    cases: Sequence[Case],
    predictor: Predictor,
    *,
    backend: str,
    labels: Sequence[str] | None = None,
    available_resources: Container[str] | None = None,
    concurrency: int = 1,
    ranked: bool = False,
) -> EvalReport:
    """Run every case through `predictor` and score the results."""
    import asyncio
    import time

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_one(case: Case) -> CaseResult:
        missing = [
            r
            for r in case.requires
            if available_resources is not None and r not in available_resources
        ]
        if missing:
            return CaseResult(
                case_id=case.id,
                expected=case.expected,
                predicted=None,
                status="skip",
                detail=f"needs {', '.join(missing)}",
            )

        async with semaphore:
            start = time.monotonic()
            try:
                prediction = await predictor(case)
            except Exception as exc:  # a broken predictor is a result, not a crash
                return CaseResult(
                    case_id=case.id,
                    expected=case.expected,
                    predicted=None,
                    status="error",
                    detail=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                )
            elapsed = int((time.monotonic() - start) * 1000)

        hit = prediction.label == case.expected
        expected_to_miss = backend in case.xfail_backends
        if hit:
            status: Status = "xpass" if expected_to_miss else "pass"
        else:
            status = "xfail" if expected_to_miss else "fail"

        return CaseResult(
            case_id=case.id,
            expected=case.expected,
            predicted=prediction.label,
            status=status,
            detail=prediction.detail,
            rank=prediction.rank,
            elapsed_ms=elapsed,
        )

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    results = await asyncio.gather(*(run_one(c) for c in cases))
    return score(name, backend, results, labels, ranked=ranked, started_at=started_at)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MARK = {
    "pass": "PASS",
    "fail": "FAIL",
    "xfail": "xfail",
    "xpass": "XPASS",
    "skip": "skip",
    "error": "ERROR",
}


def render_table(report: EvalReport) -> str:
    lines = [f"{report.name} — backend={report.backend}", ""]
    width = max((len(r.case_id) for r in report.results), default=10)
    for r in report.results:
        lines.append(
            f"{_MARK[r.status]:<6} {r.case_id:<{width}}  "
            f"expected={r.expected:<20} got={(r.predicted or '—'):<20} {r.detail[:48]}"
        )

    lines += ["", f"{'label':<22}{'support':>8}{'prec':>8}{'recall':>8}{'f1':>8}"]
    for s in report.per_label:
        lines.append(
            f"{s.label:<22}{s.support:>8}{s.precision:>8.3f}{s.recall:>8.3f}{s.f1:>8.3f}"
        )

    lines += [
        "",
        f"accuracy           {report.accuracy:.3f}",
        f"macro-F1           {report.macro_f1:.3f}",
        f"balanced accuracy  {report.balanced_accuracy:.3f}",
        f"majority baseline  {report.majority_baseline:.3f}   "
        f"<- accuracy below this means worse than always guessing the commonest label",
    ]
    if report.recall_at_k is not None:
        lines.append(f"recall@k           {report.recall_at_k:.3f}")
    if report.mrr is not None:
        lines.append(f"MRR                {report.mrr:.3f}")
    lines.append(
        "counts             "
        + ", ".join(f"{k}={v}" for k, v in sorted(report.counts.items()))
    )
    return "\n".join(lines)


def render_markdown_summary(report: EvalReport) -> str:
    lines = [
        f"### {report.name} (`{report.backend}`)",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| accuracy | {report.accuracy:.3f} |",
        f"| macro-F1 | {report.macro_f1:.3f} |",
        f"| balanced accuracy | {report.balanced_accuracy:.3f} |",
        f"| majority baseline | {report.majority_baseline:.3f} |",
    ]
    if report.recall_at_k is not None:
        lines.append(f"| recall@k | {report.recall_at_k:.3f} |")
    if report.mrr is not None:
        lines.append(f"| MRR | {report.mrr:.3f} |")
    lines += ["", f"`{', '.join(f'{k}={v}' for k, v in sorted(report.counts.items()))}`", ""]

    notable = [r for r in report.results if r.status in ("fail", "xpass", "error")]
    if notable:
        lines += ["| case | expected | got | status |", "|---|---|---|---|"]
        lines += [
            f"| `{r.case_id}` | {r.expected} | {r.predicted or '—'} | **{r.status}** |"
            for r in notable
        ]
    return "\n".join(lines)


def to_dict(report: EvalReport, *, stable: bool = False) -> dict[str, Any]:
    """Serialise a report. `stable=True` drops anything that varies run to run.

    Committed snapshots must be stable or they re-diff on every run and stop
    meaning anything.
    """
    return {
        "name": report.name,
        "backend": report.backend,
        **({} if stable else {"started_at": report.started_at}),
        "metrics": {
            "accuracy": round(report.accuracy, 6),
            "macro_f1": round(report.macro_f1, 6),
            "balanced_accuracy": round(report.balanced_accuracy, 6),
            "majority_baseline": round(report.majority_baseline, 6),
            **({} if report.recall_at_k is None else {"recall_at_k": round(report.recall_at_k, 6)}),
            **({} if report.mrr is None else {"mrr": round(report.mrr, 6)}),
        },
        "counts": dict(sorted(report.counts.items())),
        "per_label": [
            {
                "label": s.label,
                "support": s.support,
                "predicted": s.predicted,
                "true_positives": s.true_positives,
                "precision": round(s.precision, 6),
                "recall": round(s.recall, 6),
                "f1": round(s.f1, 6),
            }
            for s in report.per_label
        ],
        "results": [
            {
                "case_id": r.case_id,
                "expected": r.expected,
                "predicted": r.predicted,
                "status": r.status,
                **({} if stable else {"detail": r.detail, "elapsed_ms": r.elapsed_ms}),
                **({} if r.rank is None else {"rank": r.rank}),
            }
            for r in sorted(report.results, key=lambda r: r.case_id)
        ],
    }


def write_json(report: EvalReport, path: Path, *, stable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(report, stable=stable), indent=2, sort_keys=True) + "\n")
    return path


def diff_snapshot(report: EvalReport, snapshot: Path) -> list[str]:
    """Per-case differences against a committed snapshot. Empty list = identical."""
    if not snapshot.exists():
        return [f"snapshot {snapshot} does not exist — create it with --update-snapshot"]

    old = json.loads(snapshot.read_text())
    new = to_dict(report, stable=True)
    old_results = {r["case_id"]: r for r in old.get("results", [])}
    new_results = {r["case_id"]: r for r in new["results"]}

    diffs: list[str] = []
    for case_id in sorted(set(old_results) | set(new_results)):
        before, after = old_results.get(case_id), new_results.get(case_id)
        if before is None:
            diffs.append(f"+ {case_id}: new case ({after['status'] if after else '?'})")
        elif after is None:
            diffs.append(f"- {case_id}: case removed (was {before['status']})")
        elif before != after:
            diffs.append(
                f"~ {case_id}: {before['status']}/{before['predicted']} "
                f"-> {after['status']}/{after['predicted']}"
            )
    return diffs
