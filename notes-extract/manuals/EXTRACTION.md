# Freight Dispatch & Carrier Onboarding Manuals — staff extract

Sources (copied here; not indexed as packets):
- `Freight-Dispatch-Carrier-Onboarding-Guide.md.pdf`
- `Freight-Dispatch-SOP-FD-2026-v2.pdf` (SOP-FD-2026 v2.0)

Customer-facing RAG is only the curated `REGISTER` keys in `app/knowledge.py` (`ayyan_sales_v7`). This file is **staff / draft_unreviewed**. Do not paste unpublished rates or weekly targets into live chat copy.

## Ingested as Ayyan-safe register topics
- Freight roles (shipper / broker / dispatcher / carrier) and pay-to-carrier safeguard
- Equipment sizes & accessories (box 24–28, hotshot, van/reefer/flat/step/power-only)
- Cab types, solo/team, ELD (no HOS override from chat)
- Lane prefs (OTR vs local); daily home time remains Ayyan hard constraint when stated
- Doc checklist with review gate + driver load approval (not “auto-book on receipt”)
- Broker payment vocabulary without publishing deduction percents
- Fuel: no fuel card; advances only via agreement/ops
- Insurance typical industry ranges framed as onboarding-confirmed
- Time zones; MC age as review note (not automatic eligibility)

## Held out of live REGISTER (do not publish as Ayyan quotes)
| Item | Manual text | Policy |
|------|-------------|--------|
| Dispatcher flat fees | Box/hotshot $250–$300/wk; semi/PO $300–$350/wk | Use approved `fee_schedule` only |
| Commission close | 8–10% per load; close target 10% | Same — no invented fee |
| Jose pitch | Competitor 8% → close at 10% | Competitor key: don't match |
| Weekly revenue targets | $5k+ box/hotshot; $6k+ OTR semi | `guarantee` forbids weekly gross promises |
| MC age hard floor | Ideal 4–5 months minimum | Staff target only; chat uses `mc_age_review` |
| Immediate booking | “Once docs received, begin booking” | Overridden: review → then production; driver approves each load |
| Fuel advance SLA | Wire within 24–48 hrs | Ops/agreement only — not a chat promise |

## Raw text
See `guide-raw.txt` and `sop-raw.txt` extracted via `pdftotext`.
