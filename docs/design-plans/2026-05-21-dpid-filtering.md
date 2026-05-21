# Per-Agg-Type DPID Filtering Design

## Summary

pyAggregate aggregates SAS data files from multiple data partners (DPs) into Parquet outputs, using a TOML config to define what gets aggregated and where outputs go. Currently, every agg type processes all data partners found in the catalog — there is no mechanism to restrict a given aggregation run to a specific subset of DPs.

This design adds a required `allowed_dpids` field to each `[agg.<name>]` config block, giving operators explicit control over which data partners are included per aggregation type. The field accepts either a list of lowercase DPID strings (e.g., `["msoc", "nsdp"]`) or the wildcard `["*"]` to preserve current all-inclusive behaviour. The filtering is applied as a single pure function inserted into the existing input resolution pipeline — between the catalog filter and the latest-workplan selection step — so scan behaviour, the catalog itself, and all downstream outputs (dpid_map, manifest) are untouched. Unknown DPIDs in the config produce structured log warnings rather than hard failures, following the same contract as existing collision detection.

## Definition of Done
- Every `[agg.<name>]` block in the TOML config requires an `allowed_dpids` field — a list of lowercase DPID strings, or `["*"]` for all DPs. Missing = validation error.
- During aggregation, only DPs present in `allowed_dpids` are included in the run. The wildcard `["*"]` disables filtering. An empty list `[]` produces no output.
- If any DPID in the config doesn't match a DPID found in the catalog, a structured warning is logged.
- Scan behaviour is completely unchanged — the catalog contains all DPs regardless.
- Existing downstream filtering (dpid_map, manifest, etc.) continues to work correctly with no modifications.

## Acceptance Criteria

### dpid-filtering.AC1: Config requires allowed_dpids
- **dpid-filtering.AC1.1 Success:** `allowed_dpids = ["msoc", "nsdp"]` parses into `tuple[str, ...]`
- **dpid-filtering.AC1.2 Success:** `allowed_dpids = ["*"]` parses without error
- **dpid-filtering.AC1.3 Success:** `allowed_dpids = []` parses without error
- **dpid-filtering.AC1.4 Failure:** Missing `allowed_dpids` raises `ValueError` with descriptive message
- **dpid-filtering.AC1.5 Failure:** Non-list value for `allowed_dpids` raises `ValueError`

### dpid-filtering.AC2: Filtering limits aggregation to allowed DPs
- **dpid-filtering.AC2.1 Success:** Specific DPIDs filter catalog to only matching rows
- **dpid-filtering.AC2.2 Success:** Wildcard `["*"]` returns catalog unchanged
- **dpid-filtering.AC2.3 Edge:** Empty list `[]` returns empty DataFrame
- **dpid-filtering.AC2.4 Edge:** All columns preserved after filtering (schema unchanged)
- **dpid-filtering.AC2.5 Edge:** DPID in allowed list but not in catalog produces empty result for that DPID (no error)

### dpid-filtering.AC3: Unknown DPIDs produce structured warnings
- **dpid-filtering.AC3.1 Success:** DPID in config but not in catalog generates warning string
- **dpid-filtering.AC3.2 Success:** Wildcard skips unknown-DPID check entirely (no warnings)
- **dpid-filtering.AC3.3 Success:** All DPIDs found in catalog produces no warnings

### dpid-filtering.AC4: End-to-end pipeline integration
- **dpid-filtering.AC4.1 Success:** `resolve_inputs` applies DPID filter between `filter_catalog` and `select_latest_workplan_per_dp`
- **dpid-filtering.AC4.2 Success:** CLI run command logs warnings for unknown DPIDs via structured logger
- **dpid-filtering.AC4.3 Success:** Downstream outputs (dpid_map, manifest) naturally exclude filtered-out DPs without code changes

### dpid-filtering.AC5: Scan behaviour unchanged
- **dpid-filtering.AC5.1 Success:** Scan catalogs all DPs regardless of any `allowed_dpids` config

## Glossary

