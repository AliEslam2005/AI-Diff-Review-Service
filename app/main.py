import os
import time
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi import Request

from app.models.schemas import HealthResponse, SpecResponse, Limits, ReviewRequest, ReviewOptions
from app.services.jobs import create_job, worker_task, JOBS_DB

# Load environment variables from .env
load_dotenv()

START_TIME = time.time()
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "my-test-token")

# In-memory rate limiter tracker
RATE_LIMIT_DB = deque()
RATE_LIMIT_PER_MIN = 30

@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = [asyncio.create_task(worker_task()) for _ in range(4)]
    yield
    for w in workers:
        w.cancel()

app = FastAPI(title="AI Diff Review Service", lifespan=lifespan)

def verify_token(authorization: str = Header(None)):
    expected_header = f"Bearer {SERVICE_TOKEN}"
    if not authorization or authorization != expected_header:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "unauthorized", "message": "Missing or invalid token"}}
        )
    return authorization

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Pass through our custom error envelopes, otherwise wrap standard HTTP errors
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code, 
        content={"error": {"code": "internal", "message": str(exc.detail)}}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Differentiate between bad JSON formatting and missing/empty fields
    if any(e.get("type") == "json_invalid" for e in exc.errors()):
        return JSONResponse(
            status_code=400, 
            content={"error": {"code": "invalid_json", "message": "Body is not valid JSON"}}
        )
    return JSONResponse(
        status_code=422, 
        content={"error": {"code": "invalid_diff", "message": "diff is missing, empty, or invalid"}}
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", version="1.0.0", uptimeSeconds=int(time.time() - START_TIME))

@app.get("/spec", response_model=SpecResponse)
async def get_spec():
    return SpecResponse(
        specVersion="1.0",
        providers=["mock", "llm"],
        limits=Limits(maxPayloadBytes=1048576, chunkBytes=65536, maxConcurrentJobs=4, rateLimitPerMinute=30)
    )


@app.post("/v1/reviews")
async def submit_review(
    request: ReviewRequest, 
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    token: str = Depends(verify_token)
):
    # --- Rate Limiting Enforcement ---
    now = time.time()
    while RATE_LIMIT_DB and RATE_LIMIT_DB[0] < now - 60:
        RATE_LIMIT_DB.popleft()
        
    if len(RATE_LIMIT_DB) >= RATE_LIMIT_PER_MIN:
        retry_after = str(int(60 - (now - RATE_LIMIT_DB[0])))
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": retry_after},
            content={"error": {"code": "rate_limited", "message": "Rate limit exceeded"}}
        )
    RATE_LIMIT_DB.append(now)
    # -------------------------------------------

    # Check payload size requirement
    if len(request.diff.encode('utf-8')) > 1048576:
        return JSONResponse(
            status_code=413, 
            content={"error": {"code": "payload_too_large", "message": "Payload exceeds 1 MiB limit"}}
        )
    
    options_dict = request.options.model_dump() if request.options else ReviewOptions().model_dump()
    job_id, status_code, error = create_job(request.diff, options_dict, idempotency_key)
    
    if error:
        return JSONResponse(status_code=status_code, content=error)
        
    return JSONResponse(status_code=status_code, content={"jobId": job_id, "status": "queued"})


@app.get("/v1/reviews/{job_id}")
async def get_review_status(job_id: str, token: str = Depends(verify_token)):
    job = JOBS_DB.get(job_id)
    if not job:
        return JSONResponse(
            status_code=404, 
            content={"error": {"code": "not_found", "message": "Job not found"}}
        )
        
    response = {
        "jobId": job["jobId"],
        "status": job["status"],
        "findings": job["findings"],
        "usage": job["usage"]
    }

    # Surface the error detail if the job failed
    if job["status"] == "failed" and "error" in job:
        response["error"] = job["error"]

    return response


@app.get("/v1/reviews/{job_id}/stream")
async def stream_review(job_id: str, token: str = Depends(verify_token)):
    job = JOBS_DB.get(job_id)
    if not job:
        return JSONResponse(
            status_code=404, 
            content={"error": {"code": "not_found", "message": "Job not found"}}
        )

    async def event_generator():
        yielded_count = 0
        while True:
            while yielded_count < len(job["events"]):
                evt = job["events"][yielded_count]
                yield {"event": evt["event"], "data": evt["data"]}
                yielded_count += 1
            
            if job["status"] in ["done", "failed"] and yielded_count >= len(job["events"]):
                break
                
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())