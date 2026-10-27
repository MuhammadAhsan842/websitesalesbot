### GL07 — BOL, POD and invoicing

A bill of lading records shipment details and receipt of freight. Signed delivery evidence is commonly called proof of delivery. Required shipment paperwork and receipts support invoicing; their presence does not guarantee a payment date.

### GL08 — Quick pay, factoring payment and fuel advances

Quick pay accelerates payment under a payer’s terms. Factoring payment follows a separate agreement. A fuel advance funds a pre-delivery need and is not the same as faster post-delivery settlement. Fees, eligibility and timing must be verified.

### GL09 — ELD, HOS and appointment time zones

ELD means Electronic Logging Device. Hours of service cannot be reduced to one universal daily driving figure. Trip planning needs actual driver availability and applicable rules. Appointment conversions need the date and correct location/time zone.

### GL10 — Accessorials and empty miles

Detention, layover and truck ordered not used (TONU) are examples of charges whose applicability depends on agreement and evidence. Deadhead means movement without a paying load; compare total-trip economics rather than loaded RPM alone.

## General workflow — operational explanation, not a tool capability

1. Onboarding first establishes the applicable arrangement, documents, agreement and review state. Receiving documents does not itself authorize dispatch.
2. Operational dispatch starts from actual truck location, empty/loaded state, equipment, constraints and driver availability.
3. Authorized staff search available sources and evaluate route, weight, appointments, deadhead, total cost and broker requirements. Background knowledge is not a live search result.
4. The driver/carrier considers the option and gives the required approval. Authorized parties negotiate and accept the load under the applicable terms.
5. After confirmed acceptance, verified load instructions and contacts are provided. Do not announce a booking or assignment before execution evidence exists.
6. During the trip, operational staff coordinate progress and exceptions. Appointment changes require confirmation; a draft message is not a changed appointment.
7. Delivery documentation and receipts support invoicing. Payment updates use the applicable agreement and actual records; no general payment deadline is inferred.

## Observed outcomes: do not label every conversation a closed deal

- **Moses: High intent; staff-reported dispatch contact; activation unresolved.** Agreement/value concern remains on page 14. No completed-load or payment proof.
- **Ezequiel: Strong dispatch-engagement evidence; unresolved payment concern.** Options, weight discussion and payment requests. No independent shipment completion or payment record.
- **Current short-trailer prospect: Equipment-fit frustration; engagement continues.** Future purchase is not current equipment; no confirmed dispatch acceptance.
- **Texas-based hotshot prospect: Fuel/coverage requirements unresolved.** Historical fuel statements contradict each other; no verified booking outcome.
- **Trailer-sourcing prospect: Equipment and affordability blocker; deferred.** Last update leaves the prospect sourcing a trailer and initiating the next update.
- **Utah hotshot prospect: Authority/registration and local-fit questions unresolved.** Repeated local-load questions and temporary-tag statement do not prove eligibility.
- **Multiple-box-truck prospect: High intent; latest blocker is insurance affordability.** Counteroffers and document exchanges do not establish final commercial terms or activation.

## Source register and evidence limits

The two PDFs match the previously reviewed uploads. The five pasted exports contain 386 labelled messages before broader cross-upload deduplication. UI duplicates and repeated uploads are not independent evidence. Several export openings appear clipped. Source line numbers refer to the current pasted exports, not PDF pages.

Illustrative replies above are newly written examples, not verbatim historical sales responses. Historical staff reports are attributed reports; they are not independent proof of a call, approval, booking or payment.

The generic 15-page handbook discussed earlier is not reattached in this batch. Its prior review found heavy duplication. Do not bulk-index it as authoritative policy; retain only independently reviewed glossary material.

