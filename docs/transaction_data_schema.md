# Transaction Data Master Schema

**Purpose:** Single source of truth for every datum that ends up on any form
during a transaction. Capture once; reuse across DocuSign forms, the TW, emails,
addenda, and closing docs. This is the "master list" that drives form auto-fill.

**Sources are tracked per field** so the agent knows where to look:

- `TW` — agency team Transaction Worksheet (this is the canonical join)
- `MLS` — FlexMLS / Spark API
- `P&S` — Purchase & Sale agreement
- `Email` / `Text` — pulled from client correspondence
- `Tax` — town tax records / parcel lookup
- `Registry` — county Registry of Deeds
- `Title` — title company / closing attorney
- `Lender` — buyer's lender
- `Derived` — computed from other fields
- `Manual` — entered by TC; not extractable

**Last updated:** 2026-06-01.

---

## 0. Identifiers (join keys)

| Field | Type | Source | Notes |
|---|---|---|---|
| `docusign_room_id` | string | DocuSign | Every TW carries this at the top — it's the primary key linking TW ↔ Room ↔ all docs |
| `mls_number` | string | MLS | Secondary join when listing-side |
| `transaction_type` | enum | TW | Residential / Multi-Family / Commercial / Personal Property / Land / Other |
| `representation_side` | enum | Manual | Listing / Buyer / Dual / Lease |

---

## 1. Property

Most of this comes from MLS, but the **gaps you flagged** are the recorded-deed / tax-record items at the bottom.

| Field | Type | Source | Notes |
|---|---|---|---|
| `street_address` | string | TW / MLS | |
| `city` | string | TW / MLS | |
| `town` | string | Tax | **Maine quirk — sometimes differs from city/post office** |
| `state` | string | TW / MLS | Almost always "ME" |
| `zip` | string | TW / MLS | |
| `county` | string | Tax | Drives which Registry of Deeds is used |
| `parcel_id` / `tax_id` | string | Tax | aka "Map & Lot" — needed for tax bill, abatement, transfer tax. **Preserve source format verbatim — do not normalize.** |
| `map_lot` | string | Tax | Maine convention varies by town: `Map 12 Lot 34`, `012-034`, `U12-034`, `Map/Block/Lot` for subdivisions. **Preserve source format verbatim.** |
| `deed_book` | string | Registry | **Gap you flagged** — needed for title commitment / chain of title |
| `deed_page` | string | Registry | **Gap you flagged** — same |
| `prior_deed_date` | date | Registry | Previous owner's recording date |
| `legal_description` | text | Registry / P&S | Full metes & bounds or lot reference |
| `lot_size_acres` | number | MLS / Tax | |
| `lot_size_sqft` | number | MLS / Tax | |
| `year_built` | integer | MLS / Tax | **Required for lead paint disclosure trigger if <1978** |
| `square_footage` | number | MLS | |
| `bedrooms` | integer | MLS | |
| `bathrooms` | number | MLS | Half-baths => 0.5 |
| `subdivision` | string | MLS / Tax | If applicable |
| `hoa_or_condo_name` | string | MLS / Manual | |
| `hoa_dues_amount` | money | MLS / Manual | Monthly/quarterly/annual — note frequency |
| `septic_or_sewer` | enum | MLS | Septic / Public / Holding tank |
| `water_source` | enum | MLS | Well / Public / Other |
| `heat_type` | enum | MLS | Important for fuel oil/propane proration |
| `lockbox_code` | string | Manual | Sensitive — store in keychain not RAG |
| `showing_instructions` | text | Manual / MLS | |

---

## 2. Parties

### Sellers / Landlords

| Field | Type | Source |
|---|---|---|
| `seller_name_1` | string | TW |
| `seller_name_2` | string | TW |
| `seller_phone` | string | TW |
| `seller_email` | string | TW |
| `seller_forwarding_address` | text | TW |
| `seller_is_estate_or_trust` | bool | P&S | Triggers extra docs (executor, trustee certs) |
| `seller_attorney_name` | string | Email / Manual | If represented |
| `seller_attorney_email` | string | Email / Manual | |

### Buyers / Tenants

| Field | Type | Source |
|---|---|---|
| `buyer_name_1` | string | TW |
| `buyer_name_2` | string | TW |
| `buyer_phone` | string | TW |
| `buyer_email` | string | TW |
| `buyer_forwarding_address` | text | TW |
| `buyer_previous_zip` | string | TW | (Cartus / referral tracking) |
| `buyer_is_first_time` | bool | Manual | Triggers MSHA eligibility flags |
| `buyer_attorney_name` | string | Email / Manual | |
| `buyer_attorney_email` | string | Email / Manual | |

### Agents

