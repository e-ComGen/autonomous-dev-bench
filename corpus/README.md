# Corpus

Public project manifests pin a full Git commit, deterministic source-tree SHA-256, license digest and dependency specifications. Materialization must recompute and compare the source digest before a scenario is valid.

Public project identity does not make a benchmark instance hidden. Exact task overlays, mutation parameters/seeds, expected labels and oracle material for sealed campaigns live in a separate private store. They must not be committed here or mounted into the SUT workspace.

Project adapters may resolve bootstrap commands only. Capability expectations belong to suite-owned oracle contexts.
