# AG Routing Stress Test Report

Date: 2026-09-16
Repository: `D:\AG`
Scope: testing and diagnostics only

## 1. Test environment

- OS: Windows
- Python: `D:\AG\.venv\Scripts\python.exe` (Python 3.14.6)
- Repository state: pre-existing dirty worktree; no source changes were made by this test.
- Network/LLM: not used for deterministic assertions. Cloud fallback was observed where the live path selected it; the environment has no usable OpenRouter credentials.
- Existing pytest command was attempted but could not start because `pytest` is not installed in the active virtual environment. No dependency was installed.
- Existing `scripts\verify_live.py` completed successfully with 26 checks passed and 0 failed.
- Existing `scripts\diag_self_info.py` completed with 24 passed and 1 failed.
- Direct API diagnostics exercised `quips.analyze_request`, `PreprocessorBrain`, `Ag.process_input`, `ConversationManager`, `DirectoryControl`, and existing fallback behavior.

## 2. Tests executed

The following were exercised:

- 20 varied single self-info inputs, including identity, capabilities, limitations, brains, architecture, and operational wording.
- 10 compound self-info inputs, including reordered 3-, 4-, and 5-unit requests.
- 6 workflow-shaped file requests.
- 5 mixed self-info, workspace, explanation, listing, and file-operation requests.
- 7 unknown/general requests.
- Compound execution with an LLM guard that raises if a fallback call is attempted.
- Failure isolation with an intentionally failing architecture unit.
- ConversationManager follow-ups for local/other brain references and capabilities/limitations continuation.
- Ten repeated executions of `Tell me who you are, what you're capable of, and how you work internally.`
- Non-destructive temporary-directory listing, file creation, and file reading through `DirectoryControl`.
- Existing routing-contract cases were manually invoked because pytest was unavailable.

## 3. Single-request results

Most single requests were deterministic and correctly owned by QUIPS/self-info:

| Input family | QUIPS category | QUIPS intent | Routing | Result |
|---|---|---|---|---|
| `Who are you?`, `Tell me about yourself.` | `SELF_INFO` | `IDENTITY` | `DETERMINISTIC_SELF_INFO` | Pass |
| `What can you do?`, `What are your capabilities?` | `SELF_INFO` | `CAPABILITIES` | `DETERMINISTIC_SELF_INFO` | Pass |
| `What can't you do?`, `What are your limitations?` | `SELF_INFO` | `LIMITATIONS` | `DETERMINISTIC_SELF_INFO` | Pass |
| `What brains do you have?`, `How many brains do you have?` | `SELF_INFO` | `BRAINS` | `DETERMINISTIC_SELF_INFO` | Pass |
| `What systems do you have?`, `How do you process requests?` | `SELF_INFO` | `ARCHITECTURE` | `DETERMINISTIC_SELF_INFO` | Pass |
| `Explain your architecture.` | `SELF_INFO` | `ARCHITECTURE` | `DETERMINISTIC_SELF_INFO` | Pass |
| `What functionality do you have?` | `SELF_INFO` | `CAPABILITIES` | `DETERMINISTIC_SELF_INFO` | Pass |

### Single-request failure

**Input:** `And what are you capable of?`

- Expected: self-info capabilities.
- QUIPS category: `SELF_INFO`.
- QUIPS intent: `IDENTITY`.
- Preprocessor intent: `GET_IDENTITY`.
- Routing: deterministic self-info, so no LLM call occurred.
- Actual result: identity response instead of capabilities response.
- Responsible stage: `self_info.query_router.route_query()` semantic pattern ordering, propagated through QUIPS and PreprocessorBrain.
- Classification: confirmed implementation defect.
- Invariant impact: violates the intent portion of invariant 9 (deterministic self-info should remain correctly classified) and weakens invariant 11 ownership preservation.

The existing diagnostic script independently reproduced the same failure: 24 passed, 1 failed, for the same input.

## 4. Compound-request results

### Structural behavior

Across the 10 compound self-info cases:

- Every input produced at least one request unit.
- Request counts were preserved for the obvious 3-, 4-, and 5-request cases.
- Unit order was preserved.
- Every unit retained the full original input in `original_text`.
- No duplicate units were observed.
- QUIPS itself made no LLM calls.

