"""HTTP shim around src.generate.answer.

Single-process FastAPI server so the ~4.7 GB Qwen GGUF and the ~140 MB
cross-encoder load exactly once, on the first request. Bind to 127.0.0.1
only -- the Next.js route handler proxies browser traffic, so this never
needs to face the network. Matches the "internet off during demo" rule.

No CORS, no auth, no streaming. The Next.js layer is the only client.
"""
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel

from src.generate import answer

app = FastAPI()


class AnswerRequest(BaseModel):
    query: str


@app.post("/answer")
def post_answer(req: AnswerRequest):
    result = answer(req.query)
    return {
        "answer": result.answer,
        "gated": result.gated,
        "top_score": result.top_score,
        "citations": [asdict(h) for h in result.citations],
    }


@app.get("/health")
def health():
    return {"ok": True}
