# Page 04 — Box / hotshot dimensions, accessories, flat fees

- **Source folder:** WhatsApp Unknown 2026-10-27 at 12.32.59 AM
- **Original file:** WhatsApp Image 2026-10-27 at 12.31.02 AM (1).jpeg
- **Status:** draft_unreviewed — **fees unapproved**
- **Topic:** Equipment specs + accessories + dispatcher flat rates

## Transcription

| Equipment | Length | Weight |
|---|---|---|
| Box truck | 24ft / 22ft | 10,000 to 12,000 lbs |
| Hot shot | 30ft / 40ft | " (same weight range as written) |

**Box truck : accessories**  
1. Lift gate  
2. Pallette Jack *(pallet jack)*

**Hot shot : accessories**  
1. Binders  
2. Straps  
3. Tarps  
4. Chains

**Payment Methods of Dispatcher:**  
Flat Rate  
- Box truck: $250 → revised **$300**  
- Hotshot: **$250 – 300**  
*(some scribbles / crossed words including “if both”)*

## Structured facts (candidate)

| Concept | Candidate field | Notes |
|---|---|---|
| Box length | trailerLength | 22–24 ft examples |
| Box payload range | preferredPayload / capacity | 10k–12k lbs — capacity ≠ rejected load weight |
| Hotshot length | trailerLength | 30 / 40 ft |
| Liftgate | equipment.liftgate | Installed accessory — not “load requires liftgate” |
| Pallet jack | equipment.pallet_jack | |
| Binders/straps/tarps/chains | equipment.accessories[] | Hotshot kit |
| Dispatcher flat fee | fee.flat by equipment | Unapproved |

## Critical distinction for Stage 1

Installed accessories ≠ load requirements (“loads that do not require a liftgate”).
