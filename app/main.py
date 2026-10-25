import logging
import os
import secrets
import time
import uuid

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import Base, engine, get_session
from app.models import ApiKey, RequestLog, User
from app.security import generate_api_key, get_current_key, hash_api_key
from app.services.cache import get_cached_answer, make_cache_key, save_to_cache
from app.services.llm import MODEL, generate_answer
from app.services.rate_limit import rate_limiter


load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
MAX_PROMPT_LENGTH = 6000
CACHE_MAX_TEMPERATURE = 0.7

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    temperature: float = Field(default=0.7, ge=0, le=2)


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


Base.metadata.create_all(engine)
app = FastAPI(title="LLM Gateway")


def error_response(status_code: int, message: str, request_id: str, headers: dict[str, str] | None = None):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "status_code": status_code,
                "message": message,
                "request_id": request_id,
            }
        },
        headers=headers,
    )


def record_request(session: Session, request_id: str, user_id: int, prompt_chars: int, input_tokens: int | None, output_tokens: int | None, latency_ms: float, status_code: int, error_type: str | None, cache_hit: bool):
    session.add(
        RequestLog(
            request_id=request_id,
            user_id=user_id,
            model=MODEL,
            prompt_chars=prompt_chars,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status_code=status_code,
            error_type=error_type,
            cache_hit=cache_hit,
        )
    )
    session.commit()


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exception: StarletteHTTPException):
    return error_response(
        status_code=exception.status_code,
        message=str(exception.detail),
        request_id=request.state.request_id,
        headers=exception.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exception: RequestValidationError):
    return error_response(
        status_code=422,
        message="Request validation failed",
        request_id=request.state.request_id,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exception: Exception):
    logger.error(
        "request_id=%s error_type=%s",
        request.state.request_id,
        type(exception).__name__,
    )

    return error_response(
        status_code=500,
        message="Internal server error",
        request_id=request.state.request_id,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/keys", status_code=201)
def create_key(request: CreateKeyRequest, x_admin_token: str | None = Header(default=None), session: Session = Depends(get_session)):
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
def chat(chat_request: ChatRequest, response: Response, http_request: Request, api_key: ApiKey = Depends(get_current_key), session: Session = Depends(get_session)):
    request_id = http_request.state.request_id
    allowed, remaining, retry_after = rate_limiter.check(api_key.id)

    if not allowed:
        record_request(
            session=session,
            request_id=request_id,
            user_id=api_key.user_id,
            prompt_chars=len(chat_request.prompt),
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            status_code=429,
            error_type="RateLimitExceeded",
            cache_hit=False,
        )

        logger.info(
            "request_id=%s user_id=%s status_code=429 cache_hit=False",
            request_id,
            api_key.user_id,
        )

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limiter.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    response.headers["X-RateLimit-Limit"] = str(rate_limiter.limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)

    start = time.perf_counter()
    cache_key = make_cache_key(
        user_id=api_key.user_id,
        model=MODEL,
        prompt=chat_request.prompt,
        temperature=chat_request.temperature,
    )

    use_cache = chat_request.temperature <= CACHE_MAX_TEMPERATURE
    cached_answer = get_cached_answer(cache_key) if use_cache else None

    if cached_answer is not None:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        record_request(
            session=session,
            request_id=request_id,
            user_id=api_key.user_id,
            prompt_chars=len(chat_request.prompt),
            input_tokens=0,
            output_tokens=0,
            latency_ms=latency_ms,
            status_code=200,
            error_type=None,
            cache_hit=True,
        )

        logger.info(
            "request_id=%s user_id=%s status_code=200 cache_hit=True",
            request_id,
            api_key.user_id,
        )

        response.headers["X-Cache"] = "HIT"

        return {
            "answer": cached_answer,
            "model": MODEL,
            "latency_ms": latency_ms,
            "request_id": request_id,
        }

    response.headers["X-Cache"] = "MISS"

    try:
        answer, input_tokens, output_tokens = generate_answer(
            chat_request.prompt,
            chat_request.temperature,
        )
        status_code = 200
        error_type = None
    except Exception as exception:
        answer = None
        input_tokens = None
        output_tokens = None
        status_code = 502
        error_type = type(exception).__name__

    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    if status_code == 200 and use_cache:
        save_to_cache(cache_key, answer)

    record_request(
        session=session,
        request_id=request_id,
        user_id=api_key.user_id,
        prompt_chars=len(chat_request.prompt),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        status_code=status_code,
        error_type=error_type,
        cache_hit=False,
    )

    logger.info(
        "request_id=%s user_id=%s status_code=%s cache_hit=False error_type=%s",
        request_id,
        api_key.user_id,
        status_code,
        error_type,
    )

    if status_code == 502:
        raise HTTPException(
            status_code=502,
            detail="Gemini request failed. Please try again later.",
        )

    return {
        "answer": answer,
        "model": MODEL,
        "latency_ms": latency_ms,
        "request_id": request_id,
    }


@app.get("/usage")
def get_usage(api_key: ApiKey = Depends(get_current_key), session: Session = Depends(get_session)):
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

    cache_hits = session.scalar(
        select(func.count(RequestLog.id)).where(
            RequestLog.user_id == api_key.user_id,
            RequestLog.cache_hit.is_(True),
        )
    )

    return {
        "request_count": totals[0],
        "error_count": error_count,
        "input_tokens": totals[1],
        "output_tokens": totals[2],
        "average_latency_ms": round(totals[3], 2),
        "cache_hits": cache_hits,
    }


@app.get("/usage/recent")
def get_recent_requests(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), api_key: ApiKey = Depends(get_current_key), session: Session = Depends(get_session)):
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
                "request_id": log.request_id,
                "timestamp": log.timestamp,
                "model": log.model,
                "prompt_chars": log.prompt_chars,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "latency_ms": log.latency_ms,
                "status_code": log.status_code,
                "error_type": log.error_type,
                "cache_hit": log.cache_hit,
            }
        )

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
    }
