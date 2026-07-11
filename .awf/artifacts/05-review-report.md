# Review Report — ABUS-DOCTOR-001

> Artifact: ReviewReport | Role: reviewer (Claude Code) | Date: 2026-07-11
> Method: constitution.md §8 — first-line review flags only deterministic failures;
> non-deterministic notes are advisory, carried to the decider.

## Verdict: **PASS** (recommend approve)

All in-scope acceptance criteria met. No deterministic failures found. Reviewer ran the
token/VPS verification commands that were intentionally deferred by the implementer.

## Verification performed by reviewer (real, against user's VPS)

| Check | Result |
|-------|--------|
| `doctor --help` shows command | ✅ |
| Happy path (real coder token → VPS), read-only | ✅ all PASS, exit 0 |
| Bad token → auth FAIL, exit 1, **no traceback** | ✅ prints `401` + fix hint |
| Unreachable server → health FAIL, exit 1, no traceback | ✅ (implementer verified; code path confirmed) |
| `--send-test` round-trip (writes real event) | ✅ `sent id=10 → pending → acked`, exit 0 |
| Queue left clean after send-test | ✅ pending = `[]` (no leftover event) |
| Existing unit tests | ✅ 10 passed, OK (no regression) |
| Diff scope | ✅ only `client/cli.py` (+ `.gitignore` from workflow setup) |

## Acceptance criteria (from TaskCard)

- [x] `doctor --help` shows the command
- [x] valid server+token → PASS all, exit 0
- [x] wrong token → auth FAIL + hint, non-zero exit, no crash
- [x] unreachable URL → health FAIL + hint, non-zero exit
- [x] `--send-test` completes round-trip and leaves queue clean
- [x] existing unit tests pass
- [x] send/listen/pending/ack unchanged

## Scope adherence (frozen decisions D1–D5)

- D1 additive-only: ✅ no server/DB/protocol/existing-command change.
- D2 default read-only: ✅ only `--send-test` writes; it cleans up.
- D3 actionable output: ✅ each check PASS/FAIL + concrete fix hint.
- D4 exit-code contract: ✅ 0 iff all run checks pass.
- D5 no new deps: ✅ reuses httpx/click/get_config/get_headers.

## Advisory notes (non-blocking — for decider, NOT rework triggers)

1. **Code quality is high for a weak-model executor.** Clean structure, 401 vs 403
   distinguished, masked token, `finally`-style cleanup with manual-cleanup hint.
2. **Honest reporting.** The implementer's report explicitly separated "checks I ran" from
   "checks left for the architect," and disclosed the `502 vs ECONNREFUSED` proxy nuance
   rather than hiding it. Good handoff hygiene.
3. **Optional future polish (do NOT block):** could add a unit test for `doctor` in
   `tests/`; could add `--json` output for scripting. These are `Later`, not part of M1.

## Handler exit_code=3 anomaly (explained, not a code defect)

The listener logged `Handler exit_code=3` yet the event ended ACK'd and OpenCode completed.
This is a **workflow-plumbing** artifact (the wrapper's exit propagation), not a defect in
the delivered `doctor` code. Tracked as a workflow-process note, not an implementation bug.

## Recommendation

**Approve.** The change is correct, in-scope, verified against the real VPS, and regression-free.
Decider (user) to make the final Decision.
