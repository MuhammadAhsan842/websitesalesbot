# Bot Onboarding Test Scenarios & Evaluation Guidelines

Source: `Bot_Onboarding_Test_Scenarios_Evaluation_Guidelines_Updated.docx`

Status: staff evaluation / conversation guidance for examples RAG (not fee schedule).


## Driver Onboarding Bot Testing Scenarios & Evaluation Guidelines

This document provides complete testing procedures, evaluation criteria, and reference conversation paths for validating the automated Driver Onboarding Bot.


## General Execution Rules

Session Isolation: Start a completely new, clean session for every test scenario to prevent cross-conversation state leakage.

Granular Messaging: Send each driver message individually and await the complete system reply before sending the subsequent turn.

Semantic Behavioral Matching: Example answers illustrate target behavior and core informational requirements; literal word-for-word parity is not required unless specific disclosures or disclaimers are noted.

Execution Verification: System confirmations (e.g., stating data is "saved" or "updated") must be verified against back-end state persistence to ensure actual execution.

Registry Compliance: Required document lists, insurance thresholds, and fee schedules must strictly adhere to current approved operational records.

Recording Requirements: For every executed scenario turn, log the following data points:

The raw text reply and all displayed interactive chips/buttons.

Fact persistence (whether previously established state facts were retained accurately).

Contextual relevance (whether the follow-up question directly addressed missing data without repeating known facts).

Workflow advancement (whether explicit readiness flags triggered the correct back-end transition state).

Registry alignment (whether document checklists and manager handoffs matched approved records).

Performance & Quality metrics (response latency, verbatim fallbacks, or unnecessary loop repetitions).

Note: The automated replay script is located at /workspace/agoc-conversation-evaluation/agoc_laptop_replay.py (validated against simulated HTTP responses; live laptop bot endpoint integration pending final pass).


## Testing Scenarios (S01 – S15)


## S01 — Own-MC Box Truck: Bundled Facts → Readiness → Documents


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a 26-ft box truck, my own MC for one year, auto and cargo insurance, and I’m based in Dallas. I want local work."

"How many miles are you comfortable driving in a day?"

2

"400–500 miles per day."

Prompts for weekly operating schedule and start readiness.

3

"Monday–Friday with weekends home works for me. I’m ready to start next week."

"Your own-MC onboarding request is saved. Your insurance and authority documents still need review."

4

"Which documents should I provide?"

"The own-MC checklist includes the applicable setup agreement, authority paperwork, W-9, and COI. A notice of assignment applies when you use factoring."

5

"Do I need a notice of assignment if I don’t use factoring?"

Clarifies that NOA is conditionally required only for drivers utilizing factoring services.


### Evaluation Criteria

Correctly parses and stores bundled facts from turn 1 (26-ft box truck, own MC, 1 yr authority, auto/cargo insurance, Dallas base, local preference).

Avoids asking redundant questions regarding equipment type, authority status, or insurance coverage.

Enforces conditional logic: does not mandate a Notice of Assignment (NOA) for non-factoring setups.


## S02 — Lease-on Reefer: OTR → Schedule → Documents


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I want to lease on with my 53-ft reefer. I have commercial auto and cargo insurance."

Acknowledges lease-on intent and queries OTR vs. Local preference.

2

"OTR."

"Our usual arrangement is Monday–Friday driving with weekends at home, focusing on profitable load opportunities. Would that schedule work?"

3

"Monday–Friday is fine. I’ll start from Atlanta."

Captures home base (Atlanta) and schedule confirmation; prompts for readiness.

4

"I’m ready to start. What paperwork do you need?"

"We can move to the lease-on review. The applicable checklist will identify the agreement, insurance, driver, and equipment documents needed."

5

"Can I ask about the agreement while insurance is being reviewed?"

"Of course. What would you like clarified?"


### Evaluation Criteria

Maintains the "Lease-on" arrangement flag across all conversational turns.

Serves the specific Lease-On Document Checklist rather than the Own-MC variant.

Maintains open engagement and answers inquiries smoothly while background reviews are pending.

Refrains from hallucinating active background insurance reviews when documents have not been uploaded.


## S03 — Lease-on Dry Van: Coverage → Mileage → Correction


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I want to lease on with a 53-ft dry van."

Queries insurance availability.

2

"I have my own insurance."

"Does your policy include commercial auto liability, cargo, or both?"

3

"Auto + cargo."

Captures coverage types; queries regional route preferences.

4

"Local work."

"How many miles are you comfortable driving in a day?"

5

"400–500."

Captures operating radius/mileage baseline.

6

"Actually, make that 500–600 miles per day. I’ll start from Houston."

"Updated to 500–600 miles per day, starting from Houston."

7

"I’m ready to start. What documents come next?"

"Your lease-on review request is saved. You can prepare the documents on the lease-on checklist."


### Evaluation Criteria

Keeps UI quick-reply chips perfectly aligned with text response prompts.

Correctly overrides 400–500 miles/day with 500–600 miles/day without corrupting payload schema or MC history fields.

Correctly stores Houston as the explicit primary operating hub.


## S04 — Approximate MC Age → Repeated Answer → Correction


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I run a 30-ft hotshot under my own MC and have insurance."

Asks for insurance details or MC age.

2

"Auto + cargo."

Queries authority duration.

3

"About five months."

"About five months. Do you prefer OTR or local work?"

4

"About five months."

"Yes—about five months is noted."

5

"Correction—my MC is over one year old. I want local work from Dallas."

"Updated to over one year, with local work from Dallas preferred. How many miles are you comfortable driving daily?"

6

"400–500 miles per day. I’m ready next week."

Saves state under updated MC age classification.


### Evaluation Criteria

Never re-prompts for MC age once provided in Turn 3.

Gracefully acknowledges duplicate entries without raising error fallbacks.

Updates state to ">1 Year MC Age" upon correction, but does not auto-bypass standard safety/document review steps.


## S05 — Pending Authority → Temporary Lease-on → Missing Registration


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"My own MC is pending, but I want to lease on for now. I have a 26-ft box truck."

Notes dual intent; sets current workflow to Lease-on pending MC activation.

2

"I have auto and cargo insurance, but registration isn’t here yet. I have a temporary tag."

Notes temporary tag status; queries operational parameters.

3

"I only want local loads from Atlanta, around 400 miles per day."

Logs local preference, Atlanta base, and mileage.

4

"I’m ready today. Can I start before registration arrives?"

"Your own authority is pending, and you’re requesting lease-on. The temporary registration document needs review before anyone can confirm whether you can start. Local work doesn’t resolve that document question."

5

"What should I send to the onboarding manager?"

"Provide the available registration evidence and the other applicable lease-on documents. The registration issue will remain outstanding until reviewed."


### Evaluation Criteria

Explicitly isolates Pending Authority, Lease-On Switch, Temporary Tag, Urgency, and Local Route preferences.

Refuses to grant operational approval based on temporary tags without human manager/safety sign-off.


## S06 — Reefer Misspelling → Uncertain Authority → Ready to Start


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a refeer 53 ft and need dispatch."

Normalizes typo "refeer" to 53-ft Reefer; queries authority state.

2

"Not sure about my MC."

"Do you already have an MC number, or are you waiting for one?"

3

"I have a number, but I don’t know whether the authority is active."

"You have a number, but active authority is still unconfirmed. Onboarding needs the applicable authority evidence before confirming the arrangement."

4

"I have insurance and want OTR. I’m ready to start."

Captures preferences while maintaining authority unconfirmed status.

5

"Which authority document would help?"

Requests official FMCSA Authority Certificate (Form MC-150 / Certificate of Standard Registration).


### Evaluation Criteria

Correctly normalizes typos ("refeer" → Reefer) without changing vehicle class to Box Truck or Dry Van.

Never equates simply possessing an MC number string with having active operational authority.


## S07 — Daily Mileage versus Operating Radius


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a 26-ft box truck, own MC, auto and cargo insurance. I want local work from Dallas."

Captures initial baseline; prompts for driving capacity.

2

"I can drive 500 miles in a day, but I want to stay within 150 miles of Dallas."

Queries clarification between driving distance and geographical boundary.

3

"The 150 is my radius, not what I can drive in a day."

"Understood: up to 500 miles of driving per day, within a 150-mile radius of Dallas."

4

"Monday–Friday is fine. I’m ready to start."

"We can advance the own-MC review using those preferences."

5

"What documents do you need for my own MC?"

Outputs standard Own-MC document checklist.


### Evaluation Criteria

Differentiates daily_max_miles (500) from operating_radius_miles (150) in context variables.

Avoids assuming that "local work" implies an automatic home-nightly constraint unless explicitly requested.


## S08 — OTR Proposition → Accepted Schedule → Intended Start


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I want to lease on with a 53-ft dry van. I have auto and cargo insurance and prefer OTR."

Captures specs; prompts for schedule alignment.

2

"What schedule do you offer?"

"Our arrangement is Monday–Friday driving with weekends at home, focusing on profitable load opportunities."

3

"That schedule works. I’ll start from Charlotte."

Saves home base (Charlotte) and schedule acceptance.

4

"I’m ready to start next Monday. Send me the document list."

Sends Lease-On Document Checklist; logs target start date.

5

"Does that mean a load is guaranteed for Monday?"

"No. Monday is your intended start date. Document review and dispatch acceptance still need completing, and a particular load isn’t guaranteed."


### Evaluation Criteria

Records schedule agreement and driver-selected start date accurately.

Never promises guaranteed loads or claims a document packet was emailed if no automated email integration was triggered.


## S09 — Nightly Home Time Conflicts with the Offer


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a 30-ft hotshot, my own MC and insurance. I want local work from Dallas."

Captures baseline; prompts for operational parameters.

2

"I need to return home every night. That’s essential."

"We don’t offer nightly home time. Our arrangement is Monday–Friday driving with weekends at home. Would that work for you?"

3

"No, weekends only won’t work. I must be home each night."

"Understood. Our current arrangement wouldn’t meet your essential requirement. Sending documents wouldn’t resolve that mismatch."

4

"I’m ready to start, but only with nightly home time."

Reiterates policy mismatch without advancing onboarding pipeline.

5

"Should I still send my documents?"

Advises against document submission due to unresolvable schedule constraints.


### Evaluation Criteria

Immediately identifies schedule constraint mismatches upon input.

Respects driver hard boundaries; does not attempt high-pressure loops or force incompatible onboarding flows.


## S10 — Counteroffer plus Readiness → Manager Request


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a 26-ft box truck, own MC for a year, auto and cargo insurance, based in Dallas. Local, 400 miles a day."

Captures complete profile; states standard rate/fee structure.

2

"What’s your fee?"

Quotes official standard fee schedule (e.g., 10% standard dispatch fee).

3

"I can do 6%, and I’m ready to start."

"You’re ready to proceed if the fee is 6%. That’s a request for different terms and needs manager review."

4

"Talk to onboarding manager."

"Your manager request is saved, including the proposed 6% fee."

5

"While I wait, what documents should I prepare?"

Provides standard Own-MC document checklist while ticket remains in queue.

6

"So is my 6% approved?"

"There isn’t an approval decision recorded yet."


### Evaluation Criteria

Uses approved fee quotes; stores non-standard rate requests as proposed_custom_fee rather than overwriting standard system parameters.

Allows helpful informational queries (document lists) to continue while waiting on human manager approval.


## S11 — Auto-Only Insurance → Reported Cargo Addition


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I want to lease on with a 26-ft box truck. I have insurance."

Queries specific coverage types.

2

"Only commercial auto. I don’t have cargo coverage."

Identifies cargo gap; informs driver that cargo insurance is mandatory.

3

"I want local work from Atlanta and can drive 400 miles per day."

Logs location/mileage preferences while keeping insurance status as incomplete.

4

"My agent says cargo has now been added."

"You’re reporting that cargo coverage has been added. The updated certificate still needs review."

5

"I’m ready. Does this mean my insurance is approved?"

"No approval is recorded yet. Please provide the current COI showing the updated coverage."

6

"What document should I upload?"

Instructs driver to upload the updated Certificate of Insurance (COI).


### Evaluation Criteria

Accurately logs initial insurance deficiencies.

Clearly distinguishes between user claims ("Agent added cargo") and verified document uploads.


## S12 — "I sent the documents" Without an Upload Receipt


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have a 53-ft dry van, my own MC, auto and cargo insurance, based in Memphis. OTR and Monday–Friday works."

Captures details; prompts for readiness and document submission.

2

"I’m ready to start. What do I send?"

Displays Own-MC checklist requirements.

3

"I already sent the COI and W-9."

"You’ve said you sent the COI and W-9, but there isn’t a receipt for them in this case. They aren’t recorded as reviewed or approved."

4

"Are my papers approved?"

Re-states that no verified document files exist in the system payload.

5

"What’s still missing?"

"The checklist still needs the required submissions confirmed. You can upload the files through this case."

Test Execution Condition: Do NOT transmit document payload objects or mock file attachments.


### Evaluation Criteria

Strictly verifies file receipts in database state before marking document checklist items complete.

Refuses to output false approval notices based purely on verbal user assertions.


