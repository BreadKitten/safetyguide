"""LLM-driven query parser for the disaster-relief RAG pipeline.

Sits between the raw user input and `src.retrieve`. Two jobs:

  1. **Normalize**: a Qwen2.5-7B chat call lightly fixes spelling/phrasing
     and picks a `disaster_type` tag from a fixed allowed set. The prompt
     forbids the model from adding domain vocabulary the user didn't write
     -- in particular, no safety-advice expansion. This is deliberate. If
     the LLM were free to expand "what to do in an earthquake" into "drop
     cover and hold on" via its pretraining, it would smuggle its own
     (possibly outdated) advice past the grounded-RAG gate by influencing
     which chunks get retrieved.

  2. **Synonym back-fill** (in this module, NOT in the LLM): a small,
     hand-maintained `_SYNONYMS` table maps colloquial terms ("twister",
     "quake") to canonical hazard names. We use it for two narrow steps
     that the LLM never participates in:

       a. *Rules fallback for disaster_type.* If Qwen returns
          `disaster_type=null` but the text contains a known synonym,
          set the type to the mapped canonical.
       b. *Canonical-word back-fill.* Once `disaster_type` is set, append
          the canonical hazard word to the rewritten query if it isn't
          already there -- BM25 is a bag-of-words retriever and won't
          match "twister" against "tornado" chunks without the token.

     The table lives in source. The model can never extend it at runtime.

The `_LLM` singleton loaded here is the same object `src.generate` will
reuse for answer synthesis, so the ~1.9 GB Q4_K_M GGUF is loaded once per
process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from server.src.ingest import INDEX_DIR

# --- tuning knobs ------------------------------------------------------------
# MODEL_PATH: Q4_K_M GGUF of Qwen2.5-7B-Instruct (~4.7 GB, 2-shard split).
# llama-cpp-python auto-loads shard 2 from the first shard's path.
# N_CTX: 2048 is comfortably more than the system prompt + few-shots + a
# single user query. Parsing doesn't need a long context.
# N_GPU_LAYERS=-1: offload every layer to Metal on Apple Silicon. The
# llama-cpp-python build instructions in requirements.txt enable this.
# SEED + TEMPERATURE=0: parsing is a deterministic structured-output task;
# we want byte-identical rewrites across reruns so the tests are stable.
# MAX_TOKENS=96: our JSON object is ~30 tokens. 96 leaves headroom for a
# verbose normalization without letting the model ramble.
MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "models" / "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
)
N_CTX = 2048
N_GPU_LAYERS = -1
SEED = 0
TEMPERATURE = 0.0
MAX_TOKENS = 96

# Canonical hazard -> colloquial alternates. Only keys present in the
# actual index (chunks.json) are permitted; we assert that on first use
# in _get_known_types(). To add an entry, edit this dict in source --
# there is no runtime path that mutates it.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "earthquake": ("quake", "tremor", "seismic"),
    "wildfire": ("forest fire", "brush fire", "bushfire"),
    "tornado": ("twister", "funnel cloud"),
    "tsunami": ("tidal wave",),
    "hurricane": ("cyclone", "typhoon", "tropical storm"),
    "power_outage": ("blackout", "no power", "lost power"),
    "home_fire": ("house fire",),
    "extreme_heat": ("heat wave", "heatwave", "heatstroke", "heat stroke"),
    "winter_weather": ("blizzard", "ice storm", "snowstorm"),
    "flood": ("flash flood", "flooding"),
}


# --- lazy-loaded singletons --------------------------------------------------
# Both the known-types set (from chunks.json) and the LLM are loaded on
# first use so that `import src.query` stays free. Matches the lazy-load
# pattern in src/retrieve.py.
_KNOWN_DISASTER_TYPES: tuple[str, ...] | None = None
_LLM: Any | None = None


def _get_known_types() -> tuple[str, ...]:
    """Return the sorted tuple of disaster_type values present in chunks.json.

    Derived from the index, not from ingest.py's `_*_TYPE_MAP`, so the parser
    can never emit a tag that doesn't correspond to actual indexed content.
    Also audits the `_SYNONYMS` table against the same set on first call --
    fails loudly if a synonym key refers to a hazard the index lacks.
    """
    global _KNOWN_DISASTER_TYPES
    if _KNOWN_DISASTER_TYPES is not None:
        return _KNOWN_DISASTER_TYPES
    path = INDEX_DIR / "chunks.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run `python -m src.ingest` first."
        )
    with open(path, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    types = tuple(sorted({c["disaster_type"] for c in chunks}))
    unknown = set(_SYNONYMS) - set(types)
    if unknown:
        raise AssertionError(
            f"_SYNONYMS has keys not present in chunks.json: {sorted(unknown)}"
        )
    _KNOWN_DISASTER_TYPES = types
    return _KNOWN_DISASTER_TYPES


def _get_llm() -> Any:
    """Lazy llama_cpp.Llama. Exported via this getter so src.generate can
    reuse the same loaded model -- a second load in the same process is
    wasteful and on a laptop will OOM."""
    global _LLM
    if _LLM is not None:
        return _LLM
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Missing model file: {MODEL_PATH}. Download with:\n"
            f"  huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF "
            f'--include "*q4_k_m*" --local-dir server/models'
        )
    from llama_cpp import Llama
    _LLM = Llama(
        model_path=str(MODEL_PATH),
        n_ctx=N_CTX,
        n_gpu_layers=N_GPU_LAYERS,
        seed=SEED,
        verbose=False,
    )
    return _LLM


# --- public types ------------------------------------------------------------
@dataclass
class ParsedQuery:
    """A normalized user query, ready to hand to `src.retrieve.retrieve`.

    `rewritten` is the query string the retriever consumes. `disaster_type`
    (if non-None) is its filter argument and is guaranteed to appear in
    `_get_known_types()`. On any LLM or parse failure, the parser falls
    back to `rewritten == original` and `disaster_type is None` so the
    caller can always proceed to retrieval -- the parser is a quality
    booster, never a gate.
    """
    original: str
    rewritten: str
    disaster_type: str | None


# --- prompt construction -----------------------------------------------------
# Few-shot pattern coverage (one example per category, see plan file):
# typo + clear hazard, colloquial hazard, multi-word hazard with typo,
# general prep (null), indirect hazard reference, off-topic (null). The
# examples are also the schema -- we don't restate the JSON shape in
# English elsewhere.
_FEWSHOTS: list[tuple[str, str]] = [
    (
        "what do i do if a earth quake hit",
        '{"normalized": "what to do during an earthquake", "disaster_type": "earthquake"}',
    ),
    (
        "the ground is shaking",
        '{"normalized": "the ground is shaking", "disaster_type": "earthquake"}',
    ),
    (
        "how to prepare for a wild fire near my house",
        '{"normalized": "how to prepare for a wildfire near my house", "disaster_type": "wildfire"}',
    ),
    (
        "what goes in a go bag",
        '{"normalized": "what goes in a go bag", "disaster_type": null}',
    ),
    (
        "fridge food after power goes out for 2 days",
        '{"normalized": "fridge food after power goes out for 2 days", "disaster_type": "power_outage"}',
    ),
    (
        "who won the 2024 world series",
        '{"normalized": "who won the 2024 world series", "disaster_type": null}',
    ),
]


def _build_system_prompt(types: tuple[str, ...]) -> str:
    types_list = ", ".join(types)
    return (
        "You are a query normalizer for an offline disaster-preparedness "
        "search system. Your job is narrow:\n\n"
        "1. Lightly fix spelling and phrasing in the user's query. Do NOT "
        "add information, vocabulary, or safety advice the user did not "
        "write. Do NOT answer the question. Keep the rewrite close in "
        "length and meaning to the original.\n\n"
        "2. Identify which disaster the user is asking about. The "
        '"disaster_type" field must be EXACTLY one of these values, or '
        "null:\n\n"
        f"   {types_list}\n\n"
        "   Use null when the query is general preparedness (kits, plans, "
        "evacuation routes) that isn't tied to one hazard, or when the "
        "query is unrelated to disasters.\n\n"
        "Output STRICT JSON in exactly this shape, with no surrounding "
        "text, no code fences, no commentary:\n\n"
        '  {"normalized": "<rewritten query>", "disaster_type": "<value-or-null>"}'
    )


def _build_messages(text: str, types: tuple[str, ...]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(types)},
    ]
    for user_msg, assistant_msg in _FEWSHOTS:
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_msg})
    messages.append({"role": "user", "content": text})
    return messages


# --- LLM call + JSON extraction ----------------------------------------------
# Defensive regex for the first JSON object in the model's reply. The
# system prompt forbids commentary or code fences, but at temperature=0
# Qwen occasionally still wraps output -- one malformed token should not
# bring retrieval down.
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _llm_normalize(text: str) -> tuple[str, str | None] | None:
    """Call the LLM and return (normalized, disaster_type) or None on any
    parse / validation failure. The caller decides the fallback."""
    types = _get_known_types()
    llm = _get_llm()
    resp = llm.create_chat_completion(
        messages=_build_messages(text, types),
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    raw = resp["choices"][0]["message"]["content"]
    return _parse_llm_json(raw, types)


def _parse_llm_json(
    raw: str,
    types: tuple[str, ...],
) -> tuple[str, str | None] | None:
    m = _JSON_OBJ_RE.search(raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    normalized = data.get("normalized")
    disaster = data.get("disaster_type")
    if not isinstance(normalized, str) or not normalized.strip():
        return None
    if disaster is not None and disaster not in types:
        return None
    # "general" is an ingest-time tag for cross-cutting prep brochures, not
    # a useful retrieval filter -- filtering on it would exclude every
    # hazard-specific chunk. Treat the model emitting it as a null tag.
    if disaster == "general":
        disaster = None
    return normalized.strip(), disaster


# --- synonym post-processing -------------------------------------------------
def _rules_disaster_type(text: str) -> str | None:
    """Fallback when the LLM returned null: scan for any known synonym and
    return the mapped canonical. Lowercase substring match -- crude, but
    mirrors how BM25 will see the same text. Synonyms are short and
    disjoint, so first-match-wins is fine in practice."""
    lower = text.lower()
    for canonical, alts in _SYNONYMS.items():
        for alt in alts:
            if alt in lower:
                return canonical
    return None


def _append_canonical(text: str, disaster_type: str) -> str:
    """Ensure the canonical hazard word appears in the rewritten query so
    BM25 has the token to match against hazard-tagged chunks. No-op if the
    word is already present."""
    if disaster_type.lower() in text.lower():
        return text
    return f"{text} {disaster_type}"


# --- public entry point ------------------------------------------------------
def parse_query(text: str) -> ParsedQuery:
    """Normalize a raw user query into a ParsedQuery.

    Pipeline: LLM normalize+tag -> validate -> rules fallback for null tag
    -> canonical-word back-fill. Any LLM or parse failure short-circuits to
    `rewritten == original` and `disaster_type is None` so retrieval can
    always proceed.
    """
    original = text.strip()
    if not original:
        return ParsedQuery(original=text, rewritten=text, disaster_type=None)

    parsed = _llm_normalize(original)
    if parsed is None:
        return ParsedQuery(original=original, rewritten=original, disaster_type=None)
    rewritten, disaster_type = parsed

    if disaster_type is None:
        disaster_type = _rules_disaster_type(rewritten)

    if disaster_type is not None:
        rewritten = _append_canonical(rewritten, disaster_type)

    return ParsedQuery(original=original, rewritten=rewritten, disaster_type=disaster_type)


# --- CLI ---------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="LLM query parser CLI.")
    parser.add_argument("query")
    args = parser.parse_args(argv)
    result = parse_query(args.query)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
