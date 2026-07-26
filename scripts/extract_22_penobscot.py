"""Build a TransactionRecord from the 22 Penobscot St document set.

Extracted from:
  - 22 penobscot deed.PDF                                 (Penobscot Registry, Aug 2022)
  - 22 penobscot tax card.pdf                             (Vision Govt Solutions / town assessor)
  - exclusive_right_to_sell_listing_agreement__126.pdf    (The Agency, signed May 2026)
  - maine_real_estate_commission_brokerage_relationships  (MREC Form #3, May 31 2026)
  - lead_paint_disclosure...                              (Maine MAR, 2026)
  - property_disclosure...                                (Maine MAR, 8-section seller disclosure)

This is the Brett-as-seller listing for 22 Penobscot St, Orono.
The record itself lives in realtorai.fixtures so the demos, UI, and tests
share it; this script pretty-prints it.
"""

from realtorai.fixtures import build_22_penobscot as build  # noqa: F401  (re-export)


def main() -> None:
    rec = build()
    print("=== TransactionRecord: 22 Penobscot St ===\n")
    # Pretty-print, skipping None and empty Party objects
    d = rec.model_dump(exclude_none=True)
    for k, v in d.items():
        if isinstance(v, dict):
            if not any(v.values()):
                continue
            print(f"  {k}:")
            for sk, sv in v.items():
                if sv is not None:
                    print(f"    {sk}: {sv}")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
