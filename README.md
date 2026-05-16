# Disaster Relief RAG Chatbot

An offline-first retrieval-augmented chatbot that answers disaster preparedness and response questions from a local knowledge base of vetted sources (Ready.gov, Red Cross, Washington State Emergency Management Division).

Everything runs on a single laptop. No cloud, no API calls, nothing phones home.

---

## Why this exists

Cloud chatbots fail exactly when disasters happen. Cell towers go down, ISPs lose power, congestion melts what's left of the network. A general-purpose assistant that needs the internet to answer "what do I do during an earthquake?" is unavailable in the moments that matter most.

This project takes the opposite approach. The whole pipeline — embeddings, vector search, keyword search, reranker, and a 7B-parameter language model — lives on the laptop. With wifi off, it still works.

The second non-negotiable is grounding. Every answer cites the source chunks it was built from. When the local index doesn't contain enough evidence to answer confidently, the bot refuses rather than guessing. Wrong disaster advice is harmful — refusal is a feature, not a bug.

---

## How it works

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

Four moving parts, in order:

1. **Ingestion** turns raw PDFs and scraped text into a row-aligned set of three indexes: a FAISS vector index, a BM25 keyword index, and a JSON file of chunk text plus metadata.
2. **Retrieval** runs the user's query through both indexes in parallel and fuses the two ranked lists. A cross-encoder reranks the fused candidates and keeps the top four.
3. **The confidence gate** checks the cross-encoder's top score. If it's below a calibrated threshold, the bot returns a fixed "I could not find reliable information…" sentence and stops. The LLM is never invoked on low-confidence retrievals.
4. **Generation** sends the top four chunks plus the question to a local Qwen2.5-7B-Instruct model, which writes a short cited answer. Every factual claim gets a `[n]` marker pointing back to the chunk it came from.

---

## Stack

