"""HTTP shim around src.generate.answer.

Single-process FastAPI server so the ~1.9 GB Qwen GGUF and the ~140 MB
cross-encoder load exactly once, on the first request. Bind to 127.0.0.1
only -- the Next.js route handler proxies browser traffic, so this never
needs to face the network. Matches the "internet off during demo" rule.

No CORS, no auth. Two endpoints:
  POST /answer  -- synchronous, returns full JSON (used by CLI / tests).
  POST /stream  -- SSE stream; emits meta, token, and done events so the
                   UI can render tokens as they arrive.
The Next.js layer is the only client.
"""
import json
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.generate import answer, answer_stream

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


@app.post("/stream")
def post_stream(req: AnswerRequest):
    def event_gen():
        for event in answer_stream(req.query):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"ok": True}