### Successful compound cases

These executed as deterministic composed responses with the LLM guard active:

- `Who are you, what can you do, and how do you work internally?`
- `Tell me about yourself, what are your capabilities, and what are your limitations.`
- `What brains do you have, what systems do you have, and how do you process requests?`
- `What can you do and what can't you do?`
- `Who are you, what can you do, what can't you do, what brains do you have, and how do you work internally?`

Responses were non-empty and composed in request order. The 5-unit case returned identity, capabilities, limitations, brain information, and architecture.

### Compound failure

**Input:** `Tell me who you are, what you can do, what you can't do, and how you work.`

Produced units:

| Index | Text | Category | Intent | Routing |
|---:|---|---|---|---|
| 0 | `Tell me who you are` | `SELF_INFO` | `IDENTITY` | deterministic |
| 1 | `what you can do` | `GENERAL` | `GENERAL_REASONING` | LLM fallback |
| 2 | `what you can't do` | `SELF_INFO` | `LIMITATIONS` | deterministic |
| 3 | `how you work.` | `GENERAL` | `GENERAL_REASONING` | LLM fallback |

Actual composed response with the LLM guard was:

```text
AG: [identity response]

AG: I couldn't complete this part of the request.

AG: [limitations response]

AG: I couldn't complete this part of the request.
```

- Expected: four deterministic self-info units, including capabilities and architecture.
- Actual: two units were incorrectly sent to fallback; the guard caused those units to fail and be replaced by isolated failure messages.
- Responsible stage: QUIPS unit classification delegated to `self_info.query_router.route_query()`; the phrases `what you can do` and `how you work` are not recognized in these fragment forms.
- Classification: confirmed implementation defect.
- Invariant impact: violates invariants 2, 6, 8, 9, and 14. Units were preserved structurally, but valid deterministic requests were not routed deterministically and their results were not produced.

This is also directly coupled to the existing contract test case for `Tell me who you are, what you're capable of, and how you work internally.` only when wording is changed to the supported `you're capable` and `how you work internally`; that exact supported wording remained stable.

## 5. Workflow results

| Input | QUIPS result | Observation |
|---|---|---|
| `Create a folder named test and put test.txt inside it.` | 1 unit, `FILE_OPERATION`, `CREATE_FILE` | Correctly preserved as one coherent workflow. Preprocessor reached `CREATE_FOLDER` but reported `NO_ACTIVE_WORKSPACE`; no disk change was made. |
| `Create a folder and put a file inside it.` | 1 unit | Correctly preserved as one workflow. Preprocessor reported `NO_ACTIVE_WORKSPACE`. |
| `Make a directory called demo and write note.txt inside it.` | 1 unit | Correctly preserved as one workflow. Preprocessor reported `NO_ACTIVE_WORKSPACE`. |
| `Create a folder named test, then create test.txt inside it.` | 1 unit | Correctly preserved as one workflow. |
| `Create test.txt and then tell me what you created.` | 1 unit | Failure: action plus independent explanation was not decomposed; Preprocessor returned `GENERAL_LLM`. |
| `Create test.txt, then explain why you created it.` | 1 unit | Failure: action plus independent explanation was not decomposed; Preprocessor returned `GENERAL_LLM`. |

The first three folder/file cases support the intended workflow-preservation behavior. The latter two fail the existing independent-request contract: the operation and explanation should be separate routable units. Responsible stage: QUIPS `_split_independent_requests()` / workflow boundary detection. Classification: confirmed implementation defect.

## 6. Mixed-request results

The following retained independent categories:

- `Tell me who you are and create a file named test.txt.` -> identity plus file operation, two units.
- `Tell me about your architecture and explain why Python is being used.` -> architecture plus general reasoning, two units.
- `What brains do you have and list the files here.` -> brain information plus general/file-list candidate, two units.
- `What can you do and create a file named test.txt.` -> capabilities plus file operation, two units.

`What's my current workspace and what can you do?` produced two units, but the first unit was `GENERAL_REASONING` with `LLM_FALLBACK` rather than a workspace/local-state category. The second remained deterministic capabilities. This is a classification gap for the workspace wording, not a QUIPS unit-loss problem.

## 7. Conversation-context results

