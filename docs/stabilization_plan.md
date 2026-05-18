# Stabilization Plan

## Scope

Create a clean baseline for Robocoater V9 without refactoring or changing operational Python code.

## Sequence

1. Establish repository structure and Git hygiene.
2. Preserve antisolvent and gas quench V9 code as-is.
3. Track critical model and calibration artifacts needed by the current code.
4. Exclude generated campaign outputs, caches, local environments, and temporary logs.
5. Document known issues before changing behavior in future stabilization work.

## Baseline exit criteria

- Top-level V9 folders are present.
- Starter documentation exists.
- `.gitignore` prevents generated output and local files from entering Git.
- Human review approves the tracked and ignored file set before the first commit.
