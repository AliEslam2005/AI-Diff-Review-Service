import time
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import HealthResponse, SpecResponse, Limits, ReviewRequest
from app.services.jobs import create_job, worker_task, JOBS_DB

START_TIME = time.time()
SERVICE_TOKEN = "my-test-token"

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
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Missing or invalid token"}}
        )
    return authorization


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
    token: str | JSONResponse = Depends(verify_token)
):
    if isinstance(token, JSONResponse): return token
    
    # --- Rate Limiting Enforcement[cite: 2] ---
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

    # Check payload size requirement[cite: 2]
    if len(request.diff.encode('utf-8')) > 1048576:
        return JSONResponse(
            status_code=413, 
            content={"error": {"code": "payload_too_large", "message": "Payload exceeds 1 MiB limit"}}
        )
    
    job_id, status_code, error = create_job(request.diff, request.options.model_dump(), idempotency_key)
    
    if error:
        return JSONResponse(status_code=status_code, content=error)
        
    return JSONResponse(status_code=status_code, content={"jobId": job_id, "status": "queued"})


@app.get("/v1/reviews/{job_id}")
async def get_review_status(job_id: str, token: str | JSONResponse = Depends(verify_token)):
    if isinstance(token, JSONResponse): return token
    
    job = JOBS_DB.get(job_id)
    if not job:
        return JSONResponse(
            status_code=404, 
            content={"error": {"code": "not_found", "message": "Job not found"}}
        )
        
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "findings": job["findings"],
        "usage": job["usage"]
    }


@app.get("/v1/reviews/{job_id}/stream")
async def stream_review(job_id: str, token: str | JSONResponse = Depends(verify_token)):
    if isinstance(token, JSONResponse): return token
    
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