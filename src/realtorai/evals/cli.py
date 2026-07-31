"""Command line for the evals.

    python -m realtorai.evals intake --backend heuristic
    python -m realtorai.evals intake --backend live --metric macro_f1 --threshold 0.90
    python -m realtorai.evals retrieval --min-cases 4
    python -m realtorai.evals schema-coverage
    python -m realtorai.evals compare before.json after.json

Exit codes are the load-bearing part:

    0  everything passed
    1  a real failure — below threshold, snapshot drift, or an unexpected miss
    2  could not run: no API key, empty vector store, --min-cases unmet

The old scripts returned 1 for "no API key configured", which is why neither
could ever be a CI step — a missing optional secret was indistinguishable from
a regression. Splitting 2 out is what lets a workflow treat "unavailable" as
neutral and still fail loudly on 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

from realtorai.evals import harness
from realtorai.evals.harness import EvalReport

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_UNAVAILABLE = 2

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", type=Path, help="Write the full report here")
    parser.add_argument("--snapshot", type=Path, help="Compare against a committed report")
    parser.add_argument(
        "--update-snapshot",
        action="store_true",
        help="Rewrite the snapshot instead of comparing (local only, never in CI)",
    )
    parser.add_argument("--threshold", type=float, help="Minimum value for --metric")
    parser.add_argument("--metric", default="macro_f1", help="Metric --threshold applies to")
    parser.add_argument(
        "--filter", action="append", default=[], help="Keep cases matching id or tag; repeatable"
    )
    parser.add_argument("--min-cases", type=int, default=0, help="Fail if fewer cases ran")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--github-summary", action="store_true", help="Append markdown to $GITHUB_STEP_SUMMARY"
    )


def _select(cases: Sequence[harness.Case], patterns: Sequence[str]) -> list[harness.Case]:
    wanted = [p for p in patterns if p]
    if not wanted:
        return list(cases)
    return [c for c in cases if any(p in c.id or p in c.tags for p in wanted)]


def _emit(report: EvalReport, args: argparse.Namespace) -> int:
    print(harness.render_table(report))

    if args.json:
        harness.write_json(report, args.json)
        print(f"\nwrote {args.json}")

    if args.github_summary:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(harness.render_markdown_summary(report) + "\n")

    status = EXIT_OK

    if args.min_cases and report.scored < args.min_cases:
        print(
            f"\nFAIL: only {report.scored} case(s) ran, --min-cases {args.min_cases}. "
            "Everything skipped reads as green without this check.",
        )
        return EXIT_UNAVAILABLE

    if not report.ok:
        bad = ", ".join(
            f"{k}={v}" for k, v in sorted(report.counts.items()) if k in ("fail", "error", "xpass")
        )
        print(f"\nFAIL: {bad}")
        if report.counts.get("xpass"):
            print("  an xpass means a case marked as a known miss now passes — "
                  "remove it from xfail_backends.")
        status = EXIT_FAIL

    if args.snapshot:
        if args.update_snapshot:
            harness.write_json(report, args.snapshot, stable=True)
            print(f"\nupdated snapshot {args.snapshot}")
        else:
            diffs = harness.diff_snapshot(report, args.snapshot)
            if diffs:
                print("\nFAIL: snapshot drift")
                for line in diffs:
                    print(f"  {line}")
                print(f"  if intended: rerun with --update-snapshot and commit {args.snapshot}")
                status = EXIT_FAIL

    if args.threshold is not None:
        value = report.metric(args.metric)
        if value < args.threshold:
            print(f"\nFAIL: {args.metric} {value:.3f} < threshold {args.threshold:.3f}")
            status = EXIT_FAIL
        else:
            print(f"\n{args.metric} {value:.3f} >= threshold {args.threshold:.3f}")

    return status


def run_intake(args: argparse.Namespace) -> int:
    from realtorai.evals.backends import INTAKE_BACKENDS
    from realtorai.evals.cases.intake import INTAKE_CASES, INTAKE_LABELS

    if args.backend == "live":
        from realtorai.inference.claude_engine import get_claude_engine

        if not get_claude_engine().available:
            print("ANTHROPIC_API_KEY is not configured — the live backend cannot run.")
            print("This is 'unavailable' (exit 2), not a failing eval.")
            return EXIT_UNAVAILABLE

    cases = _select(INTAKE_CASES, args.filter)
    if not cases:
        print(f"No cases matched {args.filter}.")
        return EXIT_UNAVAILABLE

    report = asyncio.run(
        harness.run_suite(
            "intake-classifier",
            cases,
            INTAKE_BACKENDS[args.backend],
            backend=args.backend,
            labels=INTAKE_LABELS,
            concurrency=args.concurrency,
        )
    )
    return _emit(report, args)


def run_retrieval(args: argparse.Namespace) -> int:
    from realtorai.evals.backends import ingested_sources, retrieval_hit
    from realtorai.evals.cases.retrieval import RETRIEVAL_CASES

    available = ingested_sources()
    if not available:
        print("The knowledge base is empty — ingest a corpus first:")
        print("  python -m realtorai.evals fetch-corpus --dest data/corpus")
        print("  realtorai ingest data/corpus/*.pdf")
        return EXIT_UNAVAILABLE

    cases = _select(RETRIEVAL_CASES, args.filter)
    report = asyncio.run(
        harness.run_suite(
            "kb-retrieval",
            cases,
            retrieval_hit,
            backend="chroma",
            available_resources=available,
            concurrency=args.concurrency,
            ranked=True,
        )
    )
    return _emit(report, args)


def run_schema_coverage(args: argparse.Namespace) -> int:
    from realtorai.evals import schema_coverage

    print(schema_coverage.summary())
    issues = schema_coverage.problems()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "summary": schema_coverage.summary(),
                    "problems": issues,
                    "audit": {
                        name: {"disposition": str(d), "detail": detail}
                        for name, (d, detail) in schema_coverage.audit().items()
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(f"wrote {args.json}")

    if args.github_summary:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            body = ["### Schema coverage", "", schema_coverage.summary(), ""]
            body += [f"- {p}" for p in issues] if issues else ["All record fields reachable."]
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(body) + "\n")

    if issues:
        print("\nFAIL:")
        for problem in issues:
            print(f"  {problem}")
        return EXIT_FAIL

    print("Every record field reaches a destination or states why it does not.")
    return EXIT_OK


def run_compare(args: argparse.Namespace) -> int:
    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())

    lines = [
        f"### {before.get('backend', '?')} vs {after.get('backend', '?')}",
        "",
        "| metric | " + str(before.get("backend", "before")) + " | "
        + str(after.get("backend", "after")) + " | delta |",
        "|---|---:|---:|---:|",
    ]
    for key in ("accuracy", "macro_f1", "balanced_accuracy"):
        lhs = float(before.get("metrics", {}).get(key, 0.0))
        rhs = float(after.get("metrics", {}).get(key, 0.0))
        lines.append(f"| {key} | {lhs:.3f} | {rhs:.3f} | {rhs - lhs:+.3f} |")

    before_results = {r["case_id"]: r for r in before.get("results", [])}
    differing = [
        f"| `{r['case_id']}` | {before_results[r['case_id']]['predicted']} | {r['predicted']} |"
        for r in after.get("results", [])
        if r["case_id"] in before_results
        and before_results[r["case_id"]]["predicted"] != r["predicted"]
    ]
    if differing:
        lines += ["", "Cases where the backends disagree:", "",
                  "| case | " + str(before.get("backend", "before")) + " | "
                  + str(after.get("backend", "after")) + " |", "|---|---|---|", *differing]

    body = "\n".join(lines)
    print(body)
    if args.github_summary:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(body + "\n")
    return EXIT_OK


def run_fetch_corpus(args: argparse.Namespace) -> int:
    from realtorai.evals.corpus import fetch_all

    try:
        written = fetch_all(args.dest)
    except Exception as exc:
        print(f"Could not fetch the corpus: {exc}")
        return EXIT_UNAVAILABLE
    for path in written:
        print(f"  {path}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m realtorai.evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    intake = sub.add_parser("intake", help="Intake classifier accuracy")
    intake.add_argument("--backend", choices=("heuristic", "live"), default="heuristic")
    _add_common(intake)
    intake.set_defaults(func=run_intake)

    retrieval = sub.add_parser("retrieval", help="Knowledge-base retrieval recall")
    _add_common(retrieval)
    retrieval.set_defaults(func=run_retrieval, backend="chroma")

    coverage = sub.add_parser("schema-coverage", help="Every record field reaches a form")
    coverage.add_argument("--json", type=Path)
    coverage.add_argument("--github-summary", action="store_true")
    coverage.set_defaults(func=run_schema_coverage)

    compare = sub.add_parser("compare", help="Diff two reports")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--github-summary", action="store_true")
    compare.set_defaults(func=run_compare)

    corpus = sub.add_parser("fetch-corpus", help="Download the public legal PDFs")
    corpus.add_argument("--dest", type=Path, default=Path("data/corpus"))
    corpus.set_defaults(func=run_fetch_corpus)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result
