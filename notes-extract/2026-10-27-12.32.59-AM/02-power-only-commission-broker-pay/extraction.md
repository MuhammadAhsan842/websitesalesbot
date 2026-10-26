# Page 02 — Power only, commission, broker payment methods

- **Source folder:** WhatsApp Unknown 2026-10-27 at 12.32.59 AM
- **Original file:** WhatsApp Image 2026-10-27 at 12.31.01 AM.jpeg
- **Status:** draft_unreviewed — **handwritten rates ≠ published fee schedule**
- **Topic:** Equipment pricing + broker pay options
- **Note:** Near-duplicate of page 03 in this folder; keep both for source integrity.

## Transcription

★ Power only → no trailer  
→ Semi truck  
Semi truck = 300 / 350 $  
Flat rate [decided rate] [fixed amount will be received]

2) Commission:  
- Box truck: 8 to 10%  
- Hot shot: // // (same)  
- Semis = 3 to 5%

Payment Method of Broker  

1) Standard pay = 24/28 days time — 0% deductions  
2) Quick Pay = 3/4 days — 3/4 percent deduct  
   → we receive a voided cheque  
3) Factoring: Within 24 hours — 5/6% deduct  
   ✓ 3rd party company for payment method

## Structured facts (candidate)

| Concept | Candidate field | Notes |
|---|---|---|
| Power only | equipment.power_only / no trailer | Distinct from box/hotshot |
| Semi flat fee | fee.flat | $300–350 — unapproved |
| Box/hotshot commission | fee.percent by equipment | 8–10% — unapproved |
| Semi commission | fee.percent | 3–5% — unapproved |
| Broker standard pay | broker_payment.standard | Timing + 0% deduct |
| Quick pay | broker_payment.quick_pay | Timing + deduct; voided check |
| Factoring | broker_payment.factoring | Timing + deduct; 3rd party |

## Policy caution

Dispatch fees, quick-pay deductions, factoring fees, and carrier settlement % must stay separate fields. Do not load into live bot until staff publish.