| Field | Type | Source |
|---|---|---|
| `listing_agent_name` | string | TW / MLS |
| `listing_agency` | string | TW / MLS |
| `buyer_agent_name` | string | TW / MLS |
| `buyer_agency` | string | TW / MLS |
| `co_listing_agent` | string | TW / MLS | If applicable |
| `co_buyer_agent` | string | TW / MLS | |
| `designated_broker` | string | Manual | Required for compliance per Title 32 §13184 |
| `unrepresented_party` | bool | TW | Triggers extra disclosures |

### Third parties

| Field | Type | Source |
|---|---|---|
| `closing_company_name` | string | TW |
| `closing_company_attorney` | string | Email / Manual |
| `closing_company_address` | text | Manual |
| `closing_company_phone` | string | Manual |
| `closing_company_email` | string | Email |
| `lender_name` | string | TW |
| `lender_loan_officer` | string | Email / Manual |
| `lender_loan_officer_email` | string | Email / Manual |
| `lender_loan_officer_phone` | string | Email / Manual |
| `appraiser_name` | string | TW | Only if not in FlexMLS |
| `appraiser_phone` | string | TW |
| `appraiser_email` | string | TW |
| `inspector_name` | string | Email / Manual |
| `inspector_email` | string | Email / Manual |
| `inspector_phone` | string | Email / Manual |
| `title_insurer_name` | string | Title | |
| `title_insurer_owners_policy` | bool | Title | Per the lead agent's buyer-side P&P |

---

## 3. Listing & Commissions

| Field | Type | Source |
|---|---|---|
| `list_price` | money | MLS |
| `list_date` | date | MLS |
| `total_listing_commission_rate_pct` | number | TW |
| `mls_buyer_offered_split_pct` | number | TW |
| `buyer_agency_fee_pct` | number | TW |
| `agency_listing_rate_pct` | number | TW | If ERA listing |
| `mls_rate_offered_buyer_agent_pct` | number | TW |
| `agency_commission_amount` | money | TW |
| `checks_amounts_received` | money | TW |
| `buyer_agency_fee_charged` | bool | TW |
| `buyer_agency_fee_amount` | money | TW |
| `team_splits` | text | TW | side / person / split% — free-form |
| `referrals_exist` | bool | TW |
| `referral_name_and_agency` | string | TW |
| `referral_side_and_amount` | string | TW |
| `agent_is_principal` | bool | TW | Primary residence / Personal investment |

---

## 4. Critical dates

These are the deadline drivers the TC tracks. Most aren't on the TW — they live in the P&S and its addenda.

| Field | Type | Source |
|---|---|---|
| `effective_date` | date | TW / P&S | **Appears as "Contract Date" on the TW** — same field. This is the date of last party signature (mutual acceptance) and drives all downstream P&S deadlines below. |
| `emd_due_date` | date | P&S |
| `emd_delivered_date` | date | Email / Manual |
| `inspection_deadline` | date | P&S |
| `inspection_response_deadline` | date | P&S | Buyer's window to object after inspection |
| `inspection_resolution_deadline` | date | P&S | Seller's window to respond |
| `title_review_deadline` | date | P&S |
| `financing_commitment_deadline` | date | P&S | aka "loan commitment letter" |
| `appraisal_deadline` | date | P&S |
| `walk_through_date` | date | Email / Manual |
| `estimated_closing_date` | date | TW |
| `closing_date` | date | TW |
| `possession_date` | date | P&S | Usually = closing but can differ |
| `closing_time` | time | Email / Manual |
| `closing_location` | string | Email / Manual | Usually title attorney's office |

---

## 5. Financial

| Field | Type | Source |
|---|---|---|
| `estimated_sale_price` | money | TW |
| `final_sale_price` | money | TW |
| `emd_amount` | money | TW |
| `emd_held_at_agency` | bool | TW |
| `emd_released_to_title_before_close` | bool | TW |
| `seller_closing_cost_contribution_amount` | money | TW |
| `down_payment_amount` | money | Lender |
| `down_payment_pct` | number | Derived |
| `loan_amount` | money | Lender |
| `cash_to_close` | money | Title | From closing statement |
| `seller_net_proceeds` | money | Title | From closing statement |
| `sold_terms` | enum | TW | Cash / Conv / Conv.Ins / FHA / FMHA-RD / MSHA / Private / VA / Bank Owned / Court Ordered / Estate Sale / Foreclosure / Relocation / Short Sale / Other |
| `arms_length_transaction` | bool | TW |

---

## 6. Closing details

| Field | Type | Source |
|---|---|---|
| `acreage_changed_at_closing` | bool | TW |
| `new_acreage` | number | TW | If changed |
| `appraisal_done` | bool | TW |
| `appraiser_in_flexmls` | bool | TW |
| `yard_arm_sign_removed` | bool | TW |
| `closing_disclosure_received` | bool | Email |
| `closing_disclosure_date` | date | Email |
| `settlement_statement_received` | bool | Title |
| `wiring_instructions_delivered` | bool | Manual |
| `poa_needed` | bool | Manual |
| `mail_away_signing` | bool | Manual |

