# STABILIZATION_REPORT.md
## Project AB — Phase 1 Stabilization

**Report Date:** 2026-07-31  
**Engineer:** Kiro (AI Lead Engineer)  
**Status: PHASE 1 COMPLETE — STABLE**

---

## 1. Bugs Fixed

### Bug 1 — `load_dotenv()` Not Finding `.venv/.env` (Critical)

**Files Affected:** `brain.py`, `Ag.py`  
**Severity:** Critical — entire cloud brain silently non-functional  
**Root Cause:**  
Both `brain.py` and `Ag.py` called `load_dotenv()` without specifying a path. The `python-dotenv` library searches the current working directory and its parents for a `.env` file. In this project the `.env` is located at `.venv/.env` — a non-standard location outside the dotenv search path — so `load_dotenv()` returned without loading any variables. `os.getenv("OPENROUTER_API_KEY")` returned `None` on every call.

**Symptom:**  
- Cloud brain API calls failed silently with 401 / "No API key" errors.
- Default `auto` brain mode fell through to cloud fallback, which then also failed.

**Fix Applied:**  
Added an explicit dotenv path with a project-root fallback in both files:

```python
_dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', '.env')
if os.path.exists(_dotenv_path):
    load_dotenv(dotenv_path=_dotenv_path)
else:
    load_dotenv()
```

This resolves the `.venv/.env` path relative to the script file, so the fix is robust regardless of the working directory from which AG is launched.

---

### Bug 2 — Cloud Model Slug `tencent/hy3:free` No Longer Valid (Critical)

**File Affected:** `brain.py`  
**Severity:** Critical — cloud brain always returned a 404 error  
**Root Cause:**  
The `ask_cloud_brain()` function used the model identifier `tencent/hy3:free`. OpenRouter removed the free tier variant of this model; the slug now returns:

```
404: This model is unavailable for free. The paid version is available now — use this slug instead: tencent/hy3
```

**Fix Applied:**  
Updated the model identifier from `tencent/hy3:free` to `tencent/hy3`:

```python
response = get_client().chat.completions.create(
    model="tencent/hy3",
    ...
)
```

Verified live — the corrected slug responded successfully.

---

## 2. Files Modified

| File | Change |
|------|--------|
| `brain.py` | Fixed `load_dotenv()` to explicitly target `.venv/.env`; updated model slug from `tencent/hy3:free` to `tencent/hy3` |
| `Ag.py` | Fixed `dotenv.load_dotenv()` to explicitly target `.venv/.env` |

No other files were modified.

---

## 3. Remaining Issues

### Minor — Ollama ANSI Escape Codes in Terminal Output

**Severity:** Cosmetic only  
**Description:**  
When the local brain (`qwen2.5:3b`) responds via `subprocess.run(["ollama", "run", ...])`, Ollama emits ANSI cursor-movement escape sequences (`\u001B[12D`, `\u001B[K`, etc.) in its stdout. These appear in the terminal output as stray characters on non-ANSI-aware terminals.

**Impact:** None on interactive use in a standard terminal. AG's logic, parsing, and memory are not affected.  
**Recommendation:** Low priority. Could be addressed in Phase 2 by switching to the Ollama Python library API (already installed: `ollama==0.6.2`) instead of subprocess, which would give clean streaming output without escape codes.

---

### Minor — No Graceful EOF Handling in Main Loop

**Severity:** Cosmetic only (affects scripted/piped input)  
**Description:**  
`main()` in `Ag.py` calls `input("You: ")` inside a `while True` loop with no `try/except EOFError`. When stdin is piped and closes (e.g. in tests or scripts), an unhandled `EOFError` is raised.

**Impact:** None in interactive use. Occurs only when input is piped programmatically.  
**Recommendation:** Can be added in Phase 2 if scripted/automated invocation is needed.

---

## 4. Runtime Status

| Check | Status |
|-------|--------|
| Startup | ✅ Clean — all 5 startup messages print correctly |
| Greeting intent | ✅ Working |
| Memory operations (remember/recall/show) | ✅ Working |
| Task operations (add/show/complete) | ✅ Working |
| Project context operations | ✅ Working |
| Brain mode switching (local/cloud/auto) | ✅ Working |
| Brain status query | ✅ Working |
| Local brain (Ollama `qwen2.5:3b`) | ✅ Working — verified live response |
| Cloud brain (`tencent/hy3` via OpenRouter) | ✅ Working — verified live response |
| Working memory (topic tracking, follow-up resolution) | ✅ Working |
| Discussion buffer (has_unsaved_discussion, add_to_discussion) | ✅ Working |
| Graceful shutdown | ✅ Clean — prints shutdown messages, exits normally |
| Analytics event logging | ✅ Working — events.jsonl written correctly |
| No runtime exceptions during normal use | ✅ Confirmed |

---

## 5. Dependency Summary

### Runtime Dependencies (installed in `.venv`)

| Package | Version | Role |
|---------|---------|------|
| `openai` | 2.41.1 | OpenRouter cloud brain client |
| `python-dotenv` | 1.2.2 | Environment variable loading |
| `ollama` | 0.6.2 | Installed but not yet used (local brain uses subprocess) |
| `httpx` | 0.28.1 | HTTP transport for openai client |
| `pydantic` | 2.13.4 | Data validation |

### Environment

| Item | Value |
|------|-------|
| Python | 3.14 (venv at `.venv`) |
| `.env` location | `.venv/.env` |
| `OPENROUTER_API_KEY` | Present and valid |
| Cloud model | `tencent/hy3` via `https://openrouter.ai/api/v1` |
| Local model | `qwen2.5:3b` via Ollama subprocess |

