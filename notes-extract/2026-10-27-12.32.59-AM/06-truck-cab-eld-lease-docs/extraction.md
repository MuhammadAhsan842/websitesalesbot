# Page 06 — Cab types, drivers, ELD, FMCSA, lease-on docs

- **Source folder:** WhatsApp Unknown 2026-10-27 at 12.32.59 AM
- **Original file:** WhatsApp Image 2026-10-27 at 12.31.03 AM (1).jpeg
- **Status:** draft_unreviewed
- **Topic:** Equipment/driver taxonomy + lease-on packet hints

## Transcription

[Broker will send money into only MC owner account.]

**Types of Truck**  
- Day Cab, Night CAB (Sleeper cab)  
  → Night CAB: sleeping space as well.

**Types of Driver**  
- Solo driver (11 hours)  
- Team driver  

**ELD device:**  
[Electronic login device] *(likely Electronic Logging Device)*  
→ how many hours has the driver driven  

**FMCSA:**  
Federal motor carrier safety administration.  

MC / if Not MC (dispatcher gives MC)  
→ MC lease ON  

1. Driving license  
2. COI [as holder of our company Name and address.] [750K – 1ML Dollar] automobile coverage  

## Structured facts (candidate)

| Concept | Candidate field | Notes |
|---|---|---|
| Settlement to MC owner | payment routing note | Broker pays MC owner account |
| Day cab / sleeper | equipment.cab_type | |
| Solo / team | driver.mode | 11h = HOS context |
| ELD | docs_eld / compliance | |
| FMCSA | regulatory | |
| Lease-on | mcOwnership=no_own_mc | Dispatcher/company MC |
| Lease docs | licence, COI with holder | Auto liability 750k–1M — unapproved |

## Policy caution

“Dispatcher gives MC” / lease-on eligibility is staff decision, not bot auto-approval.
