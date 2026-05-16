# SAFETYGUIDE

## Inspiration

The Pacific Northwest (PNW) faces a unique combination of significant natural disasters due to its location on the Ring of Fire and varied climate, primarily earthquakes, volcanic eruptions, tsunamis, wildfires, and flooding. The region is especially noted for the threat of a "Cascadia Subduction Zone" megathrust earthquake, which could produce catastrophic damage.
Cloud chatbots fail exactly when disasters happen. Cell towers go down, ISPs lose power, and network congestion melts what's left. A general purpose assistant that needs the internet to answer "what do I do during an earthquake?" is unavailable in the moments that matter most.

This project takes the opposite approach. The whole pipeline — embeddings, vector search, keyword search, reranker, and a 7B-parameter language model — lives on the laptop. As a single isolated application it persists any network outage.

The second non-negotiable point for disaster relief information is grounding. Every answer cites the source chunks it was built from. When the local index doesn't contain enough evidence to answer confidently, the bot refuses rather than guessing. Wrong disaster advice is harmful with a single halluciation having possible life-altering consequences.

## What it does

An offline-first retrieval-augmented chatbot that answers disaster preparedness and response questions from a local knowledge base of vetted sources (Ready.gov, Red Cross, Washington State Emergency Management Division). Everything runs on a single laptop. The chat comes with built in IAAG (Information at a Glance) for nearby emergency local services and infinite scalability for additional tooling.

## How we built it

The app is currently divided into a front and backend for a complete full-stack application. The backend communicates with the frontend through a FastAPI endpoint through a RAG model pipeline. The data has been ingested into blocks for proper citation, with queries being parsed for synonyms and semantical meaning.

## Challenges we ran into

Ultimately building a single application with no API endpoints and end-to-end connection in 6-hours is an insurmountably difficult task. Additionally, finding a model and utilizing it as a RAG agent in the same timeline is also difficult. Due to the constraint of having a locally stored model in use, rather than utilizing an API endpoint of a LLM, we ended up using much more time. This challenge was amplified by the need to query this model and guarantee a formatted response that could be used for a front-end response.

## Accomplishments that we’re proud of

While we weren't able to create an end-to-end completely offline application due to the time constraints, we've successfully created the frameworks to do so. We are extremely proud that we successfully created guardrails for our RAG agent which gated doubtful answers and hallucinations. Therefore, we successfully addressed our first goal. Overall our application is more than capable of addressing disaster relief situations through its robust answering system and scalability through adding additional parsed data.

## What’s next for SafetyGuide.AI

Our goal is to expand this application into mobile devices to make SafetyGuide.AI a highly accessible application. We want to ensure that people have this information at their fingertips no matter where they are. Another feature we'd look to implement is tying together the front and back ends so that the application becomes fully offline, and better outline the necessary steps to run our application.