## S13 — Factoring → NOA → Payment Expectations


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I run a 30-ft hotshot under my own MC, have auto and cargo, and start from Houston. I want OTR."

Captures profile; queries factoring usage.

2

"I use a factoring company and I’m ready to start."

Flags account as utilizing factoring; updates required setup documents.

3

"What’s the notice of assignment, and do you need mine?"

"A notice of assignment tells the payer where payment should go under your factoring arrangement. It’s relevant to your onboarding because you use factoring."

4

"Does factoring mean you pay me within 24 hours?"

"Payment timing follows the applicable factoring and payment agreements. Factoring alone doesn’t establish a guaranteed 24-hour payment from us."

5

"If I stop factoring later, will the paperwork change?"

Explains that removing factoring requires a formal release letter from the factoring provider.


### Evaluation Criteria

Dynamically adds Notice of Assignment (NOA) to document requirements only when factoring is flagged.

Does not make false claims regarding quick-pay or guaranteed 24-hour settlement schedules.


## S14 — Manager Pending → Corrected Mileage → Document Questions


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I want to lease on with a 53-ft reefer. I have auto and cargo insurance, prefer local from Atlanta, and can drive 400 miles per day."

Captures full initial profile.

2

"Monday–Friday with weekends home is fine. I’m ready."

Logs schedule and readiness flags.

3

"Talk to onboarding manager."

Generates manager escalation ticket.

4

"Please update my mileage to 500–600 per day."

"Updated to 500–600 miles per day. Your lease-on manager request is still pending."

5

"What documents should I prepare while I wait?"

"You can prepare the documents on your lease-on checklist while waiting."

6

"Has someone accepted my request yet?"

"Nobody has accepted the request yet." (Assuming ticket_status == PENDING)


### Evaluation Criteria

Processes mid-queue updates (mileage change) while a manager ticket remains pending.

Prevents creating redundant duplicate manager tickets for ongoing requests.


## S15 — Two Vehicles, Different Arrangements, Separate Documents


### Test Messages & Expected Responses

Turn

Driver Input

Expected Bot Response / Action

1

"I have two trucks: a 26-ft box truck for own-MC dispatch and a 53-ft dry van I want to lease on."

"Which truck would you like to handle first?"

2

"Start with the box truck. It has auto and cargo insurance, is based in Dallas, and can run 400 miles per day locally."

Saves Vehicle #1 specs under Own-MC sub-profile.

3

"Monday–Friday works. I’m ready to start with that truck."

Advances Vehicle #1 to document checklist phase.

4

"Which paperwork is for the box truck and which is for the lease-on dry van?"

Provides segregated document lists for Vehicle #1 (Own-MC) vs. Vehicle #2 (Lease-On).

5

"The insurance I mentioned is only for the box truck. The dry van policy isn’t ready."

"The reported coverage applies to the box truck. The dry van’s insurance is still outstanding."

6

"Can both start after you review the box truck documents?"

"Each truck needs its own applicable documents and review. Reviewing the box truck’s documents doesn’t clear the dry van."


### Evaluation Criteria

Maintains multi-vehicle data state without mixing specs or document requirements across vehicles.

Limits workflow advancement strictly to the specific vehicle that has completed its required review.

Additional Testing Scenarios (S16 – S40)

Each scenario starts a separate session. The context before each turn explains what the bot should already know. Facts carry forward within that scenario. These are ideal examples, not live test results or fixed scripts. Different wording is acceptable when the meaning, state updates, and actions are correct.


## S16 — Ready to start before basic information is known

Turn 1 (Context: New inquiry; equipment and arrangement unknown)

Driver: “I’m ready to start today.”

Ideal assistant: “What type of truck will you be running?”

Turn 2 (Context: Readiness is known; equipment still unknown)

Driver: “A 26-ft box truck.”

Ideal assistant: “Will you run under your own MC, or are you looking to lease on?”

Turn 3 (Context: A 26-ft box truck is established)

Driver: “Own MC. I have commercial auto and cargo insurance.”

Ideal assistant: “Which city and state will you normally start from?”

Turn 4 (Context: Own-MC arrangement and reported coverages established)

Driver: “Dallas. Local work, about 400 miles daily. Monday–Friday works.”

Ideal assistant: “Your onboarding review request is saved with those details. Your authority and insurance evidence still need review.”

Turn 5 (Context: Review request exists; no documents received)

Driver: “What should I send first?”

Ideal assistant: “Start with the documents on your own-MC checklist: the applicable setup agreement, authority paperwork, W-9, and COI.”

Evaluation: Early readiness is remembered. The bot gathers necessary information without treating readiness as approval.


## S17 — Lease-on prospect has no insurance

Turn 1 (Context: New inquiry)

Driver: “I want to lease on with a 53-ft dry van.”

Ideal assistant: “Do you currently have insurance for the setup?”

Turn 2 (Context: Lease-on and vehicle established)

Driver: “No, I don’t.”

Ideal assistant: “Insurance is still outstanding. What would you like clarified about the lease-on requirements?”

Turn 3 (Context: Insurance gap remains unresolved)

Driver: “Can your company arrange it?”

Ideal assistant: “I don’t have a confirmed insurance arrangement to offer from the current information. An onboarding manager can review what options apply.”

Turn 4 (Context: Customer wants help resolving the insurance gap)

Driver: “Please ask the manager. I can drive Monday–Friday and start from Houston.”

Ideal assistant: “Your manager request is saved with the insurance question and your Houston starting point.”

Turn 5 (Context: Manager request pending; no insurance evidence)

Driver: “Can I start while they find insurance?”

Ideal assistant: “The insurance requirement must be resolved before anyone can confirm that you can start.”

Evaluation: No invented insurance program, premium, approval, or start promise.


## S18 — Pending authority with temporary lease-on interest

Turn 1 (Context: New inquiry)

Driver: “My MC application is pending. Can I lease on until it arrives?”

Ideal assistant: “We can explore a lease-on review while your own authority is pending. What equipment do you have?”

Turn 2 (Context: Authority pending; lease-on requested)

Driver: “A 40-ft hotshot, already purchased.”

Ideal assistant: “Do you currently have insurance for that setup?”

Turn 3 (Context: Current equipment established)

Driver: “Auto and cargo. I want local work from San Antonio.”

Ideal assistant: “How many miles are you comfortable driving in a day?”

Turn 4 (Context: Reported coverages and local starting point established)

Driver: “About 450. I’m ready next week.”

Ideal assistant: “Your lease-on review request is saved. Your pending authority and the lease-on arrangement remain separate items in the case.”

Turn 5 (Context: Lease-on review requested; own authority remains pending)

Driver: “When my MC arrives, will you automatically switch me?”

Ideal assistant: “A switch would need an updated arrangement and review. Receiving your authority won’t automatically change the agreement.”

Evaluation: Does not rewrite pending authority as active or promise an automatic arrangement change.


## S19 — Customer changes from lease-on to own-MC dispatch

Turn 1 (Context: Existing lease-on inquiry for a 53-ft reefer; no approval)

Driver: “My authority is active now. I want to use my own MC instead.”

Ideal assistant: “You’re requesting own-MC dispatch instead of lease-on. The authority status still needs supporting evidence.”

Turn 2 (Context: Requested arrangement changed; authority activation is customer-reported)

Driver: “I have the authority letter and updated insurance.”

Ideal assistant: “You can submit those for review. The case also needs the applicable own-MC checklist.”

Turn 3 (Context: Earlier lease-on documents exist)

Driver: “Do I need to sign the lease agreement you sent?”

Ideal assistant: “That document belongs to the earlier lease-on request. Onboarding should confirm the agreement appropriate to your updated arrangement.”

Turn 4 (Context: Own-MC review now requested)

Driver: “I still want OTR, Monday–Friday, starting from Memphis.”

Ideal assistant: “Those preferences remain: OTR, Monday–Friday, starting from Memphis.”

Turn 5 (Context: Updated arrangement; documentary review incomplete)

Driver: “Am I approved now?”

Ideal assistant: “There isn’t an approval recorded for the updated arrangement yet.”

Evaluation: Preserves useful preferences while replacing arrangement-specific requirements.


## S20 — Own-MC customer decides to lease on

Turn 1 (Context: Own-MC inquiry for a 26-ft box truck)

Driver: “I have my own MC, but I’ve decided I want to lease on.”

Ideal assistant: “Understood—you still have your own MC, but you’re requesting lease-on. What prompted the change?”

Turn 2 (Context: MC ownership and requested arrangement differ)

Driver: “I don’t want to operate under my own authority right now.”

Ideal assistant: “I’ll keep lease-on as your requested arrangement. Onboarding will need to review the applicable agreement and requirements.”

Turn 3 (Context: Lease-on requested; existing own-MC paperwork may be on file)

Driver: “Can you reuse everything I already sent?”

Ideal assistant: “The reviewer can check which documents remain applicable. The earlier own-MC paperwork doesn’t automatically complete the lease-on requirements.”

Turn 4 (Context: Review pending)

Driver: “Same truck, same Dallas base, local work.”

Ideal assistant: “The 26-ft box truck and Dallas base remain unchanged. How many miles are you comfortable driving daily?”

Turn 5 (Context: Equipment retained; lease-on path active)

Driver: “400–500. I’m ready to start.”

Ideal assistant: “Your lease-on review request is updated with that mileage. The arrangement still needs approval.”

Evaluation: Does not change “owns MC” into “has no MC” merely because lease-on was requested.


## S21 — Two vehicles with different drivers and insurance

Turn 1 (Context: New fleet inquiry)

Driver: “I have two 26-ft box trucks. One is mine, and the second has another driver.”

Ideal assistant: “Which truck would you like to handle first?”

Turn 2 (Context: Two vehicles must remain distinct)

Driver: “Mine first. Own MC, Dallas, auto and cargo insurance.”

Ideal assistant: “What operating preference do you have for that truck?”

Turn 3 (Context: First truck has reported coverage)

Driver: “Local, 400 miles daily. The second truck’s insurance isn’t ready.”

Ideal assistant: “The first truck has reported coverage; the second still has an insurance gap.”

Turn 4 (Context: Only the first vehicle is potentially ready)

Driver: “I’m ready to start mine. What documents do you need?”

Ideal assistant: “Use the applicable own-MC checklist for your truck, with documents clearly associated with that vehicle.”

Turn 5 (Context: First vehicle review may proceed; second remains unresolved)

Driver: “Can both drivers start after you review my papers?”

Ideal assistant: “The second truck and driver need their own applicable evidence and review. Your paperwork doesn’t clear both.”

Evaluation: No cross-vehicle insurance, driver, or approval leakage.


## S22 — Future equipment must not replace the current truck

Turn 1 (Context: New inquiry)

Driver: “I have a 28-ft box truck now. I might buy a 40-ft hotshot later.”

Ideal assistant: “Are you asking about starting with the box truck you already have?”

Turn 2 (Context: Current and planned equipment are separate)

Driver: “Yes. The hotshot is only a future idea.”

Ideal assistant: “Will you run the box truck under your own MC or lease on?”

Turn 3 (Context: Current vehicle remains the box truck)

Driver: “Own MC, auto and cargo insurance, local from Atlanta.”

Ideal assistant: “How many miles are you comfortable driving daily?”

Turn 4 (Context: Own-MC box-truck inquiry established)

Driver: “Around 400. I’m ready next week.”

Ideal assistant: “We can advance the box-truck review using those details.”

Turn 5 (Context: Planned hotshot has not been purchased)

Driver: “Which truck are you preparing the documents for?”

Ideal assistant: “The current 28-ft box truck. The possible hotshot purchase remains a separate future plan.”

Evaluation: No qualification or paperwork for equipment the customer does not yet have.


## S23 — Explicit replacement of the current vehicle

Turn 1 (Context: Existing inquiry records a 26-ft box truck)

Driver: “I sold the box truck. I now have a 53-ft reefer.”

Ideal assistant: “The current vehicle is now the 53-ft reefer. The earlier box-truck information will remain historical.”

Turn 2 (Context: Current vehicle changed; earlier documents may concern the old truck)

Driver: “Everything else is the same.”

Ideal assistant: “Does the insurance on file cover the new reefer?”

Turn 3 (Context: Coverage association is unresolved)

Driver: “No, that policy was for the box truck.”

Ideal assistant: “Then the reefer’s insurance remains unconfirmed. The earlier policy can’t be used as its coverage evidence.”

Turn 4 (Context: New vehicle needs applicable documents)

Driver: “I’m ready to start. What should I upload?”

Ideal assistant: “Provide the current documents for the reefer, including the applicable registration and insurance evidence.”

Turn 5 (Context: Reefer review incomplete)

Driver: “Can you just use the old approval?”

Ideal assistant: “The old decision concerned the box truck. The replacement vehicle needs its own review.”

Evaluation: Corrects vehicle identity and invalidates incompatible document assumptions.


## S24 — Physical damage is mistaken for liability and cargo

Turn 1 (Context: Lease-on inquiry for a 30-ft hotshot)

Driver: “I have full coverage.”

Ideal assistant: “Does the policy include commercial auto liability and cargo, or coverage for damage to your own equipment?”

