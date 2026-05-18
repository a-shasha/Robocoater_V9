# Decision Log

## 2026-05-18

- Use a controlled top-level monorepo structure for V9 stabilization.
- Move `Self_Driving_V9` to `antisolvent_v9/` without editing Python source.
- Move `Self_Driving_V9_GQ` to `gas_quench_v9/` without editing Python source.
- Track V9 `.joblib` model artifacts because current film classification code loads them.
- Ignore campaign outputs, generated analysis outputs, Python caches, editor state, local environments, temporary logs, and imported legacy workspaces unless later approved.
