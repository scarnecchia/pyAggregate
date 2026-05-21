# Per-Run Manifest Implementation Plan — Phase 2

**Goal:** Verify manifest determinism through dedicated tests proving byte-identical output from identical inputs.

**Architecture:** Determinism is structurally guaranteed by Phase 1 (sorted table names, sorted output type keys, `sort_keys=True` in JSON serialization). This phase adds tests that prove the guarantee holds end-to-end.

**Tech Stack:** Python 3.11+, pytest

**Scope:** 2 phases from original design (phases 1-2)

**Codebase verified:** 2026-05-21

---

## Acceptance Criteria Coverage

This phase tests:

### per-run-manifest.AC5: Determinism
- **per-run-manifest.AC5.3 Success:** Two runs with identical data produce byte-identical manifests

---

<!-- START_TASK_1 -->
### Task 1: Test byte-identical manifests across runs

**Verifies:** per-run-manifest.AC5.3

**Files:**
- Modify: `tests/test_writer.py` (add test)

**Implementation:**

No production code changes. This task adds a test that proves end-to-end determinism.

**Testing:**

- per-run-manifest.AC5.3: Run `write_run` twice with identical inputs into two separate `tmp_path` subdirectories, read both `manifest.json` files as raw bytes, assert they are byte-identical

Test approach: Create two output paths under `tmp_path`. Call `write_run` with the same `table_outputs`, `dpid_map`, `agg_type`, and `run_id` for both. Read the resulting `manifest.json` files as raw strings and assert equality. This covers the full pipeline: dict construction, key sorting, JSON serialization.

Important: the two output paths must be different directories (e.g., `tmp_path / "run_a"` and `tmp_path / "run_b"`) so that each gets its own run directory. The manifest content should still be identical because it only contains relative paths and metadata derived from identical input data.

**Verification:**
Run: `pytest tests/test_writer.py -v -k byte_identical`
Expected: Test passes

**Commit:** `test: verify byte-identical manifests from identical inputs`
<!-- END_TASK_1 -->