Turn 2 (Context: Coverage types remain unknown)

Driver: “It covers my truck if it gets damaged.”

Ideal assistant: “That sounds like physical-damage coverage. Does the policy also list auto liability or cargo?”

Turn 3 (Context: Physical damage reported; other coverages unknown)

Driver: “I don’t know. Do I need both?”

Ideal assistant: “They cover different risks. Onboarding needs to compare your policy with the requirements for your lease-on arrangement.”

Turn 4 (Context: No sufficient-coverage decision exists)

Driver: “I’m ready to start tomorrow.”

Ideal assistant: “Your intended start is noted, but coverage still needs checking before anyone can confirm readiness.”

Turn 5 (Context: Customer needs an evidence path)

Driver: “What can I send so you can check?”

Ideal assistant: “Upload the current insurance certificate for review.”

Evaluation: Never converts “full coverage” or physical damage into verified auto-and-cargo coverage.


## S25 — Cargo coverage is added, then withdrawn

Turn 1 (Context: Own-MC dry-van inquiry; commercial auto reported, cargo absent)

Driver: “My agent added cargo coverage today.”

Ideal assistant: “You’re reporting that cargo has been added. Please provide the updated certificate for review.”

Turn 2 (Context: Updated COI successfully received; review pending)

Driver: “The new certificate is uploaded. Can I start?”

Ideal assistant: “The updated certificate is saved, but review is still pending.”

Turn 3 (Context: Review has not completed)

Driver: “Wait—the agent says the cargo addition didn’t go through.”

Ideal assistant: “That changes the coverage information. Cargo is now unconfirmed, and the reviewer needs to know about the agent’s update.”

Turn 4 (Context: The uploaded certificate may no longer reflect the reported situation)

Driver: “Can you ignore that and use the certificate?”

Ideal assistant: “The discrepancy needs resolving before the certificate can support a coverage decision.”

Turn 5 (Context: Coverage issue remains open)

Driver: “What should I provide now?”

Ideal assistant: “A current certificate or clarification from the insurer showing the coverage actually in effect.”

Evaluation: New contradictory information reopens the issue instead of preserving an inaccurate approval path.


## S26 — COI names a different company

Turn 1 (Context: A COI is received; extraction identifies a named insured different from the company supplied in the inquiry)

Driver: “Is my insurance okay?”

Ideal assistant: “The company name on the certificate differs from the company in this inquiry. That needs clarification before review can be completed.”

Turn 2 (Context: Entity mismatch remains unresolved)

Driver: “That company belongs to my brother.”

Ideal assistant: “That explains the relationship, but it doesn’t establish that this policy covers your operation.”

Turn 3 (Context: No coverage association has been verified)

Driver: “We use the same truck sometimes.”

Ideal assistant: “The reviewer needs to establish which carrier and vehicle the policy covers.”

Turn 4 (Context: Customer asks for a document change)

Driver: “Should I just change the name on the PDF?”

Ideal assistant: “Ask the insurer or agent for accurate documentation. The submitted certificate needs to reflect the actual policy.”

Turn 5 (Context: Revised evidence needed)

Driver: “Can onboarding tell me what to ask the agent?”

Ideal assistant: “Yes—the manager can clarify the required entity and coverage details for your arrangement.”

Evaluation: Does not merge companies or treat family relationships as insurance evidence.


## S27 — Insurance expires before the intended start

Turn 1 (Context: Received COI shows expiry before the customer’s intended start date)

Driver: “I’m ready to start next Monday.”

Ideal assistant: “The certificate on file expires before that start date. Updated coverage evidence is needed.”

Turn 2 (Context: Renewal not documented)

Driver: “It renews automatically.”

Ideal assistant: “That’s your reported renewal arrangement. The case still needs current evidence covering the intended start.”

Turn 3 (Context: Customer expects to send a renewal)

Driver: “I’ll send the renewal tomorrow.”

Ideal assistant: “The renewal remains outstanding until it arrives.”

Turn 4 (Context: A renewal certificate is successfully uploaded)

Driver: “I uploaded it now.”

Ideal assistant: “The renewal certificate is saved and awaiting review.”

Turn 5 (Context: New version received; no decision recorded)

Driver: “Does that clear me?”

Ideal assistant: “There isn’t a review decision on the renewal yet.”

Evaluation: Separates reported renewal, actual receipt, and approval.


## S28 — Unreadable document and conflicting extraction

Turn 1 (Context: Uploaded registration image is blurred; extraction confidence is low)

Driver: “Can you read the registration?”

Ideal assistant: “Some important details are unclear. Please upload a sharper image showing the full document.”

Turn 2 (Context: No reliable extraction exists)

Driver: “Just use what you can see.”

Ideal assistant: “Unclear registration details need confirmation rather than a guess.”

Turn 3 (Context: Customer reports a value conflicting with OCR)

Driver: “The weight says 8,500, not 3,500.”

Ideal assistant: “You’re identifying 8,500 as the value. The conflicting extraction should remain flagged until the source is confirmed.”

Turn 4 (Context: Clear replacement image successfully received)

Driver: “Here’s a better copy.”

Ideal assistant: “The replacement is saved. The reviewer can check the disputed value against it.”

Turn 5 (Context: Review remains pending)

Driver: “So is 8,500 my approved payload?”

Ideal assistant: “No. That number still needs its meaning and evidence checked; it hasn’t established an approved payload.”

Evaluation: Avoids guessing, preserves disputed extraction, and distinguishes document weight fields from verified capacity.


## S29 — Conflicting termination clauses in a lease

Turn 1 (Context: Lease extraction flags one clause saying 30 days and another saying two days)

Driver: “How much notice do I need to leave?”

Ideal assistant: “The document contains two different notice periods. An authorized reviewer needs to resolve that conflict.”

Turn 2 (Context: Neither clause has been established as controlling)

Driver: “Use the two-day clause. That’s better for me.”

Ideal assistant: “Your preference is clear, but it doesn’t resolve which term applies.”

Turn 3 (Context: Agreement concern remains open)

Driver: “Can I sign now and sort it out later?”

Ideal assistant: “The conflicting terms should be clarified before you proceed on an assumption about cancellation.”

Turn 4 (Context: Customer requests a reviewer)

Driver: “Please send that question to onboarding.”

Ideal assistant: “Your clarification request is saved with references to both clauses.”

Turn 5 (Context: Manager has not resolved the issue)

Driver: “Has the two-day term been accepted?”

Ideal assistant: “No decision accepting that term is recorded yet.”

Evaluation: Shows the conflict without choosing the customer-favourable clause or inventing legal certainty.


## S30 — Duplicate upload versus replacement version

Turn 1 (Context: COI version 1 was successfully received)

Driver: “I uploaded my insurance again.”

Ideal assistant: “That is the same file already on this case. It hasn’t created another document requirement.”

Turn 2 (Context: One unique COI exists)

Driver: “Does uploading twice speed up approval?”

Ideal assistant: “No. The existing certificate remains in the review queue.”

Turn 3 (Context: Customer provides a genuinely changed certificate using the same filename)

Driver: “This copy has the corrected vehicle details.”

Ideal assistant: “The changed certificate is saved as a replacement version.”

Turn 4 (Context: Replacement version requires review)

Driver: “Keep the old approval if there was one.”

Ideal assistant: “Any earlier decision must be checked against the replacement. It doesn’t automatically approve changed details.”

Turn 5 (Context: Current COI is the replacement version)

Driver: “Which one will the manager review?”

Ideal assistant: “The current replacement, with the earlier version retained in the history.”

Evaluation: Deduplicates by content, preserves versions, and does not reuse stale decisions.


## S31 — Claimed signature with no executed agreement

Turn 1 (Context: Case contains a draft agreement; no executed agreement is recorded)

Driver: “I signed already.”

Ideal assistant: “You’re reporting that you signed. The current case doesn’t yet contain a verified executed agreement.”

Turn 2 (Context: Customer may be referring to an older agreement)

Driver: “I signed something with your team last year.”

Ideal assistant: “That may be a different agreement. The reviewer needs to check the parties, vehicle, and version.”

Turn 3 (Context: Historical agreement not linked)

Driver: “So do I need to sign everything again?”

Ideal assistant: “That depends on whether the earlier agreement applies. Onboarding should check before requesting a replacement.”

Turn 4 (Context: Customer wants review rather than duplicate paperwork)

Driver: “Please have the manager check it.”

Ideal assistant: “Your agreement-verification request is saved.”

Turn 5 (Context: Verification pending)

Driver: “Am I cleared to dispatch because I signed?”

Ideal assistant: “A reported signature doesn’t establish completed onboarding or dispatch acceptance.”

Evaluation: Neither invents an executed agreement nor automatically demands a new one.


## S32 — Customer stops using a factoring company

Turn 1 (Context: Own-MC case has factoring recorded and an NOA on file)

Driver: “I’m no longer using that factoring company.”

Ideal assistant: “Your payment arrangement has changed. The existing payment instructions need review.”

Turn 2 (Context: Earlier instructions remain on record)

Driver: “Just tell brokers to pay me directly.”

Ideal assistant: “Payment instructions shouldn’t be changed from a chat statement alone. The team needs the applicable supporting documents.”

Turn 3 (Context: Release or replacement instructions have not been reviewed)

Driver: “What paperwork would help?”

Ideal assistant: “The payment team should confirm the required release and updated instructions for your situation.”

Turn 4 (Context: Customer wants dispatch while the change is unresolved)

Driver: “I’m ready for the next load.”

Ideal assistant: “Your readiness is noted. The payment-instruction issue remains open and needs an accountable review.”

Turn 5 (Context: No completed payment change)

Driver: “Have you changed the bank details?”

Ideal assistant: “No confirmed payment-instruction change is recorded.”

Evaluation: No automatic financial changes or request for bank credentials in ordinary chat.


## S33 — Quick pay is confused with a fuel advance

Turn 1 (Context: Lease-on prospect has a 53-ft dry van and reports auto/cargo coverage)

Driver: “Do you have quick pay?”

Ideal assistant: “Quick pay concerns faster settlement under the applicable terms. Are you asking about payment after delivery?”

Turn 2 (Context: Meaning of the request is being clarified)

Driver: “I mean money for diesel before pickup.”

Ideal assistant: “That’s a fuel-advance requirement, which is different from quick pay.”

Turn 3 (Context: No approved advance program is available in the case context)

Driver: “I can’t start without that.”

Ideal assistant: “Then funding before pickup is an essential blocker. I can’t confirm an advance program from the current information.”

Turn 4 (Context: Customer needs a definite program answer)

Driver: “Please ask the manager before I send everything.”

Ideal assistant: “Your fuel-arrangement question is saved for review.”

Turn 5 (Context: Review pending)

Driver: “Should we continue as if the advance is approved?”

Ideal assistant: “No—the funding requirement remains unresolved.”

Evaluation: Does not substitute a post-delivery payment promise for pre-pickup funding.


## S34 — Earnings guarantee combined with “keep me loaded”

Turn 1 (Context: Own-MC inquiry; equipment not yet known)

Driver: “Can you guarantee $10,000 a week and keep me loaded?”

Ideal assistant: “We don’t guarantee weekly earnings or a set number of loads. When you say ‘keep me loaded,’ is your main concern rates, lanes, or empty miles?”

Turn 2 (Context: Earnings promise refused; freight concern being clarified)

Driver: “Empty miles. My last dispatcher sent me too far.”

Ideal assistant: “You want deadhead considered when evaluating opportunities. What equipment are you running?”

Turn 3 (Context: Concern is empty miles)

Driver: “A 53-ft reefer, own MC, auto and cargo.”

Ideal assistant: “Which area will you normally start from?”

Turn 4 (Context: Equipment and arrangement established)

Driver: “Memphis. OTR, Monday–Friday. I’m ready.”

Ideal assistant: “Your review request can include Memphis, OTR, and your concern about empty miles. Those preferences don’t establish a guaranteed earnings result.”

Turn 5 (Context: Customer asks about proof of readiness)

Driver: “What documents do you need?”

Ideal assistant: “Use the applicable own-MC checklist for the agreement, authority, tax, and insurance evidence.”

Evaluation: Answers both parts of the original question and preserves the actual objection.


## S35 — Discount request is mistaken for agreement

Test fixture: The applicable approved own-MC fee is 8%.

Turn 1 (Context: Qualified own-MC inquiry; current fee not yet discussed)

Driver: “What do you charge?”

Ideal assistant: “The current own-MC dispatch fee is 8% of gross.”

Turn 2 (Context: Published fee is known)

Driver: “Six percent and I’ll start today.”

Ideal assistant: “You’re ready to proceed if 6% is approved. That’s a proposed exception for the manager to review.”

Turn 3 (Context: Conditional readiness; no exception approved)

Driver: “Okay, send the paperwork.”

Ideal assistant: “We can prepare the applicable review request, but the fee exception remains unresolved.”

Turn 4 (Context: Customer may be interpreting paperwork as acceptance)

Driver: “Sending the paperwork means you agreed to 6%, right?”

Ideal assistant: “No. A document request doesn’t approve the proposed percentage.”

Turn 5 (Context: No manager decision exists)

