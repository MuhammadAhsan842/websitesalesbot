# Page 05 — Cargo coverage, trailer types, weights

- **Source folder:** WhatsApp Unknown 2026-10-27 at 12.32.59 AM
- **Original file:** WhatsApp Image 2026-10-27 at 12.31.03 AM.jpeg
- **Status:** draft_unreviewed — **coverage amounts unapproved**
- **Topic:** Docs + trailer catalogue + capacity

## Transcription

- Cargo coverage: 100,000 dollar  
- Photos of truck  
- Truck registration sheet  

**Types of trailer**  
1. Dry Van  
2. Reefer [cold, hot]  
3. flatbed  
4. step deck  

Note: In front of them if a truck attached becomes [power only]

| Trailer | Length | Weight |
|---|---|---|
| Dry Van | 48, 53 ft | 40k → 48k lbs |
| Reefer | // // | // → // |
| flatbed | // // | 40k → 100,000 lbs *(48k crossed out upward)* |
| Stepdeck | // // | // // |

## Structured facts (candidate)

| Concept | Candidate field | Notes |
|---|---|---|
| Cargo coverage amount | insurance.cargo | $100k note — unapproved |
| Truck photos / registration | requirements | |
| Dry van / reefer / flatbed / step deck | equipment | Step deck not in current bot catalogue |
| Power only | power_only when tractor + trailer pairing | |
| Length / weight ranges | capacity facts | Validation hints only |

## Uncertain

- Flatbed “100,000 lbs” may be a max example; treat carefully.
- Step deck absent from current `EQUIP_KEYS`.
