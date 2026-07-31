"""One-shot recorded-deed pull from a Maine county registry.

Wraps realtorai.integrations.registry — plain HTTP against the registry's
own site (Browntech ALIS counties), no browser, no login. Optionally runs
the Opus deed review on the fetched scan when ANTHROPIC_API_KEY is set.

Usage:
    python scripts/deed_lookup.py penobscot 16601 156
    python scripts/deed_lookup.py penobscot 16601 156 --review
    python scripts/deed_lookup.py penobscot 16601 156 --town Orono --owner "Morgan T. Rowe"
"""

import argparse
import asyncio
import sys
from pathlib import Path

from realtorai.integrations.registry import fetch_deed


async def run(args: argparse.Namespace) -> int:
    out_dir = args.out.expanduser() / f"{args.county.lower()}_bk{args.book}_pg{args.page}"
    try:
        record, pdf_path, md_path = await fetch_deed(
            args.county, args.book, args.page, out_dir,
            expect_town=args.town, expect_owner=args.owner,
        )
    except LookupError as e:
        print(f"UNSUPPORTED: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    print(f"Document : Bk {record.book} / Pg {record.page}  ({record.county} County)")
    print(f"Type     : {record.doc_type or 'n/a'}  ({record.page_count or '?'} pages)")
    print(f"Recorded : {record.recorded_date or 'n/a'}  doc date {record.doc_date or 'n/a'}")
    print(f"Town     : {record.town or 'n/a'}")
    print(f"Grantor  : {'; '.join(record.grantors) or 'n/a'}")
    print(f"Grantee  : {'; '.join(record.grantees) or 'n/a'}")
    if record.town_matches_record is not None:
        print(f"Town check   : {'OK' if record.town_matches_record else 'MISMATCH'}")
    if record.owner_matches_grantee is not None:
        print(f"Owner check  : {'OK' if record.owner_matches_grantee else 'MISMATCH'}")
    print(f"PDF      : {pdf_path}")
    print(f"Report   : {md_path}")

    if args.review:
        from realtorai.inference.claude_engine import get_claude_engine

        if not get_claude_engine().available:
            print("(--review skipped: no ANTHROPIC_API_KEY)", file=sys.stderr)
            return 0
        from realtorai.workflows.deed_review import (
            render_deed_review_markdown,
            review_deed,
        )

        label = f"Bk {record.book}/Pg {record.page}, {record.town or record.county}"
        report = await review_deed(property_label=label, deed_pdf=pdf_path.read_bytes())
        review_path = out_dir / "deed_review.md"
        review_path.write_text(render_deed_review_markdown(report, label))
        print(f"\nDeed review — {len(report.findings)} finding(s)"
              + (" — OUT OF THE ORDINARY" if report.out_of_ordinary else ""))
        for finding in report.findings:
            print(f"  [{finding.severity}] {finding.kind}: {finding.explanation}")
        print(f"Review   : {review_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a recorded deed by book/page")
    parser.add_argument("county", help="County name, e.g. penobscot")
    parser.add_argument("book")
    parser.add_argument("page")
    parser.add_argument("--town", help="Expected town (cross-check)")
    parser.add_argument("--owner", help="Expected current owner (grantee cross-check)")
    parser.add_argument("--review", action="store_true", help="Run Opus deed review on the scan")
    parser.add_argument("--out", type=Path, default=Path("data/deed_lookups"))
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