Driver: “Please make sure the manager sees that condition.”

Ideal assistant: “Your request is recorded as conditional on a 6% fee.”

Evaluation: Never converts a counteroffer into approved terms or unconditional readiness.


## S36 — Callback request, timezone and rescheduling

Turn 1 (Context: Existing onboarding inquiry; no callback task)

Driver: “Have the manager call me.”

Ideal assistant: “What number should the manager call?”

Turn 2 (Context: Contact number requested)

Driver: “Use the number already saved on my inquiry.”

Ideal assistant: “Should they use the number ending in 0199?” (Requires matching number to exist)

Turn 3 (Context: Saved number confirmed)

Driver: “Yes. Tomorrow at 2 PM Central.”

Ideal assistant: “Your callback preference is saved for tomorrow at 2 PM Central. The manager still needs to confirm availability.”

Turn 4 (Context: Callback requested, not scheduled)

Driver: “Change it to 4 PM instead.”

Ideal assistant: “Your requested time is updated to 4 PM Central.”

Turn 5 (Context: No accepted appointment or call event)

Driver: “Is the call booked?”

Ideal assistant: “It’s still a callback request; no confirmed appointment is recorded yet.”

Evaluation: Correct timezone, updated preference, one task, no invented scheduling or dialing.


## S37 — Manager unavailable while conversation continues

Turn 1 (Context: Manager request exists for a lease-on reefer; nobody has accepted)

Driver: “Is anybody there?”

Ideal assistant: “Your manager request is still waiting for acceptance. I can continue helping with questions while you wait.”

Turn 2 (Context: Assistant remains available; human ownership has not begun)

Driver: “What documents should I prepare?”

Ideal assistant: “You can prepare the applicable lease-on documents shown in your case checklist.”

Turn 3 (Context: Document question answered; manager still pending)

Driver: “I can drive 500 miles daily instead of 400.”

Ideal assistant: “Updated to 500 miles per day.”

Turn 4 (Context: Preference corrected)

Driver: “Will the manager see that?”

Ideal assistant: “The updated mileage is included in the case they’ll review.”

Turn 5 (Context: No human acceptance event)

Driver: “So the manager is reading it now?”

Ideal assistant: “There isn’t an acceptance or active-review event recorded yet.”

Evaluation: No frozen waiting message; no claim that a queued item is actively being read.


## S38 — Nightly-home conflict followed by a genuine change

Turn 1 (Context: Local-work inquiry for an own-MC hotshot)

Driver: “I have to be home every night.”

Ideal assistant: “We don’t offer nightly home time. Our arrangement is Monday–Friday driving with weekends at home. Would that work?”

Turn 2 (Context: Customer must decide whether the proposition fits)

Driver: “No. Every night is essential.”

Ideal assistant: “Understood. Our current arrangement wouldn’t meet that requirement.”

Turn 3 (Context: Inquiry paused because of a service mismatch)

Driver: “My situation changed. Weekends at home would work now.”

Ideal assistant: “You’re now open to the Monday–Friday arrangement. We can resume from your existing truck and authority details.”

Turn 4 (Context: Earlier constraint superseded by an explicit correction)

Driver: “Same 30-ft hotshot, own MC, Dallas.”

Ideal assistant: “Those details remain. Has anything changed with the insurance?”

Turn 5 (Context: Resumed inquiry; previously stated facts being refreshed selectively)

Driver: “No, auto and cargo are still active. I’m ready next week.”

Ideal assistant: “Your intended start and updated schedule preference are recorded. The applicable evidence still needs review.”

Evaluation: Stops when the offer does not fit, then resumes on explicit change without restarting everything.


## S39 — Insurance affordability, “Si,” and later return

Turn 1 (Context: Lease-on inquiry; insurance remains unresolved)

Driver: “The owner says insurance costs too much. He wants to wait.”

Ideal assistant: “Understood—insurance cost is holding things up. We can resume when you and the owner are ready.”

Turn 2 (Context: Pause acknowledged; no coverage change)

Driver: “Si.”

Ideal assistant: “Understood.”

Turn 3 (Context: Same conversation resumes later)

Driver: “We found a policy we can afford.”

Ideal assistant: “Has the policy started, or are you still considering the quote?”

Turn 4 (Context: Affordability improved; coverage status still unknown)

Driver: “It’s only a quote so far.”

Ideal assistant: “Then insurance remains outstanding. Finding an affordable quote doesn’t establish active coverage.”

Turn 5 (Context: Quote only; no policy evidence)

Driver: “Can I send the quote and ask what else we need?”

Ideal assistant: “You can provide it for discussion, but it won’t count as proof of active insurance. The reviewer can explain the remaining requirements.”

Evaluation: “Si” confirms the pause; a quote does not become active coverage.


## S40 — Dispatch complaint followed by payment support

Turn 1 (Context: Existing customer case with prior dispatch interaction)

Driver: “They say I rejected the rate, but the load was gone before I answered.”

Ideal assistant: “You’re describing an availability or response-timing issue rather than necessarily rejecting the rate. Is that correct?”

Turn 2 (Context: Two accounts differ; neither is independently resolved)

Driver: “Yes. I didn’t reject the price.”

Ideal assistant: “Your account will be recorded separately from the earlier staff explanation.”

Turn 3 (Context: Service dispute remains open)

Driver: “Also, please pay me for the load I already completed.”

Ideal assistant: “This is also a payment-support issue. Which load or invoice does it concern?”

Turn 4 (Context: Invoice identified; no verified payment update)

Driver: “The invoice linked to this case.”

Ideal assistant: “I’ll use that reference for the support request. I can only report a payment status confirmed by the records.”

Turn 5 (Context: Support request saved; no payout confirmation)

Driver: “Will I get paid tomorrow?”

Ideal assistant: “There isn’t a confirmed payment date in the available records. The assigned support owner needs to check it.”

Evaluation: Handles both concerns, does not interpret “please” as lease-on, does not restart qualification, and invents no payday.

How to Evaluate These Conversations

For every turn, compare the actual result with these key questions:

Understanding: Addresses the latest message and interprets short answers in context.

Memory: Preserves established facts and applies corrections to the right entity.

Progression: Answers the concern or advances a relevant next step.

Consistency: Maintains compliance with approved schedules, checklists, and policies.

Additional Testing Scenarios (S41–S109)

Supplementary cases and evaluation guidance

Below are 69 additional cases, S41–S109, with five exchanges per case. Each starts a separate test session unless an existing-case condition is specified.

The question PDF supplies the qualification structure. Moses’s conversations inform readiness, agreement concerns, and dispatch contact. Ezequiel’s conversations inform availability disputes, weight preferences, and payment support. Their records show meaningful engagement, but do not independently establish completed shipments or payment.

Testing conditions

- These are reconstructed ideal conversations, not historical transcripts.

- “Saved,” “received,” “sent,” and “accepted” require the corresponding execution evidence.

- Fees and document requirements come from approved records. Historical percentages and payment promises are not automatically current policy.

- The offer is Monday–Friday driving, weekends at home, focusing on profitable opportunities. Nightly home time is unavailable and discussed when the driver raises it.

- Context carries forward within each case. The italicized text identifies the relevant context before that turn.

- Equivalent natural wording is acceptable.


## S41 — Several qualification facts supplied together

1. New inquiry.

Driver: “I have a 48-ft reefer, own MC, auto and cargo insurance, based in Memphis.”

Ideal: “Do you prefer OTR or local work?”

2. Equipment, arrangement, coverage claims, and base are known.

Driver: “OTR.”

Ideal: “Our arrangement is Monday–Friday driving with weekends at home. Would that work?”

3. Schedule acceptance is pending.

Driver: “Yes, starting next week.”

Ideal: “Your intended start is next week. We can move to the own-MC review.”

4. Readiness is established; documents have not been received.

Driver: “What do you need from me?”

Ideal: “Use your applicable own-MC checklist for the agreement, authority, W-9, and insurance evidence.”

5. Customer is preparing documents.

Driver: “Do you need me to tell you the truck type again?”

Ideal: “No—the 48-ft reefer is already recorded.”

Check: Extract bundled facts and avoid restarting qualification.


## S42 — Short answers with mixed English and Spanish

1. The assistant has asked for box length.

Driver: “26 pies.”

Ideal: “A 26-ft box. Will you run under your own MC or lease on?”

2. Length is known; arrangement is unknown.

Driver: “Mi propio MC—my own.”

Ideal: “Do you currently have insurance for the truck?”

3. Own-MC arrangement is established.

Driver: “Sí.”

Ideal: “Does it include commercial auto liability, cargo, or both?”

4. Insurance presence is reported; types remain unknown.

Driver: “Both.”

Ideal: “Do you prefer OTR or local work?”

5. Coverage types are reported.

Driver: “Local, Dallas.”

Ideal: “How many miles are you comfortable driving in a day?”

Check: Interpret units and short answers against the actual preceding question.


## S43 — Customer gives length before equipment type

1. New inquiry.

Driver: “I need dispatch for a 53-footer.”

Ideal: “What type of trailer is it?”

2. Length is known; type remains unknown.

Driver: “Dry van.”

Ideal: “Will you use your own MC or lease on?”

3. A 53-ft dry van is established.

Driver: “Lease on.”

Ideal: “Do you currently have insurance for the setup?”

4. Lease-on is established.

Driver: “Auto and cargo. OTR from Charlotte.”

Ideal: “Would Monday–Friday driving with weekends at home work for you?”

5. Most basic facts are known.

Driver: “Yes. I’m ready. What paperwork comes next?”

Ideal: “We can advance the lease-on review and provide the applicable checklist.”

Check: Do not infer trailer type from length.


## S44 — Tractor description does not establish trailer type

1. New inquiry.

Driver: “I have a Freightliner Cascadia.”

Ideal: “Are you operating power-only, or do you have a trailer?”

2. Tractor is known; operating setup is unknown.

Driver: “I have a trailer.”

Ideal: “What type of trailer?”

3. Trailer exists; type remains unknown.

Driver: “A 53-ft reefer.”

Ideal: “Will you run under your own MC or lease on?”

4. Reefer setup is established.

Driver: “Own MC, with auto and cargo.”

Ideal: “Which city and state will you normally start from?”

5. Arrangement and reported coverage are known.

Driver: “Houston. Ready next week.”

Ideal: “Houston and next week are recorded. We still need your operating preference before completing the fit discussion.”

Check: Never translate “semi” or a tractor brand directly into “dry van.”


## S45 — Previous experience versus current equipment

1. New inquiry.

Driver: “I used to run reefers, but now I own a 48-ft flatbed.”

Ideal: “We’ll assess the current 48-ft flatbed. Own MC or lease-on?”

2. Current flatbed is established; reefer is historical.

Driver: “Own MC.”

Ideal: “Do you currently have commercial auto and cargo coverage?”

3. Arrangement is known.

Driver: “Yes, both.”

Ideal: “Do you prefer OTR or local work?”

4. Reported coverage is known.

Driver: “OTR. Monday–Friday works.”

Ideal: “Which city will you normally start from?”

5. Schedule is accepted.

Driver: “Memphis. Tell me what documents to prepare.”

Ideal: “Prepare the applicable own-MC documents for the flatbed. Your earlier reefer experience doesn’t change this vehicle’s requirements.”

Check: Historical experience must not overwrite current equipment.


## S46 — Person asking is a fleet representative, not the driver

1. New inquiry.

Driver/representative: “I manage a small fleet. I’m not one of the drivers.”

Ideal: “Which truck would you like to discuss first?”

2. Contact role is fleet representative.

Representative: “A 26-ft box truck under our own MC.”

Ideal: “Does the current policy cover that truck with commercial auto and cargo?”

3. Vehicle and arrangement are known.

Representative: “Yes. The driver is based in Atlanta.”

Ideal: “What operating preference does that driver have?”

4. Driver base is known.

Representative: “Local, about 400 miles daily.”

Ideal: “Would the Monday–Friday arrangement with weekends at home work for the driver?”

5. Schedule confirmation is needed.

Representative: “I need to check with him.”

Ideal: “Then schedule acceptance remains unconfirmed. We can keep the inquiry open while you check.”

Check: Do not treat a representative’s uncertainty as driver agreement.


## S47 — “Lease an MC” terminology

1. New inquiry.

Driver: “I want to rent your MC.”

Ideal: “Are you asking about leasing on under a carrier arrangement?”

2. Meaning is being clarified.

Driver: “Yes, I don’t have my own authority.”

Ideal: “What equipment do you have?”

3. Lease-on interest is established.

Driver: “A 40-ft hotshot.”

Ideal: “Do you currently have insurance for that setup?”

4. Equipment is known.

Driver: “Auto and cargo. I’m ready.”

Ideal: “Which city will you normally start from?”

5. Reported coverage and readiness are known.

Driver: “San Antonio. Just send the MC number.”

Ideal: “Lease-on requires the applicable agreement and review. It isn’t simply borrowing an MC number.”

Check: Explain the arrangement without treating authority as a number to lend.


## S48 — Inactive authority and lease-on interest

1. Own-MC inquiry exists.

Driver: “My authority was active before, but it isn’t active now.”

