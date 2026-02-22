# Trump Tariff Intelligence Desk

Internal procurement intelligence dashboard focused on U.S. tariff actions, countermeasures, and landed-cost scenario modeling.

This build is designed for Siemens Healthineers global procurement users who need:
- Fast country-level view of active vs contested U.S. tariff measures.
- Commodity-level view of affected products and tariff programs.
- Daily official-feed monitoring from reputable primary sources.
- Scenario calculator for planning landed-cost impact.

## What Is Included

- `index.html`
  - Single-page intelligence desk with tabs for Dashboard, Country Explorer, Commodity Matrix, Timeline, Live Feeds, Tariff Calculator, Sourcebook, and Gaps.
- `scripts/update_live_intel.py`
  - Pulls latest official feed data and writes `data/live_intel.json`.
- `data/live_intel.json`
  - Generated live feed artifact consumed by frontend.
- `.github/workflows/daily-intel-update.yml`
  - Daily auto-refresh workflow for `data/live_intel.json`.

## Reputable Source Policy

The live ingestion script only pulls from primary/public official sources in this build:
- U.S. Federal Register API.
- U.S. CBP CSMS (GovDelivery RSS).
- European Commission Press Corner RSS.
- UK GOV.UK DBT Atom feed.
- MOFCOM English site (headline extraction).
- Government of Canada Department of Finance tariff response page.

## Local Run

No framework build is required.

1. Refresh live feed data:
```bash
python3 scripts/update_live_intel.py
```

2. Open the site:
```bash
open index.html
```

Or serve locally:
```bash
python3 -m http.server 8000
# then open http://localhost:8000
```

## Live Feed Data Schema

`data/live_intel.json` structure:
- `generated_at`: UTC timestamp for data build.
- `about`: ingestion metadata and keyword filters.
- `feeds.federal_register`: deduped tariff-relevant Federal Register docs.
- `feeds.cbp_csms`: filtered CSMS operational messages.
- `feeds.retaliation.eu_commission`
- `feeds.retaliation.uk_dbt`
- `feeds.retaliation.china_mofcom`
- `feeds.retaliation.canada_finance`

Each feed includes:
- `source`
- `source_url`
- `items`
- `errors`

## Calculator Assumptions

The HTS landed-cost calculator is an estimator for planning, not customs entry filing.

Current logic:
- Inputs for country, commodity program, customs value, freight/insurance, MFN rate, and optional Section 301 rate.
- Optional contested IEEPA inclusion.
- Optional non-stacking simplification (highest special-duty bucket applied).
- Canada/Mexico USMCA + energy/potash toggles.
- Brazil targeted-products toggle.

Known limitations:
- Not a substitute for HTS line-level legal determination.
- Does not fully model AD/CVD, quota fill effects, or exclusions.
- Does not guarantee exact duty sequencing for all legal permutations.

## Automation

GitHub Action schedule: `30 6 * * *` (daily at 06:30 UTC).

Workflow behavior:
- Runs `scripts/update_live_intel.py`.
- Commits and pushes `data/live_intel.json` only when content changes.

## Compliance Note

This repository is an internal intelligence tool and not legal advice. Always confirm execution decisions against the latest official customs notices, legal texts, and counsel review before shipment booking.