- **LLM:** Qwen2.5-7B-Instruct, Q4_K_M GGUF quantization, served via `llama-cpp-python` (Metal-accelerated on Apple Silicon).
- **Embeddings:** `BAAI/bge-small-en-v1.5` (384-d) via `sentence-transformers`.
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder.
- **Vector store:** FAISS (`IndexFlatIP` over L2-normalized vectors, so inner product equals cosine similarity).
- **Keyword search:** `rank_bm25`.
- **UI:** Gradio — in progress, see [Roadmap](#roadmap).
- **Language:** Python 3.10+.

No Docker. No external services. No silent network calls.

---

## Repository layout

```
.
├── data/
│   ├── raw/             # Original PDFs and scraped HTML/text from each source
│   └── processed/       # Cleaned text + hand-curated Markdown sidecars
├── index/               # Built artifacts: FAISS, BM25, chunks.json
├── models/              # Local Qwen GGUF weights (you download these)
├── scripts/             # Stdlib-only cleaners for the raw corpora
├── src/                 # The pipeline: ingest → retrieve → query → pipeline → generate → app
├── tests/               # Inspection-style test scripts (not pytest)
└── requirements.txt
```

The three files in `index/` (`faiss.index`, `bm25.pkl`, `chunks.json`) are row-aligned. The Nth row in `chunks.json` corresponds to the Nth vector in FAISS and the Nth document in BM25. The retriever depends on this invariant; do not edit any of them by hand.

---

## Getting started

### Prerequisites

- macOS or Linux. Apple Silicon (M1/M2/M3/M4) is the recommended development platform — `llama-cpp-python` builds against Metal for ~3× faster generation than CPU.
- Python 3.10–3.13.
- About 10 GB of free disk space (model weights are ~4.4 GB; embedding and reranker downloads add another ~600 MB on first use).
- The **first-time setup requires internet** to download model weights. After that, the entire pipeline runs offline.

### 1. Clone and install Python dependencies

```bash
git clone <repo-url>
cd "Disaster Relief Chatbot"

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Install `llama-cpp-python` separately

The LLM runtime needs a custom build flag on Apple Silicon to enable Metal acceleration:

```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --no-cache-dir
```

On Linux or any non-Mac system, drop the `CMAKE_ARGS` prefix — pip will compile a CPU-only build:

```bash
pip install llama-cpp-python --no-cache-dir
```

### 3. Download the LLM weights

Search Hugging Face for **Qwen2.5-7B-Instruct-GGUF** and download the **Q4_K_M** quantization. It ships as a 2-shard split:

```
qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf   (~3.7 GB)
qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf   (~0.6 GB)
```

Drop both files in `models/`. `llama-cpp-python` auto-loads the second shard from the first shard's path, so the pipeline only references shard 1.

The sentence-transformer embedding and reranker models download themselves on first ingest — no manual step required.

### 4. Build the index

```bash
# Optional: re-run the cleaners if you changed anything in data/raw/
python -m scripts.clean_ready_gov
python -m scripts.clean_red_cross
python -m scripts.clean_wa_emd

# Build the FAISS + BM25 + chunks.json indexes
python -m src.ingest
```

Ingestion takes about one to two minutes on Apple Silicon. The output lands in `index/`.

### 5. Ask a question

Until the Gradio UI is wired up, the CLI is how you talk to the bot end-to-end:

```bash
python -m src.generate "what should I do during an earthquake"
```

You can also exercise individual pipeline stages, which is useful for debugging:

```bash
# Retrieval only — prints the top hits with cross-encoder scores
python -m src.retrieve "what should I do during an earthquake"

# Query parser only — prints the rewritten query and detected disaster_type
python -m src.query "what do i do if a earth quake hit"

# Parse → retrieve, no generation
python -m src.pipeline "fridge food after power goes out"
```

> **Heads up:** `python -m src.app` does **not** work yet. The Gradio UI is the last unfinished piece — see [Roadmap](#roadmap).

---

## Design decisions and trade-offs

Most of the interesting work on this project was deciding what *not* to do. Here are the calls that shaped the current pipeline.

**1. Hybrid retrieval with Reciprocal Rank Fusion, not a weighted blend.**
Dense embeddings catch paraphrases ("food spoilage" → "refrigerator contents after outage"). BM25 catches rare or proper-noun terms that embeddings dilute ("Cascadia," "ShakeOut," specific WA agency names). Combining the two with RRF needs no hand-tuned 60/40 split — it ranks purely on position in each list and stays stable as the corpus grows.

**2. Confidence gating is non-negotiable.**
After reranking, the top hit's cross-encoder score must clear a threshold of 0.1 (sigmoid-normalized) or the bot refuses. We measured this empirically: relevant hits on this corpus score 0.85–0.99 at the top, while off-topic or garbage queries bottom out near 0.0001. A threshold of 0.1 sits comfortably above the noise floor without rejecting legitimate questions. When the gate trips, the LLM is never invoked — the bot returns the fixed "I could not find reliable information in the local emergency knowledge base" sentence verbatim. This is the single most important guardrail against hallucinated disaster advice.

**3. Section-aware chunking with a 300-token budget and 30-token overlap.**
Chunks any larger than ~350 tokens degrade the 7B model's ability to attend to all of them at once, and they make citations less precise. Smaller chunks keep the cross-encoder honest. Before token-splitting, we segment text on detected headings (Markdown `#`, numbered headings, short title-case standalone lines) so brochure list items stay attached to their parent section. Tiny sections under 80 tokens fold into neighbors so embeddings always have enough context.

**4. Column-aware PDF extraction with manual sidecars as a backstop.**
Multi-column brochures from Ready.gov and WA EMD interleave column text into word salad if you extract them naively. We built a gutter-detecting extractor that finds vertical whitespace stripes in each page and emits each column top-to-bottom. For poster-style PDFs that no algorithm reliably handles (overlapping text layers, scenario callouts, hand-drawn layouts), we maintain hand-curated Markdown sidecars in `data/processed/manual_pdfs/`. When a sidecar exists, the matching PDF is skipped; sidecar chunks keep author-chosen boundaries verbatim.

**5. Safety-first reordering before generation.**
The cross-encoder ranks for *topical* relevance, not *life-safety* urgency. A query about earthquakes might rank a general preparedness brochure above an actual "drop, cover, and hold on" warning. Before prompting the LLM, we stable-sort the top hits by a safety score — a count of imperative and warning phrases like `"drop, cover"`, `"evacuate"`, `"turn around"`, `"9-1-1"`. Warning-heavy chunks land at positions `[1]` and `[2]`, so the LLM's primacy bias works in our favor even if the answer gets truncated.

**6. Two-stage query parsing.**
The LLM normalizes spelling and picks a `disaster_type` from a fixed set of tags ("earthquake", "wildfire", "flood", …). A hand-maintained synonym table handles colloquial mappings ("twister" → "tornado") that we don't trust the LLM to get right. Critically, the LLM is **forbidden** from expanding domain vocabulary in the rewritten query. If we let it inject "drop, cover, and hold on" into the rewrite, it could smuggle its own pretraining advice past the grounded-RAG gate by steering retrieval. The synonym table is the only place where vocabulary gets expanded, and it's pinned in source.

### Trade-offs at a glance

| Decision | Why | What we gave up |
|---|---|---|
| RRF over weighted hybrid blend | Tuning-free; stable as corpus grows | Marginal precision a tuned blend might offer on a fixed corpus |
| 300-token chunks (not 500–800) | Precision at retrieval; cleaner citations on a 7B model | Some cross-chunk context that the reranker has to reassemble |
| `CONF_THRESHOLD = 0.1` (refuse below) | Hallucinated disaster advice is harmful — refusal beats wrong | Some recall on borderline queries (rephrasing usually helps) |
| Safety-first reorder after rerank | LLM primacy bias should serve life-safety, not topicality | A pure topical ordering of citations |
| Disaster `phase` field removed | Before/during/recovery prose is too ambiguous to classify reliably | Granular phase filtering in the UI (we may revisit) |

---

## Challenges we hit (and what we learned)

These are the rough edges that shaped the current code. They're documented here so future contributors don't re-walk the same paths.

### Multi-column PDFs produced word salad

Ready.gov brochures and WA EMD documents have sidebars and callouts interleaved with body text. A naive PDF extract turned `"You can survive"` next to a sidebar header into `"You can / Additional Resources / survive"`. The fix is the column-aware extractor in `_extract_page_text` — it builds a horizontal occupancy bitmap per page, finds empty vertical stripes (gutters), and emits each column top-to-bottom. Three poster-style PDFs were unsalvageable by any algorithm we tried; those have hand-curated Markdown sidecars in `data/processed/manual_pdfs/` instead.

### The phase classifier got ripped out

We initially planned a `phase` metadata field ("before", "during", "recovery") to let users filter the bot's answers by where they are in a disaster. After building and testing it, we found the same vocabulary narrates all three phases in real source text — "stay indoors," "check on neighbors," "have a kit" all appear in before, during, and after sections. Keyword-based phase tagging mislabeled enough chunks that we removed the feature end-to-end. "Disaster Mode" now relies on `disaster_type` only. We may revisit phase filtering with a better signal, but not for this version.

### The cross-encoder threshold was miscalibrated at first

We initially set `CONF_THRESHOLD = 0.0`, expecting reranker logits in the rough `[-10, +10]` range you see from some cross-encoders. In practice, `bge-reranker-base` emits sigmoid-normalized scores in `[0, 1]`. At threshold 0, gibberish queries scoring `0.0001` still passed the gate and produced hallucinated answers. We logged scores across the test set, saw legitimate hits at 0.85–0.99 and noise near 0.0001, and raised the threshold to 0.1. Lesson: always inspect the empirical distribution of your gating signal before picking a threshold.

### Citation contamination in answers

The system prompt has two cases: if there's relevant context, cite it; if there isn't, emit the fixed "I could not find reliable information…" sentence verbatim. Qwen2.5-7B occasionally violated this by emitting **both** — citing real chunks *and* hedging with the canned refusal in the same answer. The fix was twofold. First, we split the system-prompt rule explicitly into "no context → canned phrase only" and "context → cite, never use the canned phrase." Second, we added a defensive post-process: if the answer contains both `[n]` markers and the canned phrase, strip the canned phrase. The strip is a no-op when the model behaves; it only fires on contradictions.

### Disaster-type tagging by content keywords mislabeled brochures

Our first tagger looked at chunk *content* — if "earthquake" appeared in the text, the chunk was tagged `earthquake`. This labeled multi-hazard preparedness brochures as earthquake-specific the moment they mentioned earthquakes as one of several risks. Filtering by `disaster_type=earthquake` then surfaced general prep advice instead of earthquake-specific guidance. We replaced this with filename-driven defaults (the per-corpus slug maps in `src/ingest.py`) and a tight list of override phrases like `"drop, cover, and hold on"` and `"great washington shakeout"` that promote specific chunks from `general` to a hazard tag. The override list is intentionally narrow.

---

## Scripts and tests

### Scripts (`scripts/`)

| Script | What it does |
|---|---|
| [`clean_ready_gov.py`](scripts/clean_ready_gov.py) | Cleans scraped Ready.gov text in `data/raw/ready_gov/` and writes the result to `data/processed/ready_gov/`. Strips trailing resource-link blocks and normalizes whitespace. |
| [`clean_red_cross.py`](scripts/clean_red_cross.py) | Same idea for Red Cross reader-mode scrapes. Strips URLs, header noise, and Markdown link syntax while keeping body content intact. |
| [`clean_wa_emd.py`](scripts/clean_wa_emd.py) | Same idea for the WA Emergency Management Division. Handles the WA EMD 4-line header format and selectively strips decorative link markers while preserving instructional image alt-text. |

All three scripts are stdlib-only and idempotent — they rebuild their output directory fresh on each run, so re-running is always safe.

### Tests (`tests/`)

All three test scripts are **inspection-style, not pytest**. They print what they see, raise `AssertionError` on hard failures, and surface softer issues as `WARN`. Run them directly with `python -m tests.<name>`; do not reach for pytest.

| Test | What it validates | When to run |
|---|---|---|
| [`test_chunking.py`](tests/test_chunking.py) | Chunk token-length distribution, absence of mid-word splits, survival of critical disaster phrases (e.g. `"drop, cover, and hold on"`), per-source metadata variety, and overall source coverage. | After re-running `python -m src.ingest`. |
| [`test_query.py`](tests/test_query.py) | Query-parser output schema, disaster-type tagging accuracy (≥70% on 12 fixtures), determinism at temperature 0, and the failure contract (any LLM or JSON error must return the original text with `disaster_type=None`). Loads the LLM once; ~1 minute on Apple Silicon. | After editing `src/query.py`, its system prompt, or its few-shots. |
| [`test_generate.py`](tests/test_generate.py) | Pure-unit pass (no LLM, under 2 seconds) covers safety-first reordering, citation-marker regex, numbered-context prompt assembly, the gating contract, and graceful degradation when the LLM raises. The `--with-llm` flag adds end-to-end checks: citations present on in-corpus queries, refusal on off-topic queries, determinism. | After editing `src/generate.py` (default pass) or its prompt (`--with-llm` pass). |

---

## Roadmap

- **Wire `src/app.py`.** This is the last unfinished module. The Gradio UI should call `src.generate.answer(query)` — a single end-to-end entry point that runs parse → retrieve → generate and returns a cited answer plus the citation list.
- **Decide the Disaster Mode UX.** Two reasonable options: a dropdown the user selects before asking, or letting the query parser auto-detect from the question text. The parser already produces a `disaster_type`; the question is whether to surface it as a UI affordance.
- **Add a fixed "call 911" banner** in the UI for life-threatening scenarios — the bot is preparedness guidance, not a substitute for emergency services.
- **Expand the corpus** with additional PNW-specific sources (Cascadia subduction zone material, more WA State EMD content).

---

## Conventions for contributors

- Use `pathlib.Path`, not string paths.
- Type-hint public functions.
- Every `src/` module should stay runnable as a script (`python -m src.<name>`) for fast debugging. This is how we test changes in isolation before touching the full pipeline.
- No new dependencies that need a network connection at runtime. Hugging Face downloads must be cached locally before any offline demo.
- Comments explain *why*, not *what*. The reference style lives in [`src/retrieve.py`](src/retrieve.py) and [`src/ingest.py`](src/ingest.py): module docstrings cover algorithmic choices and invariants, section dividers group related code, and inline comments are reserved for genuinely surprising lines.