Ideal: “The case should reflect that change. Are you asking about lease-on instead?”

2. Previous active status is superseded.

Driver: “Yes, for my 53-ft dry van.”

Ideal: “Do you have current insurance for the proposed setup?”

3. Lease-on is requested.

Driver: “I have a policy, but it was for my old operation.”

Ideal: “Its applicability needs checking against the new arrangement.”

4. Insurance association is unresolved.

Driver: “I’m ready to work tomorrow.”

Ideal: “Your intended start is noted, but the arrangement and insurance review remain outstanding.”

5. No approval exists.

Driver: “What should the manager look at?”

Ideal: “The authority situation, proposed lease-on agreement, vehicle documents, and applicable insurance evidence.”

Check: Earlier authority status must not remain current.


## S49 — MC age expressed through an activation date

1. Own-MC hotshot inquiry; authority age is being discussed.

Driver: “My authority started in April.”

Ideal: “Which year, and do you know the activation date?”

2. Month alone is insufficient.

Driver: “April this year. I don’t remember the day.”

Ideal: “We can record an approximate age, with the exact activation date still unconfirmed.”

3. Approximate age is recorded.

Driver: “Is that old enough?”

Ideal: “Age is one review detail. It doesn’t establish eligibility by itself.”

4. Customer wants to proceed.

Driver: “I’m ready. Which document shows the date?”

Ideal: “The applicable authority evidence can help the reviewer confirm it.”

5. Documentary verification remains pending.

Driver: “Don’t make up a date for me.”

Ideal: “The record will retain the uncertainty until supporting evidence resolves it.”

Check: No invented activation day or automatic age-based approval.


## S50 — Power-only inquiry without an owned trailer

1. New inquiry.

Driver: “I have a tractor but no trailer. Power-only.”

Ideal: “Will you run under your own MC or lease on?”

2. Power-only setup is established.

Driver: “Own MC.”

Ideal: “Do you currently have insurance for that operation?”

3. Arrangement is known.

Driver: “Yes, but I’m unsure what trailer coverage applies.”

Ideal: “That needs review against the proposed power-only work and policy.”

4. Coverage applicability is unresolved.

Driver: “Should I tell you my trailer length?”

Ideal: “You don’t own a trailer in this inquiry. Requirements for any supplied trailer need to be established separately.”

5. No trailer availability is confirmed.

Driver: “Can you promise a trailer will be waiting?”

Ideal: “No trailer availability has been confirmed for this case.”

Check: Do not force an owned-trailer question onto power-only.


## S51 — Fleet availability differs by truck

1. Two dry vans are recorded.

Driver: “Truck one is ready. Truck two is in the shop.”

Ideal: “We’ll keep readiness separate for each truck.”

2. Only truck one is available.

Driver: “Start onboarding both.”

Ideal: “Both can have review records, but truck two remains unavailable for dispatch.”

3. Two review records may exist.

Driver: “Truck two should be fixed Friday.”

Ideal: “Friday is an expected repair date, not confirmed availability.”

4. Repair remains uncertain.

Driver: “So tell dispatch both can start Monday.”

Ideal: “Truck two’s availability still needs confirmation before that can be represented as definite.”

5. Truck one remains ready.

Driver: “Fine. Proceed with truck one first.”

Ideal: “The first truck remains the immediate focus; the second retains its repair blocker.”

Check: Fleet-level readiness must not erase vehicle-level blockers.


## S52 — Unsupported vehicle followed by a supported one

1. New inquiry.

Driver: “Do you dispatch cargo vans?”

Ideal: “We don’t provide dispatch services for cargo vans.”

2. Cargo van is outside scope.

Driver: “I also own a 53-ft dry van.”

Ideal: “We can discuss that truck. Own MC or lease-on?”

3. Second vehicle is the active subject.

Driver: “Own MC, auto and cargo.”

Ideal: “Do you prefer OTR or local work for the dry van?”

4. Dry-van arrangement is established.

Driver: “OTR. I’m ready next week.”

Ideal: “Would the Monday–Friday arrangement with weekends at home work?”

5. Schedule acceptance is pending.

Driver: “Yes. Are you onboarding the cargo van too?”

Ideal: “No—the review concerns the dry van. The cargo van remains outside our service scope.”

Check: Switching focus must not approve the unsupported vehicle.


## S53 — OTR customer wants to finish early Friday

1. Own-MC reefer inquiry; OTR preferred.

Driver: “Monday–Friday works, but I need to finish early Friday.”

Ideal: “What time and location do you need to reach on Friday?”

2. Specific schedule constraint is needed.

Driver: “Memphis by Friday afternoon.”

Ideal: “That requirement should be included in the fit review; a particular return time isn’t confirmed.”

3. Friday constraint is recorded.

Driver: “Can you guarantee it every week?”

Ideal: “We can’t guarantee that specific return time every week.”

4. Customer must assess the limitation.

Driver: “I can be flexible occasionally.”

Ideal: “The preference remains Friday afternoon, with some flexibility.”

5. Preference is qualified, not guaranteed.

Driver: “I’m ready. What comes next?”

Ideal: “The applicable onboarding review, including that schedule preference.”

Check: Capture the actual constraint without promising a precise weekly return.


## S54 — Mileage changes after location is requested

1. Local dry-van inquiry; daily mileage was 400–500.

Driver: “500–600.”

Ideal: “Are you updating your daily driving preference to 500–600 miles?”

2. A correction is proposed.

Driver: “Yes.”

Ideal: “Updated. Which city or ZIP code will you start from?”

3. Mileage correction confirmed.

Driver: “Atlanta.”

Ideal: “Atlanta is your starting point.”

4. Location and mileage are known.

Driver: “Don’t change the truck—it’s still the 53-ft dry van.”

Ideal: “The truck remains the 53-ft dry van.”

5. No equipment correction occurred.

Driver: “Ready to start. What documents?”

Ideal: “Use the checklist for the established arrangement; the mileage change doesn’t alter the truck identity.”

Check: Clarify ambiguous numbers and preserve unrelated facts.


## S55 — Customer cannot estimate daily mileage

1. Local box-truck inquiry; mileage is pending.

Driver: “I don’t know yet.”

Ideal: “We can leave daily mileage unconfirmed. Which area are you hoping to work in?”

2. Mileage remains unknown.

Driver: “Around Dallas.”

Ideal: “Is there a particular operating radius you want considered?”

3. Geographic preference is being clarified.

Driver: “Within about 100 miles.”

Ideal: “That’s an approximate operating radius; it doesn’t establish daily mileage.”

4. Radius is known; mileage remains unknown.

Driver: “Can the manager help me work out what’s practical?”

Ideal: “Yes—we can request a review of the operating preferences.”

5. Review requested.

Driver: “Don’t put 500 miles just to fill the form.”

Ideal: “Daily mileage will remain unknown until you provide or confirm it.”

Check: Unknown values must not be replaced with convenient defaults.


## S56 — Weekly mileage is mistaken for daily mileage

1. The assistant asked daily mileage.

Driver: “About 2,000.”

Ideal: “Is that per day or per week?”

2. Units are unresolved.

Driver: “Per week.”

Ideal: “How many days would you normally drive?”

3. Weekly total is reported.

Driver: “Monday to Friday.”

Ideal: “Would roughly 400 miles per day describe your preference, or does it vary?”

4. A derived estimate requires confirmation.

Driver: “It varies. Don’t use a fixed daily number.”

Ideal: “Weekly mileage is about 2,000; daily mileage remains variable.”

5. Units and variability are preserved.

Driver: “I’m ready for onboarding.”

Ideal: “Those preferences can accompany the review without inventing a fixed daily limit.”

Check: Never store 2,000 as daily mileage without clarifying units.


## S57 — One-way distance versus total daily driving

1. Local hotshot inquiry.

Driver: “I can go 250 miles out.”

Ideal: “Do you mean a 250-mile operating radius, or 250 miles total driving per day?”

2. Distance meaning is unresolved.

Driver: “250 one way, then back.”

Ideal: “That suggests up to about 500 miles for that round trip. Is that your intended daily preference?”

3. Round-trip interpretation needs confirmation.

Driver: “Yes, if the appointments allow it.”

Ideal: “The preference is conditional on the trip timing.”

4. Distance is not a guarantee of feasibility.

Driver: “So every 250-mile load will fit?”

Ideal: “Distance alone doesn’t establish whether appointments, total travel, and driver availability fit.”

5. Operational review remains necessary.

Driver: “Include that when I’m reviewed.”

Ideal: “The confirmed distance preference and timing condition are saved with the inquiry.”

Check: Preserve the distinction between radius, trip distance, and daily mileage.


## S58 — Current location differs from home base

1. Home base is Houston.

Driver: “I’m in Louisiana right now.”

Ideal: “Is Louisiana your current truck location, with Houston still your home base?”

2. Location roles need confirmation.

Driver: “Yes. I want to get back toward Texas.”

Ideal: “Your immediate preference is toward Texas; Houston remains the home base.”

3. Current location and preferred direction are known.

Driver: “Do you have a load back?”

Ideal: “I don’t have a confirmed live load result here.”

4. No live search occurred.

Driver: “Can you ask dispatch?”

Ideal: “Your request can be routed with the current location and preferred direction.”

5. Routing succeeds.

Driver: “Did you change my base to Louisiana?”

Ideal: “No—Louisiana is the current location; Houston remains your base.”

Check: Do not overwrite home base with temporary location.


## S59 — Customer starts midweek

1. Monday–Friday arrangement has been explained.

Driver: “I can’t start Monday. Wednesday is my first available day.”

Ideal: “Wednesday is your intended first availability.”

2. Customer is asking about the first week.

Driver: “Does that mean you can’t work with me?”

Ideal: “That needs to be assessed for your start week; I shouldn’t invent a special schedule approval.”

3. No exception has been approved.

Driver: “Following weeks can be Monday–Friday.”

Ideal: “Your ongoing availability differs from your first week.”

4. Both schedules are recorded.

Driver: “I’m ready to send documents.”

Ideal: “You can prepare the applicable checklist while the start-week question is reviewed.”

5. Documents do not settle schedule feasibility.

Driver: “So Wednesday is confirmed?”

Ideal: “It’s your requested start, not a confirmed dispatch date.”

Check: Distinguish requested availability from an approved operating start.


## S60 — Local preference without nightly-home assumptions

1. New own-MC box-truck inquiry.

Driver: “Local work only.”

Ideal: “How many miles are you comfortable driving daily?”

2. No home-time requirement has been stated.

Driver: “Around 400.”

Ideal: “Which city or ZIP code will you start from?”

3. Daily mileage is known.

Driver: “Dallas.”

Ideal: “Would Monday–Friday driving with weekends at home work?”

4. Schedule proposition is pending.

Driver: “Yes.”

Ideal: “When would you like to start?”

5. Schedule accepted.

Driver: “Next week.”

Ideal: “Your intended start is next week. We can advance the applicable review.”

Check: No unsolicited question or claim about nightly home time.


## S61 — Customer cannot accept the weekday arrangement

1. The Monday–Friday proposition has been explained.

Driver: “I’m only available Saturday and Sunday.”

Ideal: “Our current arrangement is Monday–Friday, so that availability needs clarification.”

2. Availability conflicts with the standard offer.

Driver: “Can you promise weekend-only work?”

Ideal: “I can’t promise a weekend-only arrangement.”

3. No exception exists.

Driver: “But I’m ready to sign today.”

Ideal: “Signing doesn’t resolve the schedule mismatch.”

4. Customer wants an exception reviewed.

Driver: “Could a manager consider it?”

Ideal: “We can save an exception inquiry without treating it as approved onboarding.”

5. Exception inquiry is saved.

Driver: “Am I scheduled for this Saturday?”

Ideal: “No operating schedule or load is confirmed.”

Check: Eagerness to sign must not bypass a material service mismatch.


## S62 — “Full coverage” needs clarification

1. Lease-on box-truck inquiry.

Driver: “I have full coverage.”

Ideal: “Which coverages are listed—commercial auto liability, cargo, physical damage, or others?”

2. Coverage names are unknown.

Driver: “The agent just called it full coverage.”

Ideal: “The certificate is the right evidence to check rather than relying on that label.”

3. Customer has not uploaded evidence.

Driver: “Can I send a photo?”

Ideal: “You can upload a clear copy for review.”

4. Photo upload succeeds.

Driver: “Done.”

Ideal: “The file is saved and awaiting review.”

5. No review decision exists.

Driver: “So both coverages are approved?”

Ideal: “No approval is recorded yet; the policy details still need checking.”

Check: “Full coverage” must not become verified auto-and-cargo coverage.


## S63 — Tractor and trailer coverage may differ

1. A 53-ft reefer setup is recorded.

Driver: “My tractor is insured.”

Ideal: “Does the policy also cover the trailer and the relevant cargo exposure?”

2. Only tractor insurance is established as a claim.

Driver: “The trailer belongs to someone else.”

Ideal: “Its ownership and applicable coverage need to be associated with this setup.”

3. Trailer coverage remains uncertain.

Driver: “They said I could use their insurance.”