- **DPID (Data Partner ID)**: A lowercase string identifier for a data partner — a source organisation that supplies SAS input files. Derived from file paths and stored in the catalog.
- **Agg type**: A named aggregation configuration block (`[agg.<name>]` in TOML), such as `qa`, `qm`, or `snapshot`. Each defines its own output path, request type filter, and now its own `allowed_dpids` list.
- **Catalog**: A SQLite database (managed by the scanner) that records discovered data partner workplans and their metadata. The catalog is the input to the aggregation pipeline — scan populates it, run reads it.
- **Workplan**: A catalogued entry representing a specific data partner's input data at a point in time. The pipeline selects the latest workplan per DP before resolving file inputs.
- **`resolve_inputs`**: The orchestration function in `input_resolver.py` that chains catalog filtering, DPID filtering, latest-workplan selection, and file globbing into the final set of table inputs for a run.
- **`filter_catalog`**: An existing pure function that filters the catalog by request type and source field before DPID filtering is applied.
- **`select_latest_workplan_per_dp`**: An existing pure function that, after catalog filtering, selects the most recent workplan entry per data partner.
- **dpid_map**: A per-run mapping from DPID to surrogate identifier used in masked outputs. Already filtered downstream to only DPs that appear in aggregated outputs — no changes needed.
- **FCIS (Functional Core / Imperative Shell)**: The architectural pattern used throughout the codebase. Pure business logic (no I/O, no side effects) lives in `core/`; orchestration and I/O live in `io/`; side effects like logging live in `cli.py`.
- **Frozen dataclass**: A Python `@dataclass(frozen=True)` — instances are immutable after construction. All config types in pyAggregate use this pattern.
- **Polars**: The DataFrame library used for in-memory data manipulation. The catalog snapshot is loaded as a Polars DataFrame and filtered using Polars expressions.
- **Structured logging**: Log records emitted with an `extra` dict of machine-readable fields alongside the human-readable message, enabling downstream log aggregation and filtering.
- **Wildcard (`["*"]`)**: A sentinel value for `allowed_dpids` meaning "include all data partners" — preserves the current default behaviour without requiring operators to enumerate every DPID.

## Architecture

Per-agg-type DPID filtering adds a required `allowed_dpids` field to each `[agg.<name>]` TOML config block. The field accepts a list of lowercase DPID strings or the wildcard `["*"]`. Filtering is applied at aggregation time in the input resolution layer — scanning remains unchanged and catalogs all data partners regardless.

### Components

**Config layer** (`src/pyaggregate/config.py`):
- `AggTypeConfig` gains `allowed_dpids: tuple[str, ...]` (required, no default)
- `load_config` validates presence and parses from TOML list to tuple
- Missing field raises `ValueError` with a clear error message

**Filtering layer** (`src/pyaggregate/core/input_resolution.py`):
- `filter_allowed_dpids(catalog: pl.DataFrame, allowed_dpids: tuple[str, ...]) -> pl.DataFrame` — pure function that returns catalog unchanged if `"*"` is in the tuple, otherwise filters to rows where `dpid` is in the allowed set. Empty tuple yields empty DataFrame.
- `check_unknown_dpids(allowed_dpids: tuple[str, ...], catalog_dpids: set[str]) -> list[str]` — pure function that returns warning strings for any allowed DPID not found in the catalog. Returns empty list if wildcard is present.

**Orchestration** (`src/pyaggregate/io/input_resolver.py`):
- `resolve_inputs` filter chain becomes: `filter_catalog` → `filter_allowed_dpids` → `select_latest_workplan_per_dp`
- No signature changes to `resolve_inputs`

**Warning logging** (`src/pyaggregate/cli.py`):
- Run command extracts unique DPIDs from catalog snapshot
- Calls `check_unknown_dpids` per agg type before `resolve_inputs`
- Logs warnings via `logging.getLogger("pyaggregate")` with structured `extra` fields

### Data Flow

```
TOML config
  └─ load_config parses allowed_dpids into AggTypeConfig
       │
catalog snapshot (all DPs)
  └─ cli.py: check_unknown_dpids(allowed_dpids, catalog_dpids) → log warnings
  └─ resolve_inputs:
       ├─ filter_catalog (reqtype/source_field filter)
       ├─ filter_allowed_dpids (DPID allowlist filter)  ← NEW
       ├─ select_latest_workplan_per_dp
       └─ glob + group → table inputs
            │
aggregation + write (unchanged)
  └─ dpid_map filtering naturally excludes non-aggregated DPs
```

### Unchanged Components

