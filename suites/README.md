# Suites

Every suite owns an independent input projection, oracle context, version, metrics and hard gates. Sharing a `TaskSpec` or checkpoint does not permit sharing semantic conclusions.

- Auto-Zoning consumes task-ready source and request projections.
- Auto-Refactoring consumes candidate snapshots and independently validates any SUT safety claim.
