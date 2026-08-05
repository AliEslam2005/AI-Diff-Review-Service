import asyncio
import hashlib
import json
import uuid

# --- In-Memory State Stores ---
# These dictionaries will hold our data as long as the server is running.
JOBS_DB = {}
IDEMPOTENCY_DB = {}
CACHE_DB = {}

# The queue to hold pending jobs
job_queue = asyncio.Queue()

def generate_payload_hash(diff: str, options: dict) -> str:
    """Creates a deterministic hash of the payload for caching and idempotency checks."""
    payload = {"diff": diff, "options": options}
    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def create_job(diff: str, options: dict, idempotency_key: str | None = None) -> tuple[str | None, int, dict | None]:
    """
    Handles idempotency, caching, and queuing a new job.
    Returns: (job_id, http_status_code, error_envelope_if_conflict)
    """
    payload_hash = generate_payload_hash(diff, options)
    
    # 1. Idempotency Check
    if idempotency_key:
        if idempotency_key in IDEMPOTENCY_DB:
            existing = IDEMPOTENCY_DB[idempotency_key]
            if existing["hash"] == payload_hash:
                return existing["jobId"], 202, None
            else:
                # Same key + different body -> 409[cite: 2]
                error = {"error": {"code": "idempotency_conflict", "message": "Idempotency key used with different payload"}}
                return None, 409, error

    # 2. Caching Check[cite: 2]
    if payload_hash in CACHE_DB:
        cached_job_id = CACHE_DB[payload_hash]
        if idempotency_key:
            IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": cached_job_id}
            
        # Mark that this subsequent request was a cache hit
        if cached_job_id in JOBS_DB:
             JOBS_DB[cached_job_id]["usage"]["cacheHit"] = True
             
        return cached_job_id, 202, None

    # 3. Create New Job
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    JOBS_DB[job_id] = {
        "jobId": job_id,
        "status": "queued",
        "findings": [],
        "usage": {"inputBytes": len(diff.encode('utf-8')), "chunks": 0, "cacheHit": False},
        "diff": diff,          # Stored temporarily for the worker to read
        "options": options     # Stored temporarily for the worker to read
    }
    
    if idempotency_key:
        IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": job_id}
        
    CACHE_DB[payload_hash] = job_id
    
    # Add to background queue so workers can pick it up
    job_queue.put_nowait(job_id)
    
    return job_id, 202, None

async def worker_task():
    """Background worker that continuously processes jobs from the queue."""
    while True:
        job_id = await job_queue.get()
        job = JOBS_DB.get(job_id)
        
        if job and job["status"] == "queued":
            job["status"] = "running"
            await asyncio.sleep(0) # Yield control back to event loop briefly
            
            try:
                # TODO: In the next step, we will inject the mock parser and chunking logic here
                await asyncio.sleep(0.5) # Simulating work for now
                job["status"] = "done"
            except Exception as e:
                job["status"] = "failed"
                
            # Cleanup: remove the raw diff from memory once done to save space
            job.pop("diff", None)
            job.pop("options", None)
            
        job_queue.task_done()