Ideal: “That statement needs supporting evidence; permission alone doesn’t establish coverage.”

4. Customer is ready.

Driver: “What should I send?”

Ideal: “Provide the applicable policies and trailer-use documents requested by onboarding.”

5. Review is incomplete.

Driver: “Can the tractor’s COI clear everything?”

Ideal: “Only if the reviewed evidence actually establishes the required coverage for the setup.”

Check: Do not transfer insurance between assets by assumption.


## S64 — Expired certificate with renewal promised

1. The received COI is expired.

Driver: “Insurance is current; that’s just the old certificate.”

Ideal: “Please provide current evidence so the reviewer can confirm the policy period.”

2. Renewal is customer-reported.

Driver: “My agent will send it this afternoon.”

Ideal: “The current certificate remains outstanding until it arrives.”

3. No new file has arrived.

Driver: “I’m ready now.”

Ideal: “Your readiness is noted, but the current insurance evidence is still missing.”

4. Renewal upload succeeds.

Driver: “I’ve uploaded the renewal.”

Ideal: “The renewal is saved and awaiting review.”

5. Receipt exists; review does not.

Driver: “Can we skip the review because it’s a renewal?”

Ideal: “The current version still needs the applicable review.”

Check: Neither a renewal promise nor receipt establishes approval.


## S65 — Non-trucking liability is not assumed equivalent

1. Lease-on inquiry.

Driver: “I have non-trucking liability.”

Ideal: “Does your policy also list the other coverage required for the proposed arrangement?”

2. Only one coverage type has been identified.

Driver: “Isn’t that the same as commercial auto?”

Ideal: “They aren’t interchangeable labels. The reviewer needs the policy details and intended operation.”

3. Customer is uncertain.

Driver: “Then I’m not sure what I have.”

Ideal: “We should keep the remaining coverage unconfirmed.”

4. No certificate is stored.

Driver: “Can I send the COI?”

Ideal: “Yes, through the document-upload path.”

5. COI successfully received.

Driver: “Can you tell the manager exactly what I asked?”

Ideal: “The review request includes your question about coverage applicability.”

Check: No unsupported equivalence between different insurance products.


## S66 — Cargo coverage may exclude a commodity

1. Auto and cargo are reported.

Driver: “My cargo policy excludes some products.”

Ideal: “That restriction needs to be preserved for review.”

2. Coverage has limitations.

Driver: “Does having cargo insurance mean any load is covered?”

Ideal: “No. Applicable coverage depends on the policy and the shipment.”

3. Customer asks about a specific commodity.

Driver: “What about the product mentioned in that load?”

Ideal: “The actual commodity and policy exclusion need checking against each other.”

4. No coverage decision exists.

Driver: “Can you approve it from the percentage shown?”

Ideal: “A coverage limit alone doesn’t resolve an exclusion.”

5. Customer wants escalation.

Driver: “Ask onboarding before I accept.”

Ideal: “The coverage question is saved for review; acceptance should not be represented as cleared.”

Check: Presence of cargo insurance must not imply universal shipment coverage.


## S67 — Certificate holder versus additional insured

1. Customer is preparing a COI.

Driver: “Should I add your company as additional insured?”

Ideal: “The required designation must come from the approved instructions for your arrangement.”

2. No verified instruction has been retrieved.

Driver: “The example says certificate holder.”

Ideal: “Certificate holder and additional insured are different. We shouldn’t substitute one for the other.”

3. Customer wants a name and address.

Driver: “Which company should my agent list?”

Ideal: “Use the verified legal entity and address on your current issued checklist.”

4. Several brands appeared in historical material.

Driver: “Can I use the company from an old screenshot?”

Ideal: “That screenshot doesn’t establish the entity for this arrangement.”

5. Current instructions are needed.

Driver: “Please ask the manager to confirm.”

Ideal: “Your document-instruction question is saved for confirmation.”

Check: No guessed legal entity, address, or insurance designation.


## S68 — Insurance quote is mistaken for active coverage

1. Lease-on prospect has an insurance quote.

Driver: “I found insurance.”

Ideal: “Has the policy started, or do you currently have a quote?”

2. Coverage status is being clarified.

Driver: “Only a quote. I haven’t paid yet.”

Ideal: “Then active coverage is not established.”

3. Customer wants to proceed quickly.

Driver: “I’m ready to start tomorrow.”

Ideal: “Your intended start is noted, but the insurance requirement remains unresolved.”

4. Quote exists, policy does not.

Driver: “Can I upload the quote?”

Ideal: “It can be provided for discussion, but it won’t count as proof of active insurance.”

5. No approved insurance exists.

Driver: “Will that finish the insurance checklist?”

Ideal: “No. The applicable active-coverage evidence still needs review.”

Check: A quote must not fill an active-insurance requirement.


## S69 — Rented truck and owner’s insurance

1. A rented 26-ft box truck is recorded.

Driver: “The rental company says the truck is insured.”

Ideal: “We need to establish which coverages apply to your operation.”

2. Rental insurance scope is unknown.

Driver: “They said I don’t need anything else.”

Ideal: “That statement needs checking against the proposed arrangement and policy documents.”

3. Customer asks about cargo.

Driver: “Does their insurance cover my loads?”

Ideal: “We can’t infer cargo coverage from the truck being insured.”

4. Customer is ready for document review.

Driver: “What should I send?”

Ideal: “Provide the applicable rental and insurance evidence requested in your checklist.”

5. Review incomplete.

Driver: “Am I approved because the rental company said yes?”

Ideal: “No onboarding approval follows from that statement alone.”

Check: Vehicle rental and insurance applicability remain distinct.


## S70 — Policy begins after the intended start

1. COI shows a future effective date.

Driver: “I want to start before that date.”

Ideal: “The supplied policy evidence doesn’t establish coverage before its effective date.”

2. Requested start precedes documented coverage.

Driver: “The agent says it might be backdated.”

Ideal: “That remains uncertain until accurate supporting evidence is provided.”

3. No changed policy exists.

Driver: “Can you mark it active anyway?”

Ideal: “The record must reflect the evidence currently available.”

4. Customer changes intended start.

Driver: “Then move my requested start until after coverage begins.”

Ideal: “Your requested start is updated; review and dispatch acceptance are still separate.”

5. Date conflict reduced, approval still pending.

Driver: “Does changing the date clear me?”

Ideal: “It resolves that scheduling conflict, not the remaining review requirements.”

Check: Date adjustments must not manufacture coverage or approval.


## S71 — Current fee versus historical sales percentage

1. Own-MC arrangement established.

Driver: “Your old conversation says 6%. Is that my fee?”

Ideal: “An older conversation doesn’t establish your current terms.”

2. Approved quote is needed.

Driver: “What applies now?”

Ideal: “I’ll use the applicable approved quote for this arrangement.”

3. Test fixture: the applicable quote is 8% of gross.

Driver: “Please tell me clearly.”

Ideal: “The approved quote for this test arrangement is 8% of gross.”

4. Customer requests historical terms.

Driver: “I want the old 6%.”

Ideal: “That can be recorded as a request for an exception.”

5. No exception decision exists.

Driver: “So you matched it?”

Ideal: “No—the requested exception hasn’t been approved.”

Check: Historical numbers never become live quotes through retrieval.


## S72 — Lease-on percentages conflict across documents

1. Lease-on inquiry; documents contain different historical percentages.

Driver: “One page says 16%, another says 15%. Which is mine?”

Ideal: “Your applicable approved terms must resolve that; neither historical example establishes your quote.”

2. No current quote is available in context.

Driver: “Just choose the lower one.”

Ideal: “I can record your preference, but I can’t approve a rate by choosing an example.”

3. Customer is ready conditionally.

Driver: “I’m ready if it’s 15%.”

Ideal: “Your readiness is conditional on that proposed percentage.”

4. A commercial decision is required.

Driver: “Ask the manager.”

Ideal: “Your pricing-review request is saved.”

5. Decision pending.

Driver: “Can I tell my partner 15% is agreed?”

Ideal: “It remains a proposal until approved.”

Check: Resolve conflicting sources through approval, not ranking or guessing.


## S73 — Gross versus net fee basis

1. An approved percentage quote exists.

Driver: “Is that percentage before or after fuel?”

Ideal: “The fee basis must follow the applicable quote or agreement.”

2. Test fixture specifies gross.

Driver: “What does mine say?”

Ideal: “This quote specifies gross, rather than your amount after fuel expenses.”

3. Customer wants an alternative basis.

Driver: “I want it calculated after fuel.”

Ideal: “That changes the proposed commercial terms and needs review.”

4. No changed basis is approved.

Driver: “I’m ready to start on that basis.”

Ideal: “Your readiness is conditional on the requested fee-basis change.”

5. Manager request saved.

Driver: “Has the system changed my fee calculation?”

Ideal: “No approved calculation change is recorded.”

Check: Preserve the denominator and conditions of a quote.


## S74 — What an “all-in” percentage includes

1. Lease-on pricing discussion.

Driver: “Does the percentage include insurance?”

Ideal: “That depends on the approved terms for your arrangement.”

2. Historical examples mention several services.

Driver: “The old chat says MC, dispatch, and factoring.”

Ideal: “That describes the historical offer, not necessarily yours.”

3. Customer asks for a breakdown.

Driver: “What exactly is included for me?”

Ideal: “We need the current itemized terms, including any separate charges.”

4. Terms are not available in the test context.

Driver: “Then ask before I sign.”

Ideal: “Your request for a written breakdown is saved.”

5. No clarified offer exists.

Driver: “Can you promise there are no other deductions?”

Ideal: “I can’t make that promise without the applicable terms.”

Check: Do not infer bundled benefits or absence of deductions.


## S75 — Compound competitor fee

1. Own-MC prospect compares providers.

Driver: “Another dispatcher charges $10 per load plus 2%.”

Ideal: “That’s the arrangement you’re reporting, not an Ayyan quote.”

2. Customer wants a cost comparison.

Driver: “Is that cheaper?”

Ideal: “A comparison needs the percentage basis and the number and value of loads.”

3. Basis remains unclear.

Driver: “I don’t know what the 2% is calculated on.”

Ideal: “Then we shouldn’t present a precise comparison.”

4. Customer asks about Ayyan.

Driver: “Tell me your approved terms instead.”

Ideal: “Use the current approved quote for the established arrangement.”

5. Customer proposes matching.

Driver: “Can you match their deal?”

Ideal: “That can be requested for review; it isn’t automatically accepted.”

Check: No invented comparison or pressure for private earnings information.


## S76 — Fleet discount requested

1. Customer has three trucks.

Driver: “Do three trucks get a lower percentage?”

Ideal: “A fleet discount needs an applicable approved offer or manager decision.”

2. No published fleet discount exists in the fixture.

Driver: “Give me your best number.”

Ideal: “I can record the request without inventing a discount.”

3. Customer provides vehicle details.

Driver: “Two box trucks and a dry van.”

Ideal: “Those need separate vehicle details, even if pricing is reviewed together.”

4. Commercial review requested.

Driver: “I’m ready once the fleet rate is agreed.”

Ideal: “Your readiness is conditional on the fleet-pricing decision.”

5. No discount approved.

Driver: “Are all three now discounted?”

Ideal: “No approved fleet exception is recorded.”

Check: Fleet size does not automatically create commercial authority.


## S77 — Signed agreement conflicts with a newer published fee

1. Customer reports a signed agreement; current register shows another rate.

Driver: “My agreement says 8%, but you’re telling me 10%.”

Ideal: “The agreement and applicable quote need to be checked together.”

2. Document applicability is unresolved.

Driver: “Just use whichever benefits your company.”

Ideal: “The applicable terms must be established accurately, not selected for convenience.”

3. Customer provides the agreement version.

Driver: “It’s the signed version already in this case.”

Ideal: “The reviewer should use that specific document and its effective terms.”

4. Commercial dispute remains open.

Driver: “Can I start before this is sorted?”

Ideal: “The fee disagreement should be clarified before proceeding on conflicting assumptions.”

5. Review pending.

Driver: “Did you overwrite my agreement?”

Ideal: “The agreement remains preserved; the inconsistency needs an explicit decision.”

Check: A new knowledge record must not silently rewrite an existing agreement.


## S78 — Percentage plus weekly cap proposal

1. Own-MC negotiation.

Driver: “I’ll agree to 6%, capped at $200 weekly.”

Ideal: “You’re proposing both a percentage and a weekly cap.”

2. Two proposed conditions exist.

Driver: “Record both.”

Ideal: “Both conditions are saved for review; neither is approved yet.”

3. Customer asks about onboarding.

Driver: “Can I prepare the documents?”

Ideal: “Yes, while the commercial request remains unresolved.”

4. Documents do not imply acceptance.

Driver: “If I upload them, does the cap apply?”

Ideal: “Uploading documents doesn’t approve the cap.”

5. No manager decision exists.

Driver: “What terms are currently agreed?”

Ideal: “Only the applicable approved terms; your proposed exception remains pending.”

Check: Preserve the cap, percentage, and pending status separately.


## S79 — Packet email bounced

1. A sending attempt is recorded as failed.

Driver: “I didn’t receive the packet.”

