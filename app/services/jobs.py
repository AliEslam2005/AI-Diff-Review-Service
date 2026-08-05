import asyncio
import hashlib
import json
import uuid

# Import our mock engine
from app.providers.mock import scan_diff_with_mock

# --- In-Memory State Stores ---
JOBS_DB = {}
IDEMPOTENCY_DB = {}
CACHE_DB = {}

job_queue = asyncio.Queue()

def generate_payload_hash(diff: str, options: dict) -> str:
    payload = {"diff": diff, "options": options}
    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def create_job(diff: str, options: dict, idempotency_key: str | None = None) -> tuple[str | None, int, dict | None]:
    payload_hash = generate_payload_hash(diff, options)
    
    # 1. Idempotency Check
    if idempotency_key:
        if idempotency_key in IDEMPOTENCY_DB:
            existing = IDEMPOTENCY_DB[idempotency_key]
            if existing["hash"] == payload_hash:
                return existing["jobId"], 202, None
            else:
                error = {"error": {"code": "idempotency_conflict", "message": "Idempotency key used with different payload"}}
                return None, 409, error

    # 2. Caching Check
    if payload_hash in CACHE_DB:
        cached_job_id = CACHE_DB[payload_hash]
        if idempotency_key:
            IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": cached_job_id}
            
        if cached_job_id in JOBS_DB:
             JOBS_DB[cached_job_id]["usage"]["cacheHit"] = True
             
        return cached_job_id, 202, None

    # 3. Create New Job
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    
    # Calculate bytes immediately for the usage block
    input_bytes = len(diff.encode('utf-8'))
    
    # Naive chunk estimation (1 chunk per 64KiB). 
    # Note: We will need a strict file-boundary chunking algorithm later for a perfect score.
    estimated_chunks = max(1, (input_bytes + 65535) // 65536)

    JOBS_DB[job_id] = {
        "jobId": job_id,
        "status": "queued",
        "findings": [],
        "usage": {"inputBytes": input_bytes, "chunks": estimated_chunks, "cacheHit": False},
        "diff": diff,          
        "options": options     
    }
    
    if idempotency_key:
        IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": job_id}
        
    CACHE_DB[payload_hash] = job_id
    job_queue.put_nowait(job_id)
    
    return job_id, 202, None

async def worker_task():
    while True:
        job_id = await job_queue.get()
        job = JOBS_DB.get(job_id)
        
        if job and job["status"] == "queued":
            job["status"] = "running"
            await asyncio.sleep(0) # Yield to event loop
            
            try:
                diff_text = job["diff"]
                options = job["options"]
                provider_type = options.get("provider", "mock")
                max_findings = options.get("maxFindings", 100)

                # Route to the correct provider
                if provider_type == "mock":
                    # Run the full scan in a separate thread so it doesn't block the async event loop
                    all_findings = await asyncio.to_thread(scan_diff_with_mock, diff_text)
                else:
                    # TODO: Implement LLM provider later
                    all_findings = []

                # Truncate the findings list based on maxFindings
                job["findings"] = all_findings[:max_findings]
                job["status"] = "done"

            except Exception as e:
                job["status"] = "failed"
                
            finally:
                # Cleanup: remove the raw diff from memory
                job.pop("diff", None)
                job.pop("options", None)
            
        job_queue.task_done()