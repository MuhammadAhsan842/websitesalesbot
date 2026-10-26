const KNOWLEDGE = {
  version: "ayyan_sales_v2",
  welcome: "I'm Ayyan Group's AI sales assistant. I can check if we're a fit; our onboarding manager handles the papers. What are you running?",
  services: "We dispatch dry van, reefer, flatbed, box truck, and hotshot for owner-operators and small fleets. You approve every load. We handle brokers and paperwork.",
  onboarding: "Talking here isn't a contract. If you keep your own MC, our onboarding manager sends the setup packet and looks over the files. If you want to lease on, they review eligibility and the agreement. I don't approve from chat.",
  fee: "Once we know own-MC or lease-on, I can give you the current dispatch fee. What you pay today is useful for onboarding — I just won't match another company's number here.",
  guarantee: "We don't guarantee weekly gross, a set number of loads, or specific lanes paying a rate.",
  fuel: "A fuel card isn't part of the usual setup unless onboarding has a current program.",
  ownMc: "You keep your authority. Our onboarding manager sends the setup packet and looks over the files.",
  lease: "Our onboarding manager reviews lease-on eligibility and the agreement. Asking to lease on isn't approval.",
  docsOwn: "For own-MC, onboarding usually asks for the MC authority sheet, W-9, certificate of insurance, notice of assignment, and a voided check. They'll confirm the list when they send the packet.",
  docsLease: "For lease-on, onboarding usually asks for licence, insurance, medical card, inspection, W-9, and the lease. They'll confirm the list when they review.",
  support: "If you're already running with us, that's operations, not this sales chat. I can note it for them.",
  unknown: "I don't have that answer. I can note it for our onboarding manager instead of guessing.",
};

function lookupKnowledge(topic) {
  return KNOWLEDGE[topic] || null;
}
