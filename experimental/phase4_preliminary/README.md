# Experimental Preliminary Phase 4 Modules

**Status:** ISOLATED & UNAUTHORIZED FOR PRODUCTION
**Isolation Date:** November 1, 2026
**Reference:** `PRE_PHASE_4_FORENSIC_AUDIT.md` Section 14 (DEFECT-08) & Phase 3 Remediation Specification

## Purpose
This directory contains preliminary Phase 4 decision logic (Directional Scoring Engine A, Trade Setup Engine B, Setup Lifecycle Tracker, and Decision Orchestrator) along with their corresponding test files.

These modules were isolated from `backend/decision/` and `tests/` to prevent unauthorized execution or exposure as active production functionality prior to formal Phase 4 authorization.

## Contents
- `backend/decision/`:
  - `scoring_engine.py`: Directional scoring across 6 factor groups.
  - `setup_engine.py`: Heuristic trade setup identification (4 patterns).
  - `lifecycle.py`: State machine for setup triggers, collisions, and expirations.
  - `orchestrator.py`: Pipeline runner.
  - `models.py`: Dataclasses and Pydantic models.
- `tests/`:
  - `test_decision_orchestrator.py`
  - `test_decision_scoring.py`
  - `test_setup_engine.py`
  - `test_setup_lifecycle.py`

## Invariants
1. No module in `backend/` or `analytical_engine/` may import from this directory.
2. No API route in `backend/main.py` may expose endpoints from this directory.
3. These modules will be reviewed and reintegrated only upon formal Phase 4 authorization.