---

## 7. Disclosures & flags

| Field | Type | Source |
|---|---|---|
| `lead_paint_disclosure_required` | bool | Derived | True if `year_built` < 1978 |
| `lead_paint_disclosure_delivered_date` | date | Manual |
| `agency_disclosure_signed_date` | date | DocuSign | Maine §13278 |
| `property_disclosure_form_date` | date | DocuSign | Maine residential standard |
| `is_cartus_referral` | enum | TW | Seller / Buyer / N/A |
| `franchise_moves_optout` | enum | TW | Seller / Buyer |
| `insurance_quote_requested` | bool | TW |
| `pending_status_kickout` | bool | TW |
| `pending_status_continue_to_show` | bool | TW |

---

## 8. Lease-only (Page 2 of TW)

Applies when `transaction_type = Lease` or `representation_side = Lease`.

| Field | Type | Source |
|---|---|---|
| `lease_type` | enum | TW | Gross / ModGross / Net / ModNet / Industrial Gross / Full Service / Absolute NNN / NNN |
| `landlord_name_1` | string | TW |
| `landlord_name_2` | string | TW |
| `landlord_email` | string | TW |
| `landlord_phone` | string | TW |
| `tenant_name_1` | string | TW |
| `tenant_name_2` | string | TW |
| `tenant_email` | string | TW |
| `tenant_phone` | string | TW |
| `agreement_date` | date | TW |
| `commencement_date` | date | TW |
| `expiration_date` | date | TW |
| `term_months` | integer | TW |
| `right_to_renew` | bool | TW |
| `sub_lease_allowed` | bool | TW |
| `lease_rate` | money | TW |
| `lease_area_sqft` | number | TW |

---

## 9. Other income (referrals not tied to a deal)

| Field | Type | Source |
|---|---|---|
| `other_income_property_address` | string | TW |
| `other_income_agent_name` | string | TW |
| `other_income_type` | string | TW |
| `other_income_date_received` | date | TW |
| `other_income_amount` | money | TW |

---

## 10. Logistics & post-close (not on TW)

These don't appear on the TW but show up across emails and need to be tracked.

| Field | Type | Source |
|---|---|---|
| `utility_electric_provider` | string | Manual / Email |
| `utility_water_provider` | string | Manual / Email |
| `utility_heat_provider` | string | Manual / Email |
| `utility_internet_provider` | string | Manual / Email |
| `fuel_oil_reading_date` | date | Manual | For proration |
| `fuel_oil_gallons` | number | Manual | For proration |
| `propane_tank_leased` | bool | MLS / Manual |
| `propane_lease_company` | string | Manual |
| `propane_account_number` | string | Manual |
| `vendor_list_sent_date` | date | Manual |
| `closing_gift_sent` | bool | Manual | Reminder to the lead agent per P&P |

---

## Resolved decisions

- **Parcel format:** preserve the source's format verbatim — no normalization.
  Map/Lot and Parcel ID can each appear in whatever style the town/MLS uses.
- **Effective date vs. contract date:** treat them as the same field. The TW's
  "Contract Date" entry is the effective date — that's how the lead agent uses it, and
  all P&S deadlines compute from it.

## Open questions

Bring to the lead agent or punt for later:

1. **Deed book/page** — when in the workflow does the TC need this? Title
   commitment time, or earlier?
2. **Lockbox code storage** — sensitive. Don't ingest into RAG. Suggest:
   keychain entry per room ID, surfaced via UI only.
3. **Closing attorney address/phone** — not on TW. Where does the lead agent keep these?
   (Brokerage rolodex? Per-deal manual entry?)
4. **POA / mail-away** — current workflow appears to be ad-hoc. Worth a sub-form?
5. **Maine transfer tax** — calculated as $2.20 per $500 of consideration.
   Should we auto-compute and stash on the schema? (Useful for net-sheet generation.)

---

## How this gets used

1. **Schema lives in this markdown file** — single source of truth, easy to edit, version-controlled.
2. **Ingest into RAG** so the email agent can ground extraction prompts in the canonical field names.
3. **Promote to Pydantic** when stable — `src/realtorai/schemas/transaction.py` becomes the typed in-code mirror.
4. **DocuSign field mapping** — each DocuSign form template has its own field names; build a mapping layer (`field_alias → canonical_field`) so the master schema feeds every form.
5. **Population pipeline** —
   ```
   email/text/MLS/manual entry
     → extraction agent (canonical names)
     → master transaction record (per-deal, keyed by docusign_room_id)
     → DocuSign field mapper
     → auto-filled form in Room
   ```