- Scanner (`src/pyaggregate/io/scanner.py`) — catalogs all DPs regardless
- Writer (`src/pyaggregate/io/writer.py`) — `filter_dpid_map` already filters to surrogates present in masked outputs
- Manifest generation — derived from aggregated outputs
- Catalog store (`src/pyaggregate/io/catalog_store.py`) — no schema changes

## Existing Patterns

This design follows established codebase patterns:

- **FCIS separation**: Pure filtering functions in `core/input_resolution.py`, orchestration in `io/input_resolver.py`, side effects (logging) in `cli.py`. Same boundary as existing `filter_catalog` / `select_latest_workplan_per_dp` / `detect_snapshot_collisions`.
- **Frozen dataclasses**: `AggTypeConfig` is `@dataclass(frozen=True)`. New field follows same immutability guarantee.
- **Tuple for list config**: `exclude_from_rollup` uses `tuple[str, ...]` parsed from TOML list. `allowed_dpids` uses identical pattern.
- **Pure validation returning warnings**: `detect_snapshot_collisions` returns `list[str]` of warning messages. `check_unknown_dpids` follows the same contract.
- **Structured JSON logging**: Existing run command uses `logging.getLogger("pyaggregate.run.inputs")` with `extra` fields.

No new patterns introduced. No divergence from existing conventions.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Config Field and Validation

**Goal:** Add `allowed_dpids` as a required field on `AggTypeConfig` and validate it during config loading.

**Components:**
- `AggTypeConfig` in `src/pyaggregate/config.py` — new `allowed_dpids: tuple[str, ...]` field
- `load_config` in `src/pyaggregate/config.py` — parse and validate the field (missing = `ValueError`)
- `pyaggregate.example.toml` — updated to show `allowed_dpids` on every `[agg.<name>]` block
- Config tests in `tests/test_config.py` — parse success, missing field error, wildcard and empty list

**Dependencies:** None

**Done when:** `dpid-filtering.AC1.1` through `dpid-filtering.AC1.5` pass. Config with `allowed_dpids` parses correctly; config without it raises `ValueError`; wildcard and empty list both parse without error.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Filtering and Warning Functions

**Goal:** Implement the pure DPID filtering and unknown-DPID warning functions in the Functional Core.

**Components:**
- `filter_allowed_dpids` in `src/pyaggregate/core/input_resolution.py` — pure DataFrame filter
- `check_unknown_dpids` in `src/pyaggregate/core/input_resolution.py` — pure warning generator
- Unit tests in `tests/test_input_resolution.py` — wildcard passthrough, specific filtering, empty tuple, column preservation, unknown DPID warnings

**Dependencies:** Phase 1 (AggTypeConfig must have `allowed_dpids` field)

**Done when:** `dpid-filtering.AC2.1` through `dpid-filtering.AC2.5` and `dpid-filtering.AC3.1` through `dpid-filtering.AC3.3` pass. Pure functions correctly filter DataFrames and generate warning strings.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Orchestration Wiring

**Goal:** Wire the new functions into the input resolution chain and CLI warning logging.

**Components:**
- `resolve_inputs` in `src/pyaggregate/io/input_resolver.py` — insert `filter_allowed_dpids` call between `filter_catalog` and `select_latest_workplan_per_dp`
- `run` command in `src/pyaggregate/cli.py` — extract catalog DPIDs, call `check_unknown_dpids` per agg type, log warnings
- Integration test in `tests/test_input_resolution.py` — `TestResolveInputs` case verifying allowed_dpids filtering applies before globbing
- Existing test fixtures updated to include `allowed_dpids` in AggTypeConfig construction

**Dependencies:** Phase 1, Phase 2

**Done when:** `dpid-filtering.AC4.1` through `dpid-filtering.AC4.3` pass. Full pipeline correctly filters by allowed DPIDs and logs warnings for unknown DPIDs.
<!-- END_PHASE_3 -->

## Additional Considerations

**Case sensitivity:** DPIDs are lowercase in file paths (and therefore in the catalog) but may appear capitalised in table data. The `allowed_dpids` config values match against the catalog's path-derived lowercase values. This should be documented in the example TOML with a comment.

**Overlapping DPIDs across instances:** The same DPID may appear in `allowed_dpids` for multiple agg configs (or across separate pyAggregate instances sharing a catalog). This is explicitly supported — each agg type filters independently.