ConversationManager remained deterministic and did not call an LLM. It preserved turns and topics, and the capabilities-to-limitations continuation resolved as:

```text
What about your limitations?
-> recent_turn_fallback
-> What about your limitations? (continuing the capabilities discussion)
```

The requested brain references did not resolve:

- After `What brains do you have?` with topic `local brain`, `Tell me more about the local one.` returned `resolved: false`, `reference_type: none`.
- `What about the other one?` also returned `resolved: false`, `reference_type: none`.

The manager preserves the words `local one`/`other one` as input, but does not map them to the local/cloud brain entities. No explicit existing contract in the inspected ConversationManager defines those aliases, so this is recorded as an ambiguous design gap rather than asserting a defect in the core turn store. It does show that the requested reference scenario is not currently coherent end-to-end.

Compound turn preservation passed: one user turn plus one assistant turn resulted in `turn_count == 2`, with compound metadata retained on the user turn.

## 8. Unknown-request results

The following remained explicit fallback candidates rather than being forced into deterministic AG handlers:

- `Florbulate the unclassified thing.`
- `What is the meaning of existence?`
- `Predict the weather tomorrow.`
- `Explain quantum entanglement in simple terms.`
- `Please solve this arbitrary puzzle: 7x+3=24.`
- `Tell me a joke about a penguin.`
- `Blah blah unrelated words.`

QUIPS returned `GENERAL` / `GENERAL_REASONING` / `LLM_FALLBACK`; PreprocessorBrain returned `GENERAL_LLM`, `UNKNOWN`, and `requires_llm: true`. This is expected behavior. One legacy `detect_intent()` result was `recall` for the meaning-of-existence input, but it did not overwrite QUIPS ownership or change the fallback decision.

## 9. Failure-isolation results

An intentionally failing `ARCHITECTURE` unit was injected into:

```text
Tell me about yourself, what can you do, and how do you work internally.
```

Actual result retained:

- `IDENTITY result`
- `CAPABILITIES result`
- isolated `I couldn't complete this part of the request.`

The unit status model recorded `COMPLETED` for successful units and `FAILED` with an error for the failing unit. Successful siblings were not erased. This passed the failure-isolation contract.

## 10. Repetition/stability results

The important compound query was run 10 times:

```text
Tell me who you are, what you're capable of, and how you work internally.
```

All 10 QUIPS signatures were identical:

1. `IDENTITY` -> deterministic self-info
2. `CAPABILITIES` -> deterministic self-info
3. `ARCHITECTURE` -> deterministic self-info

No deterministic-to-cloud transition, intermittent classification, empty response, or intermittent exception occurred in this supported wording. The failures described above are stable deterministic classification gaps, not intermittent failures.

## 11. Regression results

### Passed

- Existing live verification: 26/26 checks passed.
- Preprocessor self-info, fallback classifier, intent router, temporary DirectoryControl listing, temporary file creation, and temporary file reading passed in `scripts\verify_live.py`.
- Temporary DirectoryControl regression independently confirmed list returns a list and create/read returns the expected content.
- Brain selection/action-pattern code remained deterministic in the inspected ConversationManager surface.
- Unknown/general fallback behavior remained available.
- Compound conversation storage remained one user/assistant turn pair.

### Environment or setup-limited

- Live `Ag.process_input()` regression calls were made without an active workspace in the PreprocessorBrain-owned directory state. Listing and folder creation consequently returned the explicit `NO_ACTIVE_WORKSPACE` message.
- A current-workspace compound probe selected a legacy `recall` route and then fell through to cloud fallback; the environment had no OpenRouter credentials. The observed `[BRAIN_DIAG]` reported missing credentials. This is an external dependency failure for the fallback call, with a preceding routing/classification gap.
- Pytest-based regression tests could not run because `pytest` is absent from the active virtual environment. This is a test-environment problem, not a source result.

## 12. Architectural invariant results