- **SRC01 — Moses banks.pdf** (primary_chat_screenshots): Identical to earlier reviewed upload. Outcome unresolved; do not infer completed dispatch or payment.
- **SRC02 — Ezequiel.pdf** (primary_chat_screenshots): Identical to earlier reviewed upload. Page 22 visually reads 8,500 lb; cached OCR reads 3,500 incorrectly.
- **SRC03 — Pasted text — current short trailer and future purchase** (primary_chat_export): 66 labelled messages; opening appears clipped. Contact metadata and UI duplicates excluded from guidance.
- **SRC04 — Pasted text — Texas-based hotshot, Louisiana location, fuel request** (primary_chat_export): 41 labelled messages; overlaps an earlier supplied conversation, not an independent outcome.
- **SRC05 — Pasted text — prospect sourcing a trailer** (primary_chat_export): 50 labelled messages. Financing and referral statements are historical, not confirmed service capabilities.
- **SRC06 — Pasted text — Utah hotshot, pending authority and registration** (primary_chat_export): 67 labelled messages. Local-work eligibility claims are user/staff assertions, not legal determinations.
- **SRC07 — Pasted text — multiple box trucks, insurance, commercial objections** (primary_chat_export): 162 labelled messages. Distinct from the trailer-sourcing prospect in SRC05.
- **SRC08 — Pasted prior assistant analysis** (secondary_analysis): Context only. Not independent evidence or current policy. Old code findings excluded from customer knowledge.
- **SRC09 — User-pasted nine-step dispatch article** (general_background): Adapted from text supplied in chat; external page was not independently verified. Not Ayyan policy.
- **SRC10 — User-confirmed service scope in this conversation** (company_rule): Only equipment categories in the handwritten images are served; box trucks must be at least 24 ft. Cargo and Sprinter vans are not served.

## Retrieval and publication instructions

1. Keep this behaviour pack separate from approved commercial policy and private case documents. Keep source authority and review status on every retrieved record.
2. Use the provided JSONL records directly where supported. If ingesting the PDF/Markdown, split at each card heading and keep the whole card together. Do not split an example from its conditions, warnings and source references.
3. Retrieve by current intent, case stage, equipment, concern and missing information. Prefer one or two applicable strategy cards plus the exact approved policy needed for the answer. Do not paste the full pack into every prompt.
4. Use true BM25 plus embeddings if evaluation shows a benefit; fuse rankings and apply metadata filters. Duplicate chat exports must not occupy multiple retrieval slots.
5. The non-negotiable scope, authority hierarchy and tool restrictions belong in the application’s persistent policy/context. Retrieval alone cannot ensure those rules appear on every turn.
6. Staff should review the drafted strategy/general-background records before production publication. User-confirmed equipment scope is a distinct authority category; no historical commercial number becomes approved through ingestion.
7. Version approved policies and withdraw superseded material from retrieval. Preserve an audit trail without continuing to serve withdrawn content.
8. Evaluate on whole conversations held out by customer and time. Do not train and test on duplicated versions of the same customer exchange.
9. Before delivery, validate the current reply against recorded facts, unanswered questions, applicable policy and actual workflow receipts. Do not replace a good model response with a paragraph catalogue.
10. A PDF or RAG pack cannot repair static greeting fallbacks, incorrect state reduction or ungrounded action handling in application code.

## Behavioural acceptance tests

- Cargo/Sprinter van: explain that service is unavailable and stop qualification for that vehicle.
- Box truck → 26 ft → own MC: retain the facts, avoid another introduction and ask only a useful next unanswered question.
- Commercial-and-cargo question: answer it before moving to local/OTR qualification.
- “8,500 is too heavy”: record an unsuitable offered weight, not verified payload.
- “Please payme”: recognize payment support without interpreting “please” as lease-on.
- “I signed already”: check actual agreement status and version; do not invent a signature record.
- “Owner will wait” → “Si”: preserve the insurance blocker and pause; do not mark coverage active.
- Multiple trucks: keep files, coverage, ownership and approval associated with the correct vehicle.
- Ready now but review pending: explain the actual status and continue useful conversation without claiming activation.
- Historical counteroffer or payment promise: do not turn it into current company terms.