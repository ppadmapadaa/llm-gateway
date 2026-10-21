import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_session
from app.models import ApiKey, RequestLog, User
from app.security import generate_api_key, get_current_key, hash_api_key
from app.services.llm import MODEL, generate_answer


load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    temperature: float = Field(default=0.7, ge=0, le=2)


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


Base.metadata.create_all(engine)
app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/keys", status_code=201)
def create_key(
    request: CreateKeyRequest,
    x_admin_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    if not ADMIN_TOKEN or not x_admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")

    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    user = session.scalar(select(User).where(User.name == request.name))

    if user is None:
        user = User(name=request.name)
        session.add(user)
        session.flush()

    raw_key = generate_api_key()

    session.add(
        ApiKey(
            user_id=user.id,
            key_hash=hash_api_key(raw_key),
            prefix=raw_key[:10],
        )
    )
    session.commit()

    return {
        "user_id": user.id,
        "api_key": raw_key,
        "prefix": raw_key[:10],
    }


@app.post("/chat")
def chat(
    request: ChatRequest,
    api_key: ApiKey = Depends(get_current_key),
    session: Session = Depends(get_session),
):
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
            user_id=api_key.user_id,
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

    return {
        "answer": answer,
        "model": MODEL,
        "latency_ms": latency_ms,
    }


@app.get("/usage")
def get_usage(
    api_key: ApiKey = Depends(get_current_key),
    session: Session = Depends(get_session),
):
    totals = session.execute(
        select(
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.input_tokens), 0),
            func.coalesce(func.sum(RequestLog.output_tokens), 0),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0),
        ).where(RequestLog.user_id == api_key.user_id)
    ).one()

    error_count = session.scalar(
        select(func.count(RequestLog.id)).where(
            RequestLog.user_id == api_key.user_id,
            RequestLog.status_code >= 400,
        )
    )

    return {
        "request_count": totals[0],
        "error_count": error_count,
        "input_tokens": totals[1],
        "output_tokens": totals[2],
        "average_latency_ms": round(totals[3], 2),
        "cache_hits": 0,
    }


@app.get("/usage/recent")
def get_recent_requests(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    api_key: ApiKey = Depends(get_current_key),
    session: Session = Depends(get_session),
):
    logs = session.scalars(
        select(RequestLog)
        .where(RequestLog.user_id == api_key.user_id)
        .order_by(RequestLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = []

    for log in logs:
        items.append(
            {
                "id": log.id,
                "timestamp": log.timestamp,
                "model": log.model,
                "prompt_chars": log.prompt_chars,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "latency_ms": log.latency_ms,
                "status_code": log.status_code,
                "error_type": log.error_type,
            }
        )

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
    }