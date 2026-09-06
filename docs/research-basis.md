# Research basis

Implementation decisions are grounded in the supplied architectural specification `benchmark-info.md` (the provided deep research report for the shared benchmark platform) and the available subsystem verification report at `../autorefactoring/deep-research-report (79).md`.

The optional Design-Form report `(72)` was not present in the accessible workspace. Current production implementations were therefore inspected directly and take precedence:

- Auto-Refactoring v0.10 exposes `auto_refactoring.design_form.ArchitectureQualityService`; whole-engine evaluation uses benchmark-owned subprocess adapters for the production CLIs because result/status families differ by layer and production self-certification cannot be trusted as an oracle.
- Auto-Zoning v0.6 exposes a read-only `RepositorySemanticFrontend` and pure `build_projection`; semantic output is proposal-only, partial, and carries no write authority. The benchmark preserves that uncertainty rather than promoting it to accepted ownership.

The design-research corpus service was invoked before architecture was fixed, but its RAG backends timed out. No unsupported claims were taken from that failed synthesis; the local reports and direct implementation inspection are the grounding sources.
