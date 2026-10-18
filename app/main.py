import time

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import Base, engine, get_session
from app.models import RequestLog
from app.services.llm import MODEL, generate_answer


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    temperature: float = Field(default=0.7, ge=0, le=2)


Base.metadata.create_all(engine)
app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_session)):
    start = time.perf_counter()

    try:
        answer, input_tokens, output_tokens = generate_answer(
            request.prompt,
            request.temperature,
        )
        status_code = 200
        error_type = None
    except Exception as exc:
        answer = None
        input_tokens = None
        output_tokens = None
        status_code = 502
        error_type = type(exc).__name__

    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    session.add(
        RequestLog(
            model=MODEL,
            prompt_chars=len(request.prompt),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status_code=status_code,
            error_type=error_type,
        )
    )
    session.commit()

    if status_code == 502:
        raise HTTPException(
            status_code=502,
            detail="Gemini request failed. Please try again later.",
        )

    return {"answer": answer, "model": MODEL, "latency_ms": latency_ms}