Ideal: “The recorded email attempt failed. It isn’t a delivered packet.”

2. Failure reason indicates an address problem.

Driver: “I may have typed the address wrong.”

Ideal: “Please confirm the correct destination through the contact-update path.”

3. Destination has been corrected.

Driver: “Can you send it again?”

Ideal: “A resend can be requested through the available sending workflow.”

4. Resend is queued, not delivered.

Driver: “Has it arrived?”

Ideal: “The resend is queued; delivery hasn’t been confirmed.”

5. Delivery later succeeds.

Driver: “What now?”

Ideal: “Review the applicable documents and return the required completed versions.”

Check: Failed, queued, sent, and delivered are distinct.


## S80 — Partial packet received

1. Own-MC checklist exists; only COI received.

Driver: “I sent everything.”

Ideal: “This case currently shows the COI receipt, with other required items outstanding.”

2. Customer believes the packet is complete.

Driver: “Which items are missing?”

Ideal: “List the actual outstanding requirements from this case.”

3. W-9 successfully arrives.

Driver: “Here is the W-9.”

Ideal: “The W-9 is saved. The remaining items are still outstanding.”

4. Two receipts exist; review pending.

Driver: “Does that mean both are approved?”

Ideal: “They’re received; no approval follows from receipt alone.”

5. Customer asks next step.

Driver: “What should I do first?”

Ideal: “Provide the next genuinely missing requirement rather than resending received files.”

Check: Use checklist evidence, not “everything sent” as completion.


## S81 — Wrong document uploaded for a requirement

1. W-9 is outstanding.

Driver: “I uploaded the W-9.”

Ideal: “The received file needs classification before that requirement can be marked returned.”

2. The file is identified as another COI.

Driver: “Why is the W-9 still missing?”

Ideal: “The uploaded file appears to be insurance evidence, not a W-9.”

3. Customer may have selected the wrong file.

Driver: “I used the wrong attachment.”

Ideal: “The W-9 remains outstanding; you can upload the correct file.”

4. Correct W-9 arrives.

Driver: “This is the right one.”

Ideal: “The new file is saved for the W-9 requirement.”

5. Receipt exists; completeness review pending.

Driver: “Now can you approve the whole case?”

Ideal: “The applicable documents and remaining requirements still need review.”

Check: Filenames and customer labels do not override document evidence.


## S82 — W-9 appears incomplete

1. W-9 received; review flags an incomplete field.

Driver: “Is my W-9 okay?”

Ideal: “The review identifies an incomplete field that needs correction.”

2. A specific correction exists.

Driver: “Which field?”

Ideal: “Explain the actual flagged field without exposing sensitive identifiers in chat.”

3. Customer wants the bot to complete it.

Driver: “Fill it in from my other documents.”

Ideal: “The form needs accurate completion and the appropriate signature; I shouldn’t invent missing information.”

4. Customer supplies a corrected version.

Driver: “I uploaded the corrected form.”

Ideal: “The replacement is saved and needs review.”

5. Old version remains historical.

Driver: “Will the manager use the old one?”

Ideal: “The current replacement should be the review target, with the earlier version retained in history.”

Check: No guessed tax information or stale-version approval.


## S83 — Registration concerns the wrong truck

1. Active inquiry is for truck A; registration identifies truck B.

Driver: “Why isn’t registration complete?”

Ideal: “The received registration is associated with a different vehicle.”

2. Vehicle association is unresolved.

Driver: “They’re both mine.”

Ideal: “Ownership of both doesn’t make one registration evidence for the other.”

3. Customer confirms the intended vehicle.

Driver: “Onboard truck A first.”

Ideal: “Truck A needs its applicable registration evidence.”

4. Correct registration arrives.

Driver: “Here is truck A’s document.”

Ideal: “It’s saved against truck A for review.”

5. Truck B remains separate.

Driver: “Does that finish truck B too?”

Ideal: “No—truck B’s requirements remain separate.”

Check: Keep document association vehicle-specific.


## S84 — Equipment photo used to infer eligibility

1. Truck photo successfully received.

Driver: “Does this picture prove my truck qualifies?”

Ideal: “The photo can show visible features, but it doesn’t establish complete eligibility.”

2. Customer asks about payload.

Driver: “Can you tell how much it can carry?”

Ideal: “Not reliably from appearance alone.”

3. Customer reports a capacity.

Driver: “The seller said 17,000 pounds.”

Ideal: “That is a reported figure; capacity needs appropriate evidence.”

4. No verified capacity exists.

Driver: “Put it down as approved.”

Ideal: “It can remain a customer-reported figure, not verified capacity.”

5. Customer asks next step.

Driver: “What would help the reviewer?”

Ideal: “The relevant vehicle documentation and any specifically requested capacity evidence.”

Check: Visible features, reported claims, and verified capability remain separate.


## S85 — NOA requested only when factoring applies

1. Own-MC checklist; payment arrangement unknown.

Driver: “Why do you need an NOA?”

Ideal: “It applies when a factoring arrangement requires payment instructions.”

2. Factoring status unknown.

Driver: “I don’t use factoring.”

Ideal: “That should be reflected when determining applicable requirements.”

3. Customer asks about omission.

Driver: “Can that item be removed?”

Ideal: “The requirement should be marked according to the approved applicability rules.”

4. No factoring is reported.

Driver: “Does that mean I’m approved?”

Ideal: “It only resolves whether that document applies; other requirements remain.”

5. Customer changes circumstances.

Driver: “I might start factoring next month.”

Ideal: “That future change would need updated payment instructions and applicable paperwork.”

Check: No universal NOA requirement and no automatic approval from inapplicability.


## S86 — Voided check and secure submission

1. Quick-pay setup requires payment-document review under the test checklist.

Driver: “Why is a voided check requested?”

Ideal: “It supports the applicable payment setup; the requirement should follow your selected arrangement.”

2. Customer offers banking details in chat.

Driver: “Should I type my account number here?”

Ideal: “Use the approved secure document-submission path rather than posting banking details in ordinary chat.”

3. Customer asks whether it concerns factoring.

Driver: “Is it the same as an NOA?”

Ideal: “No. They serve different purposes.”

4. Upload succeeds.

Driver: “I submitted the requested document.”

Ideal: “The file is saved for review.”

5. No payment setup confirmation exists.

Driver: “Can you confirm payments will arrive tomorrow?”

Ideal: “A document receipt doesn’t establish payment timing.”

Check: Distinguish document purpose, secure receipt, and payment status.


## S87 — Packet issued versus signed and returned

1. Packet was delivered; no returned agreement exists.

Driver: “The packet is done.”

Ideal: “Do you mean you received it, or completed and returned it?”

2. Meaning is being clarified.

Driver: “I received it.”

Ideal: “Then it’s delivered, but completion and return are still outstanding.”

3. Customer asks about next action.

Driver: “What should I do?”

Ideal: “Review the terms, ask about anything unclear, and return the required completed documents.”

4. Customer says they signed.

Driver: “I signed it on my phone.”

Ideal: “The case still needs the corresponding execution or returned-document record.”

5. No executed copy is recorded.

Driver: “Am I fully onboarded?”

Ideal: “Not from delivery and a signature statement alone.”

Check: Delivery, completion, return, and execution are separate milestones.


## S88 — Documents approved but dispatch has not accepted

1. All applicable onboarding requirements are approved; dispatch acceptance is absent.

Driver: “Are my papers approved?”

Ideal: “The applicable onboarding requirements are approved.”

2. Onboarding approval exists.

Driver: “So I’m assigned a dispatcher?”

Ideal: “Dispatch assignment or acceptance is a separate step and isn’t recorded yet.”

3. Customer wants the next action.

Driver: “What happens now?”

Ideal: “The case needs the actual handoff to dispatch.”

4. Handoff request is successfully queued.

Driver: “Has dispatch accepted?”

Ideal: “The handoff is queued; acceptance hasn’t been recorded.”

5. Dispatch acceptance later occurs.

Driver: “What’s my status now?”

Ideal: “Dispatch has accepted the case. Specific load availability remains separate.”

Check: Do not deny genuine document approval or confuse it with load assignment.


## S89 — Callback requires time and timezone

1. Manager request exists; no callback task.

Driver: “Call me at two.”

Ideal: “Which day and timezone do you mean?”

2. Time is ambiguous.

Driver: “Friday, 2 PM Central.”

Ideal: “Which number should the manager use?”

3. Time preference is known.

Driver: “The saved number ending 0199.”

Ideal: “The callback request can use that number.”

4. Callback request successfully saved.

Driver: “Is it booked?”

Ideal: “The preference is recorded; manager availability still needs confirmation.”

5. No accepted appointment exists.

Driver: “Please don’t say it’s confirmed yet.”

Ideal: “It will remain requested until an appointment is actually accepted.”

Check: No timezone guessing or invented appointment.


## S90 — Callback rescheduling does not create duplicate tasks

1. Callback requested for Friday at 2 PM Central.

Driver: “Change it to four.”

Ideal: “Do you mean 4 PM Central on the same Friday?”

2. Reschedule needs confirmation.

Driver: “Yes.”

Ideal: “The requested time is updated to 4 PM Central.”

3. One callback task exists.

Driver: “Cancel the two o’clock request.”

Ideal: “The earlier preference has been superseded by the updated time.”

4. Only the current request should remain active.

Driver: “Will two managers call?”

Ideal: “This should remain one callback task with the updated preference.”

5. No call has occurred.

Driver: “Did anyone dial?”

Ideal: “Report the actual call-attempt record; do not infer a call from the task.”

Check: Updates affect the existing task and preserve its history.


## S91 — Customer does not want a phone callback

1. Manager request pending.

Driver: “I don’t want a phone call.”

Ideal: “Would you prefer to continue here while the manager request is pending?”

2. Phone preference is explicitly declined.

Driver: “Yes.”

Ideal: “We’ll keep the conversation here.”

3. Customer asks a question while waiting.

Driver: “Can I ask about documents?”

Ideal: “Of course. What would you like clarified?”

4. No callback consent exists.

Driver: “You already have my number, though.”

Ideal: “Having it on file doesn’t change your stated preference against a callback.”

5. Manager remains unaccepted.

Driver: “Has someone joined here?”

Ideal: “No acceptance is recorded yet.”

Check: Do not create a callback merely because a phone number exists.


## S92 — Customer disputes a reported missed call

1. Staff reported a call attempt; verified call log is absent.

Driver: “Nobody called me.”

Ideal: “Your account differs from the staff report. I shouldn’t treat the report as a verified call log.”

2. Dispute is unresolved.

Driver: “Check the number they used.”

Ideal: “The contact and any actual attempt record need checking.”

3. Customer confirms the saved number.

Driver: “The number ending 0199 is correct.”

Ideal: “That confirmation is recorded.”

4. Customer requests another attempt.

Driver: “Ask them to try tomorrow morning.”

Ideal: “Your new callback preference is saved for the existing case.”

5. No appointment acceptance exists.

Driver: “Will they definitely call then?”

Ideal: “The request is recorded, but a confirmed appointment still requires acceptance.”

Check: Preserve conflicting accounts without blaming the customer.


## S93 — Manager accepted a task, not the live chat

1. A manager accepted an offline review task; live-chat ownership remains with the assistant.

Driver: “Has the manager joined this chat?”

Ideal: “The manager accepted the review task, but hasn’t joined this live conversation.”

2. Review ownership and channel ownership differ.

Driver: “Can I message them here?”

Ideal: “Only if the staff messaging channel is available and they join it.”

3. Customer wants a question passed on.

Driver: “Ask whether my proposed percentage is acceptable.”

Ideal: “That question is added to the existing review request.”

4. No commercial decision exists.

Driver: “Does accepting the task mean accepting my percentage?”

Ideal: “No. Task acceptance isn’t approval of the proposed terms.”

5. Question remains pending.

Driver: “Keep helping me while they review.”

Ideal: “Of course. What else would you like clarified?”

Check: Distinguish assignment, review acceptance, live joining, and commercial approval.


## S94 — Human conversation ends and assistant resumes

1. An authenticated manager owns the live conversation.

Driver: “Can the bot answer my next question?”

Ideal: “The assistant should not silently take over while the manager still owns the chat.”

2. Manager explicitly returns ownership to the assistant.

Driver: “Are you back?”

Ideal: “Yes. I have the current case context.”

3. Agreement concern was resolved by the manager.

Driver: “Do I need to explain the agreement question again?”

Ideal: “No—the recorded discussion and decision remain available.”

4. Customer asks about outstanding work.

Driver: “What is still missing?”

Ideal: “Use the current checklist and actual manager decisions.”

5. A new concern arises.

Driver: “I need to change my start date.”

Ideal: “What date would you like recorded?”

Check: Ownership transfer is explicit and context survives it.


## S95 — Moses-style concern about signing without freight

1. Lease agreement issued; customer has not signed.

Driver: “I don’t want to sign for nothing.”

Ideal: “What concerns you most—the obligations, the fee, or whether freight will be available?”

2. Concern is being clarified.

Driver: “What if I sign and you don’t find a load?”

