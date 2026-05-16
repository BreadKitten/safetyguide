const DEFAULT_RESPONSE = {
  answer: "",
  citations: [],
  gated: true,
  confidence: 0,
};

export async function askSafetyGuide(query) {
  const endpoint = process.env.NEXT_PUBLIC_SAFETY_GUIDE_ENDPOINT;

  if (!endpoint) {
    return getDevResponse(query);
  }

  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

  if (!response.ok) {
    throw new Error(`SafetyGuide backend returned ${response.status}`);
  }

  return normalizeBackendResponse(await response.json());
}

function normalizeBackendResponse(payload) {
  if (!payload || typeof payload !== "object") {
    return DEFAULT_RESPONSE;
  }

  return {
    answer: typeof payload.answer === "string" ? payload.answer : "",
    citations: Array.isArray(payload.citations) ? payload.citations : [],
    gated: Boolean(payload.gated),
    confidence:
      typeof payload.confidence === "number" ? payload.confidence : undefined,
  };
}

async function getDevResponse(query) {
  await sleep(650 + Math.random() * 450);

  const normalizedQuery = query.toLowerCase();

  if (normalizedQuery.length < 3) {
    return DEFAULT_RESPONSE;
  }

  if (/earthquake|quake|shake/.test(normalizedQuery)) {
    return {
      confidence: 0.92,
      gated: false,
      answer:
        "When shaking begins, drop to your hands and knees before the quake throws you down [1]. This protects you and lets you move if you need to.\n\n" +
        "- Cover your head and neck with one arm. If a sturdy table is within reach, get under it; otherwise move next to an interior wall away from windows [1].\n" +
        "- Hold on to your shelter, or your head and neck, until the shaking stops [2].\n" +
        "- Stay where you are. Most injuries happen when people try to move during shaking [3].\n\n" +
        "After the shaking stops, expect aftershocks. Check yourself for injuries before helping others, and be cautious around broken glass, fallen objects, and damaged structures [2].",
      citations: [
        {
          source: "Ready.gov - Earthquakes",
          page: 1,
          disaster_type: "earthquake",
          text: "Drop, Cover, and Hold On. Drop to your hands and knees so the earthquake does not knock you down. Cover your head and neck with one arm and hand.",
        },
        {
          source: "WA EMD - 2 Weeks Ready",
          page: 7,
          disaster_type: "earthquake",
          text: "Hold on to any sturdy cover until the shaking stops. Be prepared to move with your shelter if it shifts.",
        },
        {
          source: "American Red Cross - Earthquake Safety",
          page: 1,
          disaster_type: "earthquake",
          text: "Most injuries during earthquakes happen when people try to move to a different location inside the building, or try to leave.",
        },
      ],
    };
  }

  if (/water|drink/.test(normalizedQuery)) {
    return {
      confidence: 0.88,
      gated: false,
      answer:
        "Plan for one gallon of water per person per day, for at least two weeks [1]. That covers drinking, basic hygiene, and food preparation.\n\n" +
        "- Store water in food-grade containers in a cool, dark place [2].\n" +
        "- Replace stored water every six months, or use commercially sealed bottled water and follow the printed date [1].\n" +
        "- Include extra water for pets, for anyone who is pregnant or ill, and for hot weather [1].",
      citations: [
        {
          source: "WA EMD - 2 Weeks Ready",
          page: 4,
          disaster_type: "general",
          text: "Store at least one gallon of water per person per day for two weeks for drinking and sanitation.",
        },
        {
          source: "Ready.gov - Build a Kit",
          page: 1,
          disaster_type: "general",
          text: "Keep water in a cool, dark place. Replace stored water every six months.",
        },
      ],
    };
  }

  if (/fridge|food|power|outage/.test(normalizedQuery)) {
    return {
      confidence: 0.81,
      gated: false,
      answer:
        "Keep refrigerator and freezer doors closed as much as possible during a power outage [1]. A closed refrigerator keeps food cold for about four hours; a full freezer holds its temperature for about 48 hours, or 24 hours if half full [1].\n\n" +
        "- Discard perishable food that has been above 40 degrees F for two hours or more [2].\n" +
        "- When in doubt, throw it out. Never taste food to decide if it is safe [2].",
      citations: [
        {
          source: "Ready.gov - Food Safety During Power Outage",
          page: 1,
          disaster_type: "outage",
          text: "Keep the refrigerator and freezer doors closed. The refrigerator will keep food cold for about 4 hours if unopened.",
        },
        {
          source: "American Red Cross - Food Safety",
          page: 1,
          disaster_type: "outage",
          text: "Throw out perishable food that has been above 40 degrees F for two hours or more. When in doubt, throw it out.",
        },
      ],
    };
  }

  return DEFAULT_RESPONSE;
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
