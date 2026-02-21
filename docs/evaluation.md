# InjectionRadar Feature Evaluation

## Date: 2026-02-21
## Author: Evaluation Agent

---

## 1. RATE LIMITING (Task #2 / rate-limiter agent)

### Current State
Rate limiting is **already fully implemented** in `src/api/main.py:137-225`:
- Redis sliding-window rate limiter (`RateLimitMiddleware`)
- Per-endpoint tier limits (`_RATE_LIMITS` dict)
- Client IP extraction with `X-Forwarded-For` support
- Proper `429` responses with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` headers
- Graceful fallthrough when Redis is unavailable
- Rate limit Redis connection initialized in `lifespan()` (line 77-89)

### Critical Risks
1. **DO NOT REWRITE** - The existing implementation is solid. Enhancement only.
2. **Shared Redis connection**: Rate limiter uses a separate `aioredis.Redis` instance (`rate_limit_redis` global at line 47), distinct from the job queue. This is correct and should not be changed.
3. **Config mismatch**: `APIConfig.rate_limit_per_minute = 60` in `config.py:106` is unused by the actual middleware which uses the hardcoded `_RATE_LIMITS` dict and `_DEFAULT_RATE_LIMIT = 60`. Any enhancement should either wire up the config value or remove it from config to avoid confusion.
4. **`_persisted_jobs` memory leak** (line 473): The set grows unbounded and only trims at 10K entries. This is tangentially related but should not be touched by the rate-limiter agent.

### Recommended Enhancements Only
- Make rate limits configurable via `config.yaml` instead of hardcoded
- Add per-API-key rate limiting (currently only per-IP)
- Add rate limit metrics/logging for monitoring
- Consider adding burst allowance

### Files That Will Be Touched
- `src/api/main.py` (modify existing middleware)
- `src/core/config.py` (potentially add rate limit config section)
- `config/config.yaml` (add rate limit tiers)

### CONFLICT RISK: **HIGH** - `src/api/main.py` is also the target for the Web Dashboard agent (new routes) and potentially MCP agent. Rate limiter changes to middleware must not break anything.

---

## 2. CHECKPOINT SYSTEM (Task #3 / checkpoint-dev agent)

### Current State
- **Pydantic model exists**: `CrawlCheckpoint` in `src/core/models.py:200-216`
- **DB model exists**: `CrawlCheckpointDB` in `src/core/database.py:266-287`
- **CLI checkpoint functions exist**: `src/cli/interactive.py:82-138` has file-based JSON checkpoints (`load_checkpoint`, `save_checkpoint`, `delete_checkpoint`, `list_checkpoints`) using `~/.injection-radar/checkpoints/`
- **config.yaml**: `crawling.checkpoint_interval: 50` already defined

### Critical Risks
1. **TWO CHECKPOINT SYSTEMS**: The CLI already has a file-based checkpoint system (JSON files in `~/.injection-radar/checkpoints/`). The database has `CrawlCheckpointDB`. The agent needs to decide: unify them or keep both. File-based is simpler for CLI resumability; DB-based is better for Docker/API.
2. **CrawlCheckpointDB table is created but never used**: `init_db()` creates it via `Base.metadata.create_all`, but no code reads/writes to it.
3. **The CLI `scan list` command** likely already uses the file-based checkpoints. Any DB-based system should supplement, not break the existing CLI flow.

### Recommended Approach
- The DB-based checkpoint system should be used by the API/orchestrator for large crawls
- Keep the existing CLI file-based system for interactive resume
- Add a `POST /crawl` endpoint that uses `CrawlCheckpointDB` for server-side batch crawls

### Files That Will Be Touched
- `src/core/database.py` (may need checkpoint CRUD helpers)
- `src/api/main.py` (new crawl endpoints)
- `src/cli/interactive.py` (may integrate DB checkpoints for `resume` command)

### CONFLICT RISK: **MEDIUM** - Touches `src/api/main.py` (shared with rate-limiter and dashboard agents). The CLI file is large (900+ lines), edits must be surgical.

---

## 3. WEB DASHBOARD (Task #4)

### Current State
- No templates, no HTML files in the project (only test files)
- No `jinja2` in dependencies
- FastAPI + Jinja2 is the right choice (no npm/React/build tools)
- CORS is already configured with wildcard in `src/api/main.py:111-117`

### Critical Risks
1. **New dependency**: Must add `jinja2` to `pyproject.toml` and `requirements.txt`
2. **Must NOT break API**: Dashboard routes must coexist with existing JSON API routes. Use a separate router or prefix like `/dashboard/`.
3. **Static files**: Need `fastapi.staticfiles.StaticFiles` for CSS/JS. Need to decide on location (`src/api/static/` or `static/` at project root).
4. **Templates location**: Need `src/api/templates/` directory.
5. **Docker**: The `Dockerfile.orchestrator` must include the templates and static files in the image. Currently it likely only copies `src/`. This needs verification.
6. **Security**: Dashboard shows scan results which is safe (no raw HTML). But if it displays URLs, ensure they are properly escaped to prevent XSS.

### Recommended Architecture
- Add routes under `/dashboard` prefix
- Minimal Jinja2 templates (base.html, dashboard.html, scan-detail.html)
- Use HTMX for interactivity (no build tooling needed)
- Reuse existing API endpoints for data (dashboard routes call internal functions)

### Files That Will Be Touched
- **NEW**: `src/api/templates/` directory (multiple HTML files)
- **NEW**: `src/api/static/` directory (CSS, maybe JS)
- `src/api/main.py` (mount static files, add template routes)
- `pyproject.toml` (add jinja2 dependency)
- `requirements.txt` (add jinja2)
- `docker/Dockerfile.orchestrator` (include templates/static in image)

### CONFLICT RISK: **HIGH** - Heavy modifications to `src/api/main.py`. Must coordinate with rate-limiter (middleware) and checkpoint (new API routes) agents.

---

## 4. SCHEDULED SCANS (Task #5)

### Current State
- No scheduler code exists
- `APScheduler` is not in dependencies
- `config.yaml` has rescan intervals defined: `crawling.rescan_interval_safe: 30`, `rescan_interval_suspicious: 7`, `rescan_interval_dangerous: 3`
- `URLDB.next_scan` column exists (line 84 in database.py) but is never populated
- The `CrawlingConfig` in `config.py:88-97` has all the interval fields

### Critical Risks
1. **New dependency**: Must add `apscheduler>=3.10.0` (v3.x, NOT v4.x which has a completely different API)
2. **Integration point**: Scheduler must run inside the orchestrator process OR as a separate worker. Running inside the orchestrator's FastAPI lifespan is simpler.
3. **Re-scan logic**: Must query `URLDB` for urls where `next_scan < now()`, then enqueue them via the existing `JobQueue`. This is clean because it reuses the existing scan pipeline.
4. **`URLDB.next_scan` population**: After each scan completes, `_save_scan_results()` in `main.py` must set `next_scan` based on the classification and rescan intervals. Currently it does NOT do this.
5. **Concurrency**: If multiple orchestrator instances run (unlikely but possible), they could schedule duplicate scans. Need a lock mechanism (Redis-based or DB-based).

### Recommended Architecture
- Add `APScheduler` `AsyncIOScheduler` to the FastAPI lifespan
- Job runs every N minutes, queries URLs due for rescan
- Enqueues them via existing `job_queue.enqueue_scan()`
- After scan completes, `_save_scan_results()` calculates and sets `next_scan`
- Add `/scheduler/status` API endpoint to check scheduler state
- Add config section for scheduler (enable/disable, check interval)

### Files That Will Be Touched
- **NEW**: `src/core/scheduler.py` (scheduler logic)
- `src/api/main.py` (start scheduler in lifespan, add status endpoint)
- `src/core/config.py` (add SchedulerConfig)
- `config/config.yaml` (add scheduler section)
- `pyproject.toml` (add apscheduler dependency)
- `requirements.txt` (add apscheduler)

### CONFLICT RISK: **HIGH** - Modifies `src/api/main.py` lifespan and adds new endpoints. Must coordinate with ALL other agents touching this file.

---

## 5. MCP SERVER HARDENING (Task #6)

### Current State
- MCP server exists at `src/mcp/server.py` with 5 tools: `scan_url`, `scan_urls`, `get_history`, `check_url`, `get_dangerous_domains`
- It's a thin HTTP proxy: calls FastAPI API endpoints via `httpx`
- `mcp` is an optional dependency (`[project.optional-dependencies] mcp = ["mcp>=1.0.0"]`)
- Entry point: `injection-radar-mcp = "src.mcp.server:main"`

### Critical Risks
1. **DO NOT REWRITE** - The existing server works. Hardening only.
2. **No input validation**: `_scan_url` and `_scan_urls` do basic URL normalization but no real validation. Malicious MCP clients could pass arbitrary strings.
3. **No rate limiting on MCP side**: The MCP server proxies to the API which has rate limiting, but MCP clients get the same IP (localhost), meaning all MCP calls share one rate limit bucket.
4. **Error handling is minimal**: Generic `except Exception` catches everything. Should differentiate network errors, timeouts, and API errors.
5. **No authentication**: Anyone who can connect to the MCP server can scan URLs. This is acceptable for local use but needs documentation.
6. **Timeout values**: `_scan_url` uses 180s timeout, `_get_history` uses 30s. These should be configurable.

### Recommended Hardening
- Add URL validation (reject non-HTTP URLs, private IPs, localhost)
- Add proper error types/messages
- Add request logging
- Add configurable timeouts
- Add health check tool
- Document security model (localhost-only, no auth by design)

### Files That Will Be Touched
- `src/mcp/server.py` (primary target)
- Possibly `src/core/config.py` (MCP config section)

### CONFLICT RISK: **LOW** - `src/mcp/server.py` is an isolated module. No other agent should touch it.

---

## 6. CROSS-CUTTING CONCERNS AND CONFLICT ANALYSIS

### The `src/api/main.py` Bottleneck

This is the most dangerous file. **FOUR agents** may need to edit it:

| Agent | What they need | Lines affected |
|-------|---------------|----------------|
| rate-limiter | Modify middleware, maybe config wiring | 137-225 |
| checkpoint-dev | Add crawl/checkpoint API endpoints | New endpoints after line 670+ |
| dashboard | Add template routes, static files mount | New routes, lifespan changes |
| scheduler | Add scheduler to lifespan, status endpoint | lifespan (50-101), new endpoint |

**Mitigation**: Each agent should add code in SEPARATE sections. Use FastAPI `APIRouter` for new endpoint groups to minimize merge conflicts:
- Dashboard: `dashboard_router = APIRouter(prefix="/dashboard")`
- Checkpoint: add endpoints at end of file
- Scheduler: add to lifespan + one status endpoint
- Rate limiter: modify existing middleware only

### The `src/core/config.py` Conflict

Multiple agents may need to add config sections:

| Agent | Config addition |
|-------|----------------|
| scheduler | `SchedulerConfig` class + field in `Settings` |
| dashboard | Possibly template/static paths |
| rate-limiter | Wire existing `api.rate_limit_per_minute` or add tier config |

**Mitigation**: Each agent should add their config class and field independently. Config classes are self-contained.

### The `config/config.yaml` Conflict

Same as above - multiple agents adding YAML sections. Less risky since YAML sections are independent blocks.

### The `pyproject.toml` / `requirements.txt` Conflict

Multiple agents adding dependencies. Git merge should handle this automatically since they add different lines.

---

## 7. DEPENDENCY ANALYSIS

### New Dependencies Required

| Feature | Package | Version | Notes |
|---------|---------|---------|-------|
| Dashboard | `jinja2` | `>=3.1.0` | Templating |
| Dashboard | (optional) `python-multipart` | Already in requirements.txt | For form submissions |
| Scheduler | `apscheduler` | `>=3.10.0,<4.0.0` | Pin to v3, v4 is incompatible |

### Existing Dependencies That Are Sufficient
- Rate Limiting: Uses existing `redis` package
- Checkpoint: Uses existing `sqlalchemy`
- MCP: Uses existing `mcp` optional dep + `httpx`

---

## 8. DOCKER BUILD IMPLICATIONS

### What Needs to Change in Docker
1. **Dashboard**: `Dockerfile.orchestrator` must copy `src/api/templates/` and `src/api/static/` into the image
2. **Scheduler**: Must install `apscheduler` in orchestrator image
3. **Dashboard**: Must install `jinja2` in orchestrator image
4. **Nothing changes for scraper image** - none of these features affect the scraper

### The `Dockerfile.orchestrator` needs to be checked
The current build likely does `COPY src/ /app/src/` which would include templates/static automatically. But we should verify the Dockerfile exists and has the right structure.

---

## 9. TESTING PRIORITIES

### What Must Be Tested
1. **Rate Limiting**: Verify existing tests still pass after enhancement. Test new config wiring.
2. **Checkpoint**: Test resume from checkpoint. Test checkpoint CRUD in DB.
3. **Dashboard**: Manual browser testing. Verify API endpoints still work (no regression).
4. **Scheduler**: Test scheduler starts/stops correctly. Test rescan query logic. Test `next_scan` population.
5. **MCP**: Test URL validation rejects bad input. Test error handling.

### Integration Test Order
1. Rate Limiting (enhancing existing, lowest risk)
2. MCP Hardening (isolated module, low risk)
3. Checkpoint System (new feature, medium risk)
4. Scheduled Scans (new feature, touches lifespan, higher risk)
5. Web Dashboard (most new code, highest risk of conflicts)

---

## 10. SUMMARY OF CRITICAL FINDINGS

| # | Finding | Severity | Affected Agent |
|---|---------|----------|---------------|
| 1 | Rate limiting already implemented - DO NOT REWRITE | CRITICAL | rate-limiter |
| 2 | MCP server already exists - DO NOT REWRITE | CRITICAL | mcp-dev |
| 3 | `src/api/main.py` is a 4-agent conflict hotspot | HIGH | ALL |
| 4 | Two checkpoint systems (file + DB) must be reconciled | HIGH | checkpoint-dev |
| 5 | `URLDB.next_scan` never populated (needed by scheduler) | MEDIUM | scheduler |
| 6 | `api.rate_limit_per_minute` config unused by actual code | MEDIUM | rate-limiter |
| 7 | No `jinja2` or `apscheduler` in deps yet | MEDIUM | dashboard, scheduler |
| 8 | Dashboard needs Docker build changes | MEDIUM | dashboard |
| 9 | APScheduler v3 vs v4 API incompatibility risk | MEDIUM | scheduler |
| 10 | MCP server lacks input validation | LOW | mcp-dev |
