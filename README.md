# SafetyGuide.AI

Everybody Hacks 2026 — Disaster Response Track

## Demo

Watch the demo on YouTube: **[SafetyGuide.AI walkthrough](https://youtu.be/UMFcAi7lDxU)**

[![SafetyGuide demo video](docs/screenshots/chatbot.png)](https://youtu.be/UMFcAi7lDxU)

The demo shows two queries: *"What can I do against a volcano eruption?"* gets a cited answer from the local knowledge base, and *"Who won the FIFA World Cup?"* gets correctly refused — the confidence gate fires because nothing in the index covers it. It also shows the interactive PNW resource map.

**Slide deck:** [SafetyGuide.AI on Canva](https://canva.link/dbib27r46a93nfv) — covers the motivation, architecture, guardrails, and roadmap.

---

![Interactive PNW resource map](docs/screenshots/map.png)
*The interactive Pacific Northwest resource map — nearby emergency services, shelters, and response infrastructure at a glance.*

---

## Inspiration

The Pacific Northwest sits on the Ring of Fire. Earthquakes, volcanic eruptions, tsunamis, wildfires, flooding — and a Cascadia Subduction Zone megathrust event that scientists say is overdue. People here have real reasons to want reliable disaster information.

The problem is that cloud chatbots fail exactly when disasters happen. Cell towers go down, ISPs lose power, and whatever's left of the network gets congested. An assistant that needs the internet to answer "what do I do during an earthquake?" is unavailable in the moments that matter most.

We built SafetyGuide.AI to take the opposite approach. The entire pipeline — embeddings, vector search, keyword search, a cross-encoder reranker, and a 7B language model — runs on a single laptop. With wifi off, it still works.

The second thing we cared about was grounding. Every answer cites the source chunks it was built from, and when the index doesn't have enough evidence to answer confidently, the bot refuses instead of guessing. Wrong disaster advice is harmful, so refusal is a feature.

---

## What it does

SafetyGuide.AI is an offline-first RAG chatbot that answers disaster preparedness and response questions from a local knowledge base of vetted sources (Ready.gov, Red Cross, Washington State Emergency Management Division). Everything runs on a single laptop — no cloud, no API calls, nothing phones home.

It also ships with an interactive map of Pacific Northwest emergency resources (shelters, fire stations, hospitals) for "information at a glance" about services near you.

---

## How we built it

The project is split into a Python backend and a Next.js frontend, connected through a local FastAPI endpoint.

**Backend pipeline** ([`server/src/`](server/src/)) — five stages wired together:

1. **Ingestion** ([`ingest.py`](server/src/ingest.py)) — loads PDFs and text scrapes, chunks them at 300 tokens with 30-token overlap and heading-aware splitting, and builds a row-aligned FAISS + BM25 + JSON index.
2. **Retrieval** ([`retrieve.py`](server/src/retrieve.py)) — runs semantic search (FAISS, top 15) and keyword search (BM25, top 15) in parallel, merges the results with Reciprocal Rank Fusion, and reranks the pool with a `bge-reranker-base` cross-encoder down to the top 4 hits.
3. **Query parsing** ([`query.py`](server/src/query.py)) — Qwen2.5-7B normalizes the user's spelling and tags a `disaster_type`, but is explicitly forbidden from injecting safety vocabulary (more on why in Challenges).
4. **Orchestration** ([`pipeline.py`](server/src/pipeline.py)) — thin glue layer: parse → retrieve, nothing else.
5. **Generation** ([`generate.py`](server/src/generate.py)) — reorders chunks by safety priority, prompts Qwen2.5-7B to produce a cited answer, and strips any answer that violates the citation rules.

**HTTP shim** — [`app.py`](server/src/app.py) is a FastAPI server wrapping the pipeline end-to-end. It binds only to `127.0.0.1`.

**Frontend** — Next.js 16 (App Router) + React 19 + Tailwind v4 in [`client/sg-client/`](client/sg-client/). The browser talks to a server-side route handler at [`app/api/chat/route.js`](client/sg-client/app/api/chat/route.js), which proxies to FastAPI.

**Models** — Qwen2.5-7B-Instruct (Q4_K_M GGUF) via `llama-cpp-python` with Metal GPU acceleration; `BAAI/bge-small-en-v1.5` for 384-d embeddings; `BAAI/bge-reranker-base` as the cross-encoder reranker. The 7B model is loaded once and shared between query parsing and generation — loading it twice would OOM the laptop.

```
Documents → Chunking → Embeddings → FAISS Index
                                         ↓
User Query → Query Rewrite (LLM) → ┬─ Semantic retrieval (top 15)
                                   └─ BM25 retrieval (top 15)
                                         ↓
                                   Reciprocal Rank Fusion
                                         ↓
                                   Cross-encoder rerank → Top 4
                                         ↓
                                   Confidence gate (refuse or proceed)
                                         ↓
                                   Qwen2.5-7B → Answer with citations
```

---

## Challenges we ran into

**Building a fully offline pipeline in 6 hours.** Wiring RAG + a Next.js client in a single hackathon window was a lot. Using a local GGUF model instead of an API endpoint costs real setup time (4.7 GB of weights, Metal configuration) before you can even start iterating on the prompt.

**Multi-column PDFs produced word salad.** Ready.gov brochures have sidebars interleaved with body text. A naive extract turned "You can survive" next to a sidebar header into "You can / Additional Resources / survive." The fix is a column-aware extractor in `_extract_page_text` that builds a horizontal occupancy bitmap per page, finds the empty vertical gutters, and emits each column top-to-bottom. Three poster-style PDFs were unsalvageable algorithmically; those have hand-curated Markdown sidecars in [`server/data/processed/manual_pdfs/`](server/data/processed/manual_pdfs/) instead.

**The confidence threshold was miscalibrated.** We set `CONF_THRESHOLD = 0.0` expecting logits in `[-10, +10]`. Turns out `bge-reranker-base` emits sigmoid-normalized scores in `[0, 1]`. At threshold 0, gibberish queries scoring `0.0001` still passed and produced hallucinated answers. We logged scores across the test set, saw real hits at `0.85–0.99` and noise near `0.0001`, and raised the threshold to `0.1`.

**Citation contamination.** Qwen2.5-7B kept citing real chunks and hedging with the canned refusal phrase in the same answer. We split the prompt rule into two explicit cases — "no context → canned phrase only" and "context → cite, never use the canned phrase" — and added a defensive post-process that strips the canned phrase whenever an answer also has `[n]` markers.

**Disaster-type tagging by content keyword mislabeled brochures.** Tagging any chunk that mentioned "earthquake" as `earthquake` caused multi-hazard prep brochures to get mislabeled the moment they mentioned earthquakes as one of several risks. We replaced this with filename-driven defaults and a tight allowlist of override phrases like "drop, cover, and hold on" that promote individual chunks from `general` into a specific hazard.

**We explicitly forbid the query parser from expanding vocabulary.** If the LLM rewrites "shaky ground" to "drop, cover, and hold on", it smuggles its pretraining knowledge past the grounded-RAG gate by steering retrieval toward what it already believes rather than what the index contains. A hand-maintained synonym table (`_SYNONYMS` in `query.py`) handles colloquial-to-canonical mapping instead.

**Switching to the 3B model didn't help latency.** We benchmarked Qwen2.5-3B-Instruct Q4_K_M as a drop-in:

| Model | Warmup | Steady-state avg | Min / Max |
|-------|--------|------------------|-----------|
| 3B Q4_K_M | 10.38 s | 6.36 s | 3.37 s / 10.48 s |
| 7B Q4_K_M | 9.90 s | 6.32 s | 3.20 s / 10.49 s |

Statistically identical. With `n_gpu_layers=-1` both models are fully Metal-offloaded, so wall-clock latency is dominated by output token count (~200–350 tokens per answer), not parameter count. The per-token speed advantage of 3B exists but is swamped by answer-length variance. We stayed on 7B.

---

## Accomplishments we're proud of

The confidence gate actually works. The demo's "Who won the FIFA World Cup?" refusal isn't hand-coded — the gate fires because no chunk in the index covers that question, and the LLM is never invoked. Every claim in an answer is traceable back to a specific source chunk, enforced by the system prompt, a one-shot retry, and a post-process.

The safety-first chunk reordering is a small idea with real impact. The cross-encoder ranks for topical relevance, not life-safety priority. A stable-sort by a count of imperative/warning phrases before prompting means truncated answers still lead with the warning — exploiting LLM primacy bias for something useful.

We also shipped not just the RAG pipeline but a full Next.js client, interactive resource map, FastAPI shim, and three inspection-style test suites — all in the hackathon window.

---

## What we learned

Log the empirical distribution of your gating signal before you pick a threshold. Our `CONF_THRESHOLD` story is the textbook example: we set `0.0` based on what we expected the reranker to emit, and it took an evening of logging to discover the actual range was sigmoid-normalized `[0, 1]`.

Small, section-aware chunks beat large ones for 7B-class models. 300 tokens with 30-token overlap and heading-aware splitting produced visibly better citations than the 500–800 token chunks we started with.

Don't use LangChain. Direct library calls (sentence-transformers, FAISS, rank-bm25, llama-cpp-python) are dramatically easier to debug under time pressure. Every minute we didn't spend chasing a framework version mismatch was a minute we spent improving retrieval.

A clean refusal is better than a hedge. "I could not find reliable information in the local emergency knowledge base" built more user trust than "I'm not sure, but…" When you're uncertain, say so clearly.

---

## What's next for SafetyGuide.AI

The biggest thing we want to do is get this onto mobile. An offline RAG pipeline running on a phone would make this genuinely accessible to people evacuating without laptop access.

Beyond that:
- **"Call 911" banner** in the UI — the bot is preparedness guidance, not a substitute for emergency services.
- **Expand the corpus** — more Cascadia subduction zone material, additional WA EMD content, and eventually support for regions outside the PNW.
- **Disaster Mode UX** — the query parser already tags a `disaster_type`; we need to decide whether to surface it as a UI dropdown or rely purely on auto-detection.
- **Single-app packaging** — bundle the Next.js client and FastAPI server into one launchable artifact so the setup experience is less painful.
- **Automated corpus refresh** — a scripted way to re-pull authoritative sources and rebuild the index.

---

## Stack

- **LLM:** Qwen2.5-7B-Instruct, Q4_K_M GGUF, via `llama-cpp-python` (Metal-accelerated on Apple Silicon)
- **Embeddings:** `BAAI/bge-small-en-v1.5` (384-d) via `sentence-transformers`
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder
- **Vector store:** FAISS (`IndexFlatIP` over L2-normalized vectors — inner product equals cosine similarity)
- **Keyword search:** `rank_bm25`
- **Backend:** Python 3.10+ with FastAPI + Uvicorn ([`server/src/app.py`](server/src/app.py))
- **Frontend:** Next.js 16 (App Router) + React 19 + Tailwind v4 ([`client/sg-client/`](client/sg-client/))

No Docker. No external services. No network calls.

---

## Repository layout

```
.
├── server/
│   ├── data/
│   │   ├── raw/                  # Source PDFs and raw scrapes
│   │   └── processed/
│   │       ├── ready_gov/        # Cleaned Ready.gov text
│   │       ├── red_cross/        # Cleaned Red Cross text
│   │       ├── wa_emd/           # Cleaned WA EMD text
│   │       └── manual_pdfs/      # Hand-curated Markdown sidecars for poor-OCR PDFs
│   ├── index/                    # Built artifacts: faiss.index, bm25.pkl, chunks.json
│   ├── models/                   # Local Qwen GGUF weights (gitignored)
│   ├── scripts/                  # Corpus cleaners
│   ├── src/                      # ingest → retrieve → query → pipeline → generate → app
│   ├── tests/                    # Inspection-style test scripts
│   └── requirements.txt
├── client/
│   └── sg-client/                # Next.js 16 frontend
│       ├── app/
│       │   └── api/chat/route.js # Server-side proxy to FastAPI
│       └── package.json
├── docs/screenshots/
├── CLAUDE.md
└── README.md
```

The three files in `server/index/` (`faiss.index`, `bm25.pkl`, `chunks.json`) are row-aligned — the Nth entry in each corresponds to the same chunk. Don't edit them by hand.

---

## Getting started

### Prerequisites

- macOS or Linux. Apple Silicon is the recommended platform — `llama-cpp-python` builds against Metal for ~3× faster generation than CPU.
- Python 3.10–3.13.
- Node.js 20+ and npm.
- ~10 GB of free disk space (Qwen weights are ~4.4 GB; embedding and reranker models add ~600 MB on first use).
- **First-time setup needs internet** to download model weights. After that, everything runs offline.

### 1. Clone and install Python dependencies

```bash
git clone https://github.com/AdiKum26/safetyguide.git
cd safetyguide

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r server/requirements.txt
```

### 2. Install `llama-cpp-python`

On Apple Silicon:

```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --no-cache-dir
```

On Linux / non-Mac:

```bash
pip install llama-cpp-python --no-cache-dir
```

### 3. Download the LLM weights

Search Hugging Face for **Qwen2.5-7B-Instruct-GGUF** and download the **Q4_K_M** quantization — it ships as two shards:

```
qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf   (~3.7 GB)
qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf   (~0.6 GB)
```

Drop both into `server/models/`. `llama-cpp-python` auto-loads shard 2 from shard 1's path; the pipeline only references shard 1. The embedding and reranker models download themselves on first ingest.

### 4. Build the index

```bash
# Optional: re-run cleaners if you've changed server/data/raw/
PYTHONPATH=server python -m server.scripts.clean_ready_gov
PYTHONPATH=server python -m server.scripts.clean_red_cross
PYTHONPATH=server python -m server.scripts.clean_wa_emd

# Build the FAISS + BM25 + chunks.json indexes (~1-2 min on Apple Silicon)
PYTHONPATH=server python -m server.src.ingest
```

### 5. Run the app

Backend (one shell):

```bash
PYTHONPATH=server uvicorn src.app:app --host 127.0.0.1 --port 8000
```

Frontend (another shell):

```bash
cd client/sg-client
npm install   # first time only
npm run dev
```

Open the URL the dev server prints (usually `http://localhost:3000`).

### CLI shortcuts

```bash
# Retrieval only — top hits with cross-encoder scores
PYTHONPATH=server python -m server.src.retrieve "what should I do during an earthquake"

# Query parser only — rewritten query and detected disaster_type
PYTHONPATH=server python -m server.src.query "what do i do if a earth quake hit"

# Parse → retrieve, no generation
PYTHONPATH=server python -m server.src.pipeline "fridge food after power goes out"

# Full pipeline — cited answer, ~5-10 s
PYTHONPATH=server python -m server.src.generate "what do I do during an earthquake"
```

---

## Tests

All three test suites are inspection-style, not pytest — they print what they see, raise `AssertionError` on hard failures, and surface softer issues as `WARN`.

| Test | What it checks | When to run |
|---|---|---|
| [`test_chunking.py`](server/tests/test_chunking.py) | Token-length distribution, no mid-word splits, critical disaster phrases survive, source coverage | After re-ingesting |
| [`test_query.py`](server/tests/test_query.py) | Parser output schema, disaster-type tagging accuracy (≥70% on 12 fixtures), failure contract. Loads the LLM, ~1 min. | After editing `query.py` or its prompt |
| [`test_generate.py`](server/tests/test_generate.py) | Safety reordering, citation regex, gating contract, graceful LLM-error degradation. `--with-llm` adds end-to-end checks. | After editing `generate.py` |

```bash
PYTHONPATH=server python -m server.tests.test_chunking
PYTHONPATH=server python -m server.tests.test_query
PYTHONPATH=server python -m server.tests.test_generate
PYTHONPATH=server python -m server.tests.test_generate --with-llm
```

---

## Retrieval evaluation

[`test_retrieve.py`](server/tests/test_retrieve.py) evaluates the retrieval pipeline against a hand-annotated gold standard of 31 queries: 28 in-corpus queries covering 13 disaster types, and 3 off-corpus queries that must trigger the confidence gate.

```bash
PYTHONPATH=server python -m server.tests.test_retrieve
```

**Pre-rerank** (FAISS + BM25 + RRF, 15-candidate pool):
- **R@15** — fraction of relevant chunks that appear before the cross-encoder runs. This is the ceiling: anything missed here can never reach the LLM.
- **P@15** — fraction of the 15 candidates that are relevant. Low by design since the pool is intentionally wide.

**Post-rerank** (cross-encoder top-4):
- **MRR** — Mean Reciprocal Rank (`1 / rank` of the first relevant hit). The primary quality metric. The LLM is most influenced by whatever lands at rank 1, so getting the right chunk there is what drives answer quality.

**Results on the current index** (170 chunks, 25 disaster types):

| Stage | Metric | Value |
| :--- | :--- | :--- |
| Pre-rerank | P@15 | 0.320 |
| Pre-rerank | R@15 | 0.836 |
| Post-rerank | MRR | 0.911 |

R@15 = 0.836 means the FAISS + BM25 + RRF stage surfaces 84% of relevant chunks before reranking. The 16% miss rate is concentrated in disaster types with thin coverage (tornado, flood) — a content problem, not an algorithm problem.

- **R@15 = 0.836** — The FAISS + BM25 + RRF stage surfaces 84% of all relevant chunks before the cross-encoder runs. The 16% miss rate is concentrated in disaster types with thin corpus coverage (tornado, flood) where only 3 chunks exist, making any single miss a large percentage hit. This is a content-coverage problem, not a retrieval algorithm problem.
- **MRR = 0.911** — On 25 of 27 queries that were not gated, the very first returned chunk is a relevant one. The cross-encoder is reliably placing the best chunk at rank 1 in the LLM prompt.
- **Off-corpus gating** — All 3 off-corpus queries (sports trivia, restaurant recommendation, stock market) gate correctly with cross-encoder scores in the range `[0.0001, 0.0044]`, well below the `CONF_THRESHOLD = 0.1`. Legitimate in-corpus queries score `0.74–0.9997`. The gap between noise-floor and real matches is large enough that the gate is not at risk of false positives.

---

## Conventions for contributors

- Use `pathlib.Path`, not string paths.
- Type-hint public functions.
- Every `server/src/` module stays runnable as a script (`PYTHONPATH=server python -m server.src.<name>`) for fast iteration in isolation.
- No new dependencies that need a network connection at runtime. Hugging Face downloads must be cached locally before any offline demo.
- Comments explain *why*, not *what*. The reference style lives in [`server/src/retrieve.py`](server/src/retrieve.py) and [`server/src/ingest.py`](server/src/ingest.py).
