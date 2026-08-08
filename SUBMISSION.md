# SUBMISSION.md

## Architecture

FastAPI service (single process) with 4 background `asyncio` worker tasks pulling from an in-memory queue.

- `POST /v1/reviews` validates the request, calculates the hash of `{diff, options}` for idempotency/caching, enqueues a job and returns `202` immediately. All processing is async.
- A worker pulls the job, splits it into chunks of ≤ 64KiB on file boundaries, sends each chunk to the selected provider, sorts and deduplicates the results in a global fashion across the chunks, and marks the job as `done` (or `failed`, with an error stored).
- The job state (status, findings, usage, and a full event log for SSE) is stored in an in-memory dict of data, keyed by job ID; the poll and stream endpoints simply read from this dict.
- Custom exception handlers normalize FastAPI's default error shapes into the contract's `{error:{code,message}}` envelope.

## Provider design

Both providers have a common interface. A function takes a diff chunk and returns findings in the same `Finding` schema, so the pipeline in jobs.py (chunk → scan → merge/sort/dedupe → truncate) is the same in both cases.

- **mock**: a regex rule table (`MOCK_RULES`) applied to each added line via a small unified-diff line parser. Fully deterministic. One rule (`MOCK-004`, empty catch block) needed a short look-ahead across added lines rather than a single-line regex, since the contract explicitly allows the block to span lines.
- **llm**: Google's `google-genai` SDK (Gemini). Gemini 3.6 Flash. The client is lazily built, meaning that if you don't have an API key, the jobs that require it will fail, but the app won't crash on startup. The response from the model is checked and filtered (any key missing or with a severity that is not schema is dropped) before being accepted. On purpose, there are no exceptions in this path. Any failure (bad key, network error, malformed model output) will bubble up to the worker's `except` block, which results in a clean `failed` job with a stored error message, rather than a hang or crash.

## How I verified the cross-cutting behaviors

Mostly with a self-contained Postman collection (included in the repo) built to cover what the contract's scoring section calls out specifically, not just the happy path.

- **Chunking**: created a synthetic multi-file diff (~170KB across 10 files, two of which were each over 64KB) and verified that a chunked scan returns the same result as an unchunked scan of the same diff: same results, same order, no dups or losses, and the oversized files were correctly identified as their own chunks.
- **Caching / idempotency**: If you submit the same `{diff, options}` again, you will get the same `jobId` and the same `cacheHit: true`; If you submit the same key with a different body, you will get `409`; If you submit the same key with the same body again, you will get the same jobId and the same `cacheHit: true`.
- **SSE replay**: Connected to a job's stream *after* the job has completed, all `status`/`finding`/`done` events replay exactly the same, as the event log is not stored for the stream itself, but only for the job.
- **Injection inertness**: a diff combining an injection phrase with a real `eval()` on the next line reports both as ordinary findings; neither suppresses the other.
- **Error taxonomy**: automated checks across all error paths: `401` on missing/wrong tokens (checked before job lookup, so an unknown ID with no auth returns `401`, not `404`), `400`/`invalid_json` on malformed bodies, `422`/`invalid_diff` on missing or empty diffs, `413` on oversized payloads, `409` on idempotency conflicts, `404` on unknown jobs. The exact envelope shape was asserted, not just the status code.
- **Rate limiting / concurrency**: 35 rapid submissions using Postman's Collection Runner - first ~30 succeeded, the rest returned with `429` and `Retry-After`, never a `5xx`. 5+ jobs are run concurrently, each one of which is separately confirmed, and no job blocks another.
- **llm degradation**: ran the same job against a working key (real findings, correct schema) and a broken/missing key (clean `failed` status with a readable error), confirming neither path ever hangs or crashes.

## AI tools used

Claude, Gemini, and ChatGPT: for scaffolding, debugging, and reviewing the implementation against the contract.

## An AI suggestion I rejected

Both Gemini and ChatGPT suggested Express for the service. I went with FastAPI instead:

- The task is a basic async job pipeline (background workers, SSE streaming). That's exactly what the native async/await of FastAPI does, whereas Express would require additional libraries to be added on to achieve the same.
- Pydantic gave me request/response validation matching the contract's JSON shapes almost for free, instead of hand-rolling it.
- A free manual-testing surface was created during development, as were the models that generated the documentation, for `/docs`.

A second one: Gemini proposed to hardcode a value into a Railway environment variable to control the app's port. I pushed back. This defeats the purpose of Railway's dynamic `PORT` injection, and silently fails if the platform ever changes its port assignment. Rather, the Dockerfile's `CMD` directly reads from the platform's $PORT, making it adaptable.

A third: After half way through the test, the following command was failing locally: `POST /v1/reviews` and it was recommended to begin editing the file `main.py`. First, I rebuilt the Docker image to eliminate a simpler cause. It was just a stale build from before an earlier fix, it was not a new bug. I would not have patched code if I hadn't checked the server I was running against before installing it.

## What I'd do next with more time

- The multi-line empty-catch detection (`MOCK-004`) fails to detect the case where the closing brace is not added, but rather remains in the same context, as it is only added lines that the parser reports. That's part of handling it properly, too, which involves keeping track of context lines.
- Replace the in-memory job/idempotency/cache stores with something persistent (Redis or SQLite). Right now a process restart during the scoring window loses all job history, which is fine for a take-home but not for anything real.
- Add a real "is this actually a parseable unified diff" check rather than just rejecting empty strings. A garbage non-diff string currently gets accepted and just produces zero findings instead of a `422`.
- Replace the Postman collection's checks with a pytest suite that can be executed in CI, rather than only be executed manually.
- Per-client rate limiting (which it never had more than one real caller).