# Handwritten notes — extraction analysis

**Status:** `draft_unreviewed` — useful for Stage 1–3 design; **not** live company policy / RAG rates.

## What the pages teach (by theme)

### A. Qualification conversation (26 Oct)
| Page | Content | Bot implication |
|---|---|---|
| Symmetry conversation | Greeting → truck → accessories → MC (age) → insurance / no-MC→NTL; auto 750k–1M; cargo 100k | Adaptive ASK order; split insurance types; MC age is a fact, not auto-eligibility |
| Operating preferences | OTR vs local, miles/day, Mon–Fri, home-every-night not standard, prefer profitable week | Add `regional`; don’t force OTR/local only |
| Start + docs | Short onboarding; DL + COI as holder → then dispatch | Docs received ≠ approved; dispatch after review |
| Registration close | Registration + photos; start date; soft close | Checklist items |
| Jose anecdote | 8% → convince 10% OTR | Negotiation strategy evidence only — **do not publish as fee** |
| Fuel card | No fuel card; money in 24–48h | Objection copy — **unapproved timing** |

### B. Money, equipment, roles (27 Oct)
| Page | Content | Bot implication |
|---|---|---|
| NOA | NOA required **for factoring** | Conditional requirement — do not always demand NOA |
| Commission / broker pay | Power-only flat $300–350; box/hotshot 8–10%; semis 3–5%; Standard / Quick Pay (+voided check) / Factoring | Separate dispatch fee vs broker-pay deductions; voided check ↔ quick pay |
| Box/hotshot dims | Box 22–24ft, ~10k–17k lbs; hotshot 30/40ft; liftgate/pallet jack vs straps/chains/tarps/binders; dispatcher flat $250–300 | Accessories ≠ load requirements; flat fees unapproved |
| Trailers + cargo | Dry van/reefer/flatbed/step deck; 48/53; cargo $100k note; tractor+trailer → power only framing | Expand equipment catalogue carefully |
| Cab / ELD / lease | Day vs sleeper; solo 11h / team; ELD; lease-on: DL + COI holder 750k–1M; broker pays MC owner | Lease checklist; settlement routing note |
| Roles / timezones | Shipper→broker→dispatcher→carrier; rate negotiate + docs; MC/FMCSA; US zones | Safe vocabulary for explanations |

## Corrections vs earlier extract
- Box truck payload note updated to **10,000–17,000 lbs** (this image set).
- Power-only arrow reads toward **trailer / semi** pairing (tractor without owned trailer).

## What must NOT go into live RAG yet
- Any % or $ fee (8–10%, 3–5%, $300 flat, quick-pay 3–4%, factoring 5–6%).
- Hard MC age rule (4–5 months).
- Hard insurance limits until staff publish policy.
- Fuel advance 24–48h as a commitment.
- Jose 10% “convincing” pitch as Ayyan rate.

## Implementation mapping (this build)
1. **Done / in progress:** structured facts, Sprinter, explanation memory, conditional NOA/voided check in `requirements.py`.
2. **Next:** upload → case_files + checklist; per-doc decide; approve only when ready; keep sample ingest labeled demo-only.
3. **Later:** staff-published fee schedule by equipment; reviewed RAG entries from cleaned pages.
