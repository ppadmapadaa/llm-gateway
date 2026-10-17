import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.services.llm import generate_answer


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    temperature: float = Field(default=0.7, ge=0, le=2)


app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    start = time.perf_counter()

    try:
        answer = generate_answer(request.prompt, request.temperature)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Gemini request failed. Please try again later.",
        )

    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    return {
        "answer": answer,
        "model": "gemini-3.5-flash-lite",
        "latency_ms": latency_ms,
    }