| Invariant | Result |
|---|---|
| 1. Every input produces at least one request unit | Pass for all non-empty inputs tested. |
| 2. Compound requests preserve independent requests | Partial: structural splitting preserved tested self-info units, but action-plus-explanation workflows were incorrectly kept whole. |
| 3. Request order is preserved | Pass for decomposed compounds. |
| 4. Original input remains traceable | Pass; every unit retained the full original input. |
| 5. Single requests remain legacy-compatible | Partial; deterministic self-info remains compatible, but natural variants can be misclassified. |
| 6. QUIPS does not call an LLM | Pass; direct API is side-effect-free. |
| 7. ConversationManager is not the intent classifier | Pass; it stored context/resolved references only. |
| 8. Deterministic self-info avoids unnecessary LLM fallback | Partial/fail for `what you can do` and `how you work` compound fragments. |
| 9. Unknown requests are not incorrectly classified | Pass for unknown matrix; legacy intent noise did not overwrite QUIPS fallback ownership. |
| 10. Failed unit does not erase successful units | Pass. |
| 11. Legacy `detect_intent()` does not overwrite valid QUIPS ownership | Pass in tested unknown and deterministic cases. |
| 12. Compound processing does not create duplicate turns | Pass in direct ConversationManager contract. |
| 13. Compound processing does not lose conversation context | Partial; turn context is retained, but local/other brain aliases are unresolved. |
| 14. Response composition preserves all unit results | Pass for successful deterministic compounds and isolated failures; fails semantically when misclassified units fall back. |

## 13. Exact failures discovered

### Failure A: capability phrase classified as identity

- Input: `And what are you capable of?`
- Expected: `SELF_INFO / CAPABILITIES / GET_CAPABILITIES`.
- Actual: `SELF_INFO / IDENTITY / GET_IDENTITY`.
- Routing: deterministic self-info, no LLM.
- Handler: self-info identity handler.
- Stage: `self_info.query_router`.
- Type: confirmed implementation defect.

### Failure B: natural compound fragments fall back

- Input: `Tell me who you are, what you can do, what you can't do, and how you work.`
- Expected units: identity, capabilities, limitations, architecture.
- Actual units: identity, general fallback, limitations, general fallback.
- Handler/fallback: two fallback units; guarded execution produced isolated failure messages.
- Stage: QUIPS classification through `self_info.query_router`.
- Type: confirmed implementation defect.

### Failure C: action plus explanation is not decomposed

- Inputs:
  - `Create test.txt and then tell me what you created.`
  - `Create test.txt, then explain why you created it.`
- Expected: create-file unit plus independent explanation unit, with isolated routing.
- Actual: one `FILE_OPERATION / CREATE_FILE` unit; Preprocessor returned `GENERAL_LLM` for the whole request.
- Stage: QUIPS request splitting/workflow boundary logic.
- Type: confirmed implementation defect; it also contradicts the existing routing-contract test expectation.

### Failure D: local/other brain references unresolved

- Inputs after `What brains do you have?`:
  - `Tell me more about the local one.`
  - `What about the other one?`
- Expected for a fully coherent reference flow: resolve to the relevant previously introduced brain entities or request clarification.
- Actual: `resolved: false`, `reference_type: none`, `needs_clarification: false`.
- Stage: ConversationManager reference-resolution patterns.
- Type: ambiguous design gap requiring a product decision about brain aliases and clarification policy.

## 14. Environment/dependency problems

- `pytest` is not installed; pytest-based tests were not executable.
- Cloud fallback diagnostics reported missing OpenRouter credentials. This affected only requests that had already fallen through to the brain path.
- No dependencies were installed or removed.
- No configuration was changed.
- No permanent filesystem operation was performed. Temporary-directory operations were cleaned up by the test harness.

## 15. Overall architectural observations

The hardened request-unit data model is functioning: QUIPS is deterministic, traceability and ordering are preserved, compound responses are composed as one response, and failure isolation works. Unknown requests remain explicit fallback candidates, and legacy intent values do not replace a valid QUIPS deterministic ownership decision.

The main risk is coverage asymmetry between full natural-language requests and fragments produced by compound splitting. The self-info router recognizes exact standalone forms such as `what can you do` and `how do you work internally`, but not semantically equivalent fragments such as `what you can do` and `how you work` after QUIPS removes coordination. A second risk is that workflow detection currently protects folder-inside-file sequences but does not consistently separate file creation from a subsequent explanation request. Conversation state storage is sound, while entity-level aliases such as local/other brain remain unresolved.

No fixes are included in this report.
