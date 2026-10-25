# LLM Gateway

A backend-heavy FastAPI gateway between client applications and Google Gemini.
It authenticates clients, validates requests, rate-limits usage, caches safe
responses, records usage in SQLite, and exposes usage data through an API and
Streamlit dashboard.

This project is a tested single-server prototype. Its in-memory cache and rate
limiter are not shared across processes or machines.

## Why this project exists

Client applications should not need to manage provider authentication, retries,
usage tracking, rate limits, and caching separately. They send requests to this
gateway, and the gateway handles those concerns in one place.

## Architecture

```mermaid
flowchart LR
    A[Client application] --> B[FastAPI gateway]
    D[Streamlit dashboard] --> B
    E[GATE Notes Assistant] --> B
    B --> C{Authenticated?}
    C -->|No| F[401 response]
    C -->|Yes| G[Rate limiter]
    G --> H[TTL cache]
    H -->|Hit| I[Return cached answer]
    H -->|Miss| J[Gemini API]
    J --> K[SQLite request log]
    I --> K
```

## Request flow

```text
Client request
  -> assign request ID
  -> validate JSON
  -> authenticate hashed API key
  -> check per-key rate limit
  -> check exact-match cache
  -> call Gemini on a cache miss
  -> record status, latency and token usage
  -> return a consistent JSON response
```

## Features

- FastAPI HTTP API with automatic Swagger documentation
- Pydantic request validation
- Google Gemini answer generation
- Random client API keys stored as SHA-256 hashes
- Per-key fixed-window rate limiting
- Per-user exact-match cache with a five-minute TTL
- One retry for selected temporary Gemini failures
- Provider timeout
- SQLite and SQLAlchemy request logging
- Per-user usage totals and recent-request history
- Request IDs in responses and database logs
- Consistent JSON error responses
- Streamlit dashboard
- Docker support
- Integration with the GATE Notes Assistant RAG project

## Technology

- Python 3.13
- FastAPI and Uvicorn
- Pydantic
- SQLAlchemy and SQLite
- Google Gen AI SDK
- HTTPX
- Streamlit
- Docker

## Project structure

```text
llm gateway/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── security.py
│   └── services/
│       ├── cache.py
│       ├── llm.py
│       └── rate_limit.py
├── tests/
│   └── test_health.py
├── dashboard.py
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── .dockerignore
```

## Local setup on Windows

Create and activate a virtual environment:

```cmd
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```cmd
python -m pip install -r requirements.txt
```

Create `.env` from `.env.example`:

```env
GEMINI_API_KEY=your_gemini_api_key
ADMIN_TOKEN=your_long_random_admin_token
```

Never commit `.env`.

Start the gateway:

```cmd
python -m uvicorn app.main:app --reload
```

Open the API documentation:

```text
http://127.0.0.1:8000/docs
```

## Creating a client API key

In `/docs`, open `POST /admin/keys`.

Provide the admin token through the `X-Admin-Token` header and a body such as:

```json
{
  "name": "alice"
}
```

The full client key is returned once:

```json
{
  "user_id": 1,
  "api_key": "generated-client-key",
  "prefix": "generated-"
}
```

The database stores only its SHA-256 hash. Save the raw key securely because it
cannot be recovered from the hash.

## Calling the chat endpoint

Send the client key as a bearer token:

```http
POST /chat
Authorization: Bearer generated-client-key
Content-Type: application/json

