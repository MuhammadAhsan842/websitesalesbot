const KNOWLEDGE = {
  version: "ayyan_sales_v1",
  welcome: "Ayyan Dispatch. I can help with carrier dispatch, a service question, or an existing account. What do you need?",
  services: "We dispatch dry van, reefer, flatbed, box truck, and hotshot for owner-operators and small fleets. You approve every load. We handle brokers and paperwork.",
  onboarding: "If you run your own MC, a person sends the dispatch setup packet. If you want to lease on, a person reviews eligibility and the lease. The assistant does not approve onboarding.",
  fee: "Live dispatch fees are quoted by staff after the arrangement is confirmed. I will not invent a percentage, a discount, or an earnings figure.",
  guarantee: "We do not guarantee weekly gross, a set number of loads, or specific lanes paying a rate.",
  fuel: "A fuel card is not part of the standard dispatch arrangement unless staff confirm a current program.",
  ownMc: "Own-MC dispatch: keep your authority. Staff send the setup packet and review documents.",
  lease: "Lease-on: staff confirm eligibility and the agreement. Asking to lease on is not approval.",
  docsOwn: "Usual own-MC items: MC authority sheet, W-9, certificate of insurance, notice of assignment, voided check. Staff confirm the live list.",
  docsLease: "Usual lease-on items: licence, insurance, medical card, inspection, W-9, lease. Staff confirm the live list.",
  support: "Existing-carrier issues go to the operations desk. I will not run sales qualification on an open dispatch problem.",
  unknown: "I do not have an approved answer for that. I can note it for the team instead of guessing.",
};

function lookupKnowledge(topic) {
  return KNOWLEDGE[topic] || null;
}