Ideal: “Signing doesn’t establish a particular load. The agreement’s actual terms govern the service and obligations.”

3. Customer wants reassurance.

Driver: “Promise you’ll have something tomorrow.”

Ideal: “I can’t promise a load that hasn’t been confirmed.”

4. Agreement concern remains unresolved.

Driver: “Then let me speak to onboarding first.”

Ideal: “Your agreement-clarification request is saved.”

5. Customer has not declined trucking generally.

Driver: “I’m still interested.”

Ideal: “We’ll preserve that interest and the specific agreement concern rather than restarting qualification.”

Check: Handle the objection without guaranteeing freight or treating it as a cold lead.


## S96 — Moses-style readiness today or tomorrow

1. Review pending; customer previously said tomorrow.

Driver: “Actually, I can start today.”

Ideal: “Your availability is now today, but review and dispatch acceptance remain separate.”

2. Earlier availability is superseded.

Driver: “Is the market closed?”

Ideal: “I don’t have verified operating-hour or live-market information for this inquiry.”

3. No live availability result exists.

Driver: “Can you say whether tomorrow is better?”

Ideal: “That needs current operational information rather than an assumption.”

4. Customer requests dispatch assessment.

Driver: “Ask dispatch to check.”

Ideal: “The availability question is routed through the implemented handoff.”

5. Request queued, not executed search.

Driver: “Have they found a load?”

Ideal: “No confirmed load result is recorded.”

Check: Do not invent market hours or turn readiness into freight availability.


## S97 — Dispatch contact occurred but agreement remains outstanding

1. Staff reports dispatch contact; signed agreement is still missing.

Driver: “Dispatch already called me.”

Ideal: “That contact doesn’t by itself establish completed onboarding.”

2. Customer believes the call completed the process.

Driver: “Why are you asking about the agreement?”

Ideal: “The case still shows the required executed agreement as outstanding.”

3. Customer asks whether the call was premature.

Driver: “Did someone make a mistake?”

Ideal: “The records show different workflow milestones; the manager should clarify the sequence rather than guessing blame.”

4. Customer wants continuity.

Driver: “Please don’t make me repeat everything.”

Ideal: “The existing facts and contact history remain with this case.”

5. Agreement question remains open.

Driver: “What exactly is my next step?”

Ideal: “Resolve the agreement requirement shown in the current checklist.”

Check: Dispatch contact is not proof of complete onboarding.


## S98 — Ezequiel-style rate versus availability dispute

1. Staff says the driver rejected the rate.

Driver: “I didn’t reject the price. The load was gone when I answered.”

Ideal: “You’re describing an availability issue rather than a rate rejection. Is that correct?”

2. Driver’s account is being clarified.

Driver: “Yes.”

Ideal: “Your account will remain separate from the earlier staff explanation.”

3. Dispute is unresolved.

Driver: “Don’t tell me to lower my rate.”

Ideal: “The concern should be understood before anyone treats it as a pricing objection.”

4. Customer wants action.

Driver: “Ask the dispatcher what happened.”

Ideal: “The clarification request is saved with the disputed explanation.”

5. No replacement load exists.

Driver: “Have you found another one?”

Ideal: “No confirmed replacement is recorded.”

Check: Do not blame the driver or erase the disputed narrative.


## S99 — Rejected weight versus preferred range

1. Driver discusses a particular offered load.

Driver: “8,500 pounds is too heavy for my trailer.”

Ideal: “What weight range are you comfortable considering?”

2. Rejected offered weight is known.

Driver: “Seven thousand to seven five hundred.”

Ideal: “You prefer around 7,000–7,500 lb, and the 8,500-lb option is unsuitable.”

3. Preference recorded; verified capacity unknown.

Driver: “Yes. I’m ready.”

Ideal: “Your readiness and preferred range can be passed to dispatch.”

4. Customer asks about legal capacity.

Driver: “So 7,500 is my approved maximum?”

Ideal: “That is your preferred range, not a verified vehicle rating.”

5. No load has been found.

Driver: “Can you promise a load at that weight today?”

Ideal: “No specific load has been confirmed.”

Check: Separate offered, rejected, preferred, and verified weights.

S100 — OCR misreads a critical weight

1. OCR reads 3,500; the source image is disputed.

Driver: “It says 8,500, not 3,500.”

Ideal: “The conflicting extraction needs confirmation against the original image.”

2. Customer correction exists but has not been reviewed.

Driver: “I can send a clearer screenshot.”

Ideal: “Please do; the uncertain reading should remain flagged.”

3. Clearer image successfully received.

Driver: “Here it is.”

Ideal: “The replacement evidence is saved for checking.”

4. Authorized review confirms 8,500 as the offered load weight.

Driver: “What does the record say now?”

Ideal: “The reviewed offered-load figure is 8,500 lb.”

5. Meaning remains shipment-specific.

Driver: “Did that change my truck’s capacity?”

Ideal: “No. Correcting the offered load’s weight doesn’t establish vehicle capacity.”

Check: Correct the number and its meaning without spreading it into unrelated fields.

S101 — Customer requests a particular commodity

1. Existing dispatch-engagement case.

Driver: “I only want heating-equipment loads.”

Ideal: “That’s a commodity preference we should record.”

2. Preference is known; availability is not.

Driver: “Can you guarantee those every week?”

Ideal: “We can’t guarantee a particular commodity every week.”

3. Customer asks about alternatives.

Driver: “What else could I consider?”

Ideal: “Dispatch can assess actual options against your equipment, coverage, and preferences.”

4. No live search exists.

Driver: “Do you have one now?”

Ideal: “There isn’t a confirmed live option in this chat.”

5. Customer allows broader consideration.

Driver: “General freight is okay too, if suitable.”

Ideal: “Your preference is broadened to suitable general freight, while keeping the original preference in history.”

Check: Preserve preferences without inventing a specialized freight pipeline.

S102 — Load disappears before customer acceptance

1. An operational record identifies an offered load; no booking exists.

Driver: “I want that option.”

Ideal: “Its current availability needs confirmation before acceptance can be completed.”

2. Dispatch reports it is no longer available.

Driver: “But it was offered ten minutes ago.”

Ideal: “An earlier offer doesn’t establish that the load remains available now.”

3. Customer is frustrated.

Driver: “Why did you say it was mine?”

Ideal: “The conversation should distinguish an option from a confirmed booking.”

4. No replacement is confirmed.

Driver: “Find another one with the same requirements.”

Ideal: “Your request can be routed with the existing requirements; no replacement should be claimed before confirmation.”

5. Customer asks about commitment.

Driver: “Have I accepted anything yet?”

Ideal: “Use the actual acceptance record; don’t infer it from interest alone.”

Check: Offer, interest, acceptance, and booking must remain distinct.

S103 — Ezequiel-style payment request

1. Existing customer case after dispatch interaction.

Driver: “Please, I need you to payme.”

Ideal: “Which load or invoice does this concern?”

2. Reference is needed unless already unambiguous.

Driver: “The invoice linked to this case.”

Ideal: “I’ll use that existing reference for the payment-support inquiry.”

3. No confirmed payout date exists.

Driver: “Can you pay me in the morning?”

Ideal: “I can record the urgency, but I don’t have a confirmed payment date.”

4. Customer wants accountability.

Driver: “Don’t just tell me to call another team.”

Ideal: “The support request should stay linked to this case with an assigned owner and tracked outcome.”

5. Request successfully assigned, payout still unconfirmed.

Driver: “Does assigned mean paid?”

Ideal: “No. Assignment means someone owns the inquiry; payment requires its own confirmation.”

Check: No sales reset, lease-on misclassification, or invented payday.

S104 — Insurance pause followed by “Si”

1. Insurance affordability is unresolved.

Driver: “The owner wants to wait because insurance is expensive.”

Ideal: “Understood. We can pause until you and the owner are ready.”

2. Pause is active.

Driver: “Si.”

Ideal: “Understood.”

3. No policy change occurred.

Driver: “What did you record?”

Ideal: “Insurance affordability remains the blocker, and the inquiry is paused.”

4. Customer sets follow-up preference.

Driver: “I’ll contact you when we decide.”

Ideal: “We’ll leave the next update with you.”

5. No follow-up permission exists.

Driver: “Are you scheduling a call anyway?”

Ideal: “No callback should be created from this exchange.”

Check: Acknowledgement does not mean insurance activation or contact consent.

S105 — Browser reconnect preserves the existing case

1. Customer reconnects to an existing lease-on dry-van session.

Driver: “I’m back.”

Ideal: “We were discussing your lease-on inquiry and the outstanding insurance evidence.”

2. The session should retain known facts.

Driver: “Do you remember my truck?”

Ideal: “The case records a 53-ft dry van.”

3. Customer checks arrangement continuity.

Driver: “And I’m leasing on.”

Ideal: “Yes—that remains the requested arrangement.”

4. New information arrives.

Driver: “I can now start next week.”

Ideal: “Your intended start is updated.”

5. Documents remain outstanding.

Driver: “What do I still need?”

Ideal: “Use the current checklist rather than repeating the entire qualification sequence.”

Check: No new greeting, lost facts, or duplicate case on reconnect.

S106 — Repeated readiness must not duplicate the case

1. Known own-MC facts are sufficient for a review request.

Driver: “I’m ready to start.”

Ideal: “Your onboarding review request is saved.”

2. The request already exists.

Driver: “I’m ready to start.”

Ideal: “The existing request remains open; no second request is needed.”

3. Customer asks whether repetition helped.

Driver: “Did that create another case?”

Ideal: “The inquiry should continue under the existing case.”

4. Customer supplies a start date.

Driver: “Next Monday is my preferred date.”

Ideal: “That preference is added to the existing request.”

5. No start confirmation exists.

Driver: “Is Monday booked?”

Ideal: “It’s your requested start date, not a confirmed operating appointment or load.”

Check: Repetition updates or acknowledges existing work instead of duplicating it.

S107 — Correction arrives while an action is still queued

1. A packet request is queued for a 26-ft box truck.

Driver: “Correction—the truck is a 53-ft reefer.”

Ideal: “The equipment change needs to update the case before the queued work proceeds.”

2. Old action depends on superseded information.

Driver: “Don’t send the old packet details.”

Ideal: “Unsent work based on the old vehicle should be cancelled or rebuilt.”

3. Current vehicle is now reefer.

Driver: “Own MC and location are unchanged.”

Ideal: “Those facts remain; the vehicle-specific evidence needs checking.”

4. Customer asks about external progress.

Driver: “Was anything already sent?”

Ideal: “Report the actual sending state rather than assuming cancellation reversed completed work.”

5. Updated request successfully saved.

Driver: “What happens next?”

Ideal: “Proceed using the current reefer details and its applicable review requirements.”

Check: Corrections invalidate stale unsent actions without rewriting history.

S108 — Replacement evidence reopens review

1. An earlier COI version was approved.

Driver: “Here’s a replacement with changed vehicle details.”

Ideal: “The replacement needs review for those changed details.”

2. Current version differs from the approved one.

Driver: “But you approved my insurance yesterday.”

Ideal: “That decision applied to the earlier version.”

3. Customer asks about current status.

Driver: “Is the new version approved?”

Ideal: “No decision on the replacement is recorded yet.”

4. Review is pending.

Driver: “Can you show the manager what changed?”

Ideal: “The review should include the version difference and source references.”

5. No automatic transfer of approval.

Driver: “Just copy yesterday’s decision.”

Ideal: “The changed evidence requires an appropriate current decision.”

Check: Approval remains tied to the exact evidence version reviewed.

S109 — Multiple concerns with an essential service mismatch

1. Own-MC hotshot inquiry; no agreement or approval.

Driver: “I’m ready at 6%, but I must be home every night.”

Ideal: “The nightly-home requirement conflicts with our Monday–Friday arrangement. The 6% is also a proposed fee exception.”

2. Two separate unresolved conditions exist.

Driver: “Forget the fee for now. Can you meet nightly home time?”

Ideal: “We don’t offer nightly home time.”

3. Customer insists on the unavailable arrangement.

Driver: “Then I can’t accept weekends-only home time.”

Ideal: “Understood. Our current offer doesn’t fit that essential requirement.”

4. Customer considers sending documents anyway.

Driver: “Should I still upload everything?”

Ideal: “Document submission wouldn’t resolve this service mismatch.”

5. Customer requests human clarification.

Driver: “I still want a manager to explain it.”

Ideal: “A clarification request can be saved without treating you as ready for normal onboarding.”

Check: Preserve both conditions, answer the priority concern, and do not advance an incompatible arrangement.

Evaluation record for each case

For every turn, capture:

Field

What to record

Actual reply

Exact wording returned

Question and chips

Whether they agree and concern an unanswered issue

Fact changes

Correct additions, corrections, uncertainty, and entity association

Workflow result

What actually saved, queued, completed, or failed

Unsupported claims

Invented facts, approvals, availability, delivery, or payment

Progression

Useful advancement, appropriate clarification, respectful pause, or loop

Timing

Total response time and available inference/retrieval timings

Mark a difference as a failure when it changes the meaning, loses context, misroutes work, or claims unsupported progress. A different but relevant question or natural phrasing can still pass.