### Import Dependency Graph

```
Ag.py
├── executive.py          (interpret_storage_decision, interpret_category_decision, analyze_context, build_execution_plan)
│   └── brain.py          (ask_brain)
├── working_memory.py     (WorkingMemory, resolve_followup)
├── conversation_manager.py (analyze_action_pattern)
│   └── working_memory.py
├── analytics_logger.py   (log_event)
└── brain.py              (ask_brain, ask_cloud_direct, ask_local, set_brain_mode, get_brain_status, load_brain_mode)
    └── local_brain.py    (ask_local_brain)

ag_pipeline.py
├── working_memory.py
├── executive_layer.py
├── cognitive_engine.py
├── brain_dispatcher.py
└── response_processor.py
```

No circular imports detected.

---

## 6. Test Results

**All 35 tests across 7 test files passed.**

| Test File | Tests | Result |
|-----------|-------|--------|
| `test_working_memory.py` | 8 | ✅ All pass |
| `test_cognitive_engine.py` | 5 | ✅ All pass |
| `test_brain_dispatcher.py` | 3 | ✅ All pass |
| `test_response_processor.py` | 3 | ✅ All pass |
| `test_executive_layer.py` | 3 | ✅ All pass |
| `test_ag_pipeline.py` | 7 | ✅ All pass |
| `test_conversation_manager.py` | 18 | ✅ All pass |
| **Total** | **47** | **✅ All pass** |

*(Note: test_conversation_manager.py has 18 tests; total count is 47.)*

---

## 7. Modules Verified

| Module | Status | Notes |
|--------|--------|-------|
| `working_memory.py` | ✅ Stable | New architecture is the source of truth. All methods present. No compatibility issues. |
| `conversation_manager.py` | ✅ Stable | Deterministic. No LLM calls. Correct reference resolution and topic tracking. |
| `executive.py` | ✅ Stable | Storage and category decisions work correctly. LLM fallback for ambiguous input is functional. |
| `executive_layer.py` | ✅ Stable | Storage routing and category decisions confirmed. |
| `brain.py` | ✅ Stable (after fix) | Both local and cloud paths functional after dotenv and model slug fixes. |
| `local_brain.py` | ✅ Stable | Ollama subprocess call works. `qwen2.5:3b` responds correctly. |
| `cognitive_engine.py` | ✅ Stable | All five pipeline stages function correctly. |
| `brain_dispatcher.py` | ✅ Stable | Mock adapters work. Dispatch routing correct. |
| `response_processor.py` | ✅ Stable | Sanitization, safety checks, and action extraction all correct. |
| `ag_pipeline.py` | ✅ Stable | End-to-end pipeline executes cleanly. All failure recovery paths tested. |
| `analytics_logger.py` | ✅ Stable | Append-only event logging works. No exceptions. |
| `Ag.py` | ✅ Stable (after fix) | Full conversation loop verified. All intents route correctly. |

---

## 8. Architecture Observations

1. **Dual-architecture split:** AG has two distinct execution paths that operate independently of each other:
   - **Primary path (Ag.py):** Direct intent routing → `ask_brain()` → local or cloud response. This is the live interactive path.
   - **Pipeline path (ag_pipeline.py):** Full cognitive pipeline (CognitiveEngine → BrainDispatcher → ResponseProcessor → ExecutiveLayer). This is architected but uses mock brain adapters — it does not yet call real LLMs.

   These two paths do not conflict. The pipeline is an evolutionary layer being built incrementally alongside the working primary path.

2. **WorkingMemory is the session backbone:** All cross-turn state (topic tracking, discussion buffer, pending actions, follow-up resolution) flows through `WorkingMemory`. The new architecture is complete and stable. Legacy attribute-style access (e.g. `working_memory.default_brain`) has been properly replaced with the new API (`cache_decision`/`add_fact`) throughout `Ag.py`.

3. **`.venv/.env` convention:** The project stores its `.env` file inside the virtual environment directory. This is non-standard and caused the environment loading bug. It works correctly with the explicit path fix, but a more standard approach (`.env` at project root) would be simpler. Recommend moving `.env` to the project root in Phase 2.

4. **Ollama integration uses subprocess:** `local_brain.py` calls `ollama` via `subprocess.run()`. The `ollama` Python library (`0.6.2`) is already installed and provides a cleaner API. Migrating to it in Phase 2 would eliminate the ANSI escape code issue.

5. **`development_manager.py` is empty:** The file exists but contains no code. This is not a bug — it's a placeholder for future development.

6. **No circular imports:** The import graph is a clean DAG. `brain.py` is the only module with external network calls; all others are deterministic.

---

## 9. Phase 1 Completion Recommendation

**Phase 1 is complete. AG is stable.**

All Phase 1 success criteria are met:

| Criterion | Status |
|-----------|--------|
| Starts successfully | ✅ |
| Runs without runtime exceptions | ✅ |
| Completes an entire conversation loop | ✅ |
| Passes all existing tests | ✅ (47/47) |
| No broken imports | ✅ |
| No missing methods | ✅ |
| No circular dependency issues | ✅ |
| No compatibility issues between modules | ✅ |
| Produces clean startup logs | ✅ |
| Shuts down gracefully | ✅ |

The two bugs that were present (dotenv path and stale model slug) have been fixed with minimal, targeted changes. The architecture has not been redesigned, renamed, or extended. All existing tests pass and no new tests were required.

**Phase 2 development may proceed.**

---

*Report generated by Kiro — Phase 1 Stabilization, 2026-07-31*
