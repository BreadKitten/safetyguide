export const STARTER_PROMPTS = [
  "What should I do during an earthquake?",
  "How much water should I store for two weeks?",
  "Is the food in my fridge safe after the power goes out?",
  "When should I evacuate for a wildfire?",
];

export const SAFETY_SCOPE = {
  is: [
    "A calm reference for preparedness and immediate self-protection.",
    "Grounded in Ready.gov, American Red Cross, and WA EMD source documents.",
    "Fully offline when paired with your local backend.",
    "Designed to refuse rather than guess when the local index lacks evidence.",
  ],
  isNot: [
    "A replacement for 911 or local emergency services.",
    "A source of live alerts, shelter availability, or routing.",
    "Medical, legal, or structural-engineering advice.",
  ],
};