{
  "prompt": "Explain virtual memory",
  "temperature": 0.2
}
```

Example response:

```json
{
  "answer": "Virtual memory is...",
  "model": "gemini-3.5-flash-lite",
  "latency_ms": 1432.21,
  "request_id": "5d625a0e-01b7-4cbd-975f-4d054ab39a71"
}
```

Useful response headers include:

```text
X-Request-ID
X-Cache
X-RateLimit-Limit
X-RateLimit-Remaining
```

## Endpoints

| Method | Path | Purpose | Authentication |
|---|---|---|---|
| `GET` | `/health` | Check whether the service is running | None |
| `POST` | `/admin/keys` | Create a user and client key | Admin token |
| `POST` | `/chat` | Generate or retrieve an answer | Bearer client key |
| `GET` | `/usage` | Return the current user's totals | Bearer client key |
| `GET` | `/usage/recent` | Return paginated recent requests | Bearer client key |

## Dashboard

Start the gateway first. In another terminal, run:

```cmd
streamlit run dashboard.py
```

The dashboard acts as an API client. It does not import the gateway's database
models or read SQLite directly.

It can:

- Submit prompts
- Show answers, latency, cache status and request ID
- Display usage totals
- Display recent request records

<!-- Add a dashboard screenshot here before publishing the repository. -->

## Docker

Build the image:

```cmd
docker build -t llm-gateway .
```

Run a container:

```cmd
docker run --name llm-gateway-container -p 8000:8000 --env-file .env llm-gateway
```

Verify it from another terminal:

```cmd
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The local database inside a container is lost if that container is deleted.
A production deployment would use persistent storage or an external database.

## Error format

Errors use one response structure:

```json
{
  "error": {
    "status_code": 401,
    "message": "API key required",
    "request_id": "5d625a0e-01b7-4cbd-975f-4d054ab39a71"
  }
}
```

Common status codes:

| Code | Meaning |
|---|---|
| `401` | Missing, invalid or revoked key |
| `422` | Request validation failed |
| `429` | Per-key rate limit exceeded |
| `502` | Gemini request failed |

## Security choices

- `.env` is excluded from Git and Docker.
- SQLite files are excluded from Git and Docker.
- Client keys are generated with Python's `secrets` module.
- Only SHA-256 hashes of high-entropy client keys are stored.
- Raw client keys are returned only when created.
- Admin tokens are compared using `secrets.compare_digest()`.
- Prompts and raw keys are not stored in the database or application logs.
- Cache keys contain prompts temporarily in process memory.
- Usage queries filter records by the authenticated user's ID.
- Internal Gemini exception messages are not returned to clients.

SHA-256 is suitable here because the client keys are long, random tokens.
Human-created passwords would require a slow password-hashing algorithm such as
Argon2 or bcrypt.

## Reliability behavior

- Gemini requests have a 15-second timeout.
- Temporary HTTP `408`, `429`, `500`, `502`, `503`, and `504` failures receive at
  most one retry.
- Authentication and validation failures are never retried.
- Low-temperature successful answers can be cached for five minutes.
- Failed and high-temperature requests are not cached.

## Testing

Run the current automated check with:

```cmd
python -m pytest -q
```

The repository currently contains a health-handler test. Provider, caching,
rate-limit and authentication behavior were developed as part of the prototype,
but a complete automated test suite remains future work.

## GATE Notes Assistant integration

The GATE Notes Assistant keeps its existing PDF extraction, chunking, embeddings,
vector storage and retrieval. It sends only its final grounded-answer prompt to
this gateway through `POST /chat`.

This lets the gateway centrally authenticate the application, call Gemini,
record usage, apply rate limits and cache eligible answers.

## Limitations

- The rate limiter is stored in one Python process.
- Cache entries are stored in one Python process.
- Restarting the process clears rate limits and cached answers.
- Multiple workers or servers would not share those values.
- SQLite is suitable for this prototype, not a horizontally scaled deployment.
- Revoking keys currently requires changing the database directly.
- The Docker setup does not configure persistent SQLite storage.
- Only one LLM provider is supported.
- The automated test suite is incomplete.

For a larger deployment, shared services such as Redis and PostgreSQL, database
migrations, structured monitoring, and stricter provider-specific exception
handling would be appropriate.

## Interview summary

I built a FastAPI gateway that sits between client applications and Gemini. It
authenticates random client API keys while storing only their SHA-256 hashes. It
applies per-key rate limits and per-user TTL caching before calling Gemini. It
records request ownership, latency, token counts, status, cache results and
request IDs in SQLite. I packaged the service with Docker and documented that its
in-memory components make it a single-server prototype rather than production-
scale infrastructure.
