# Read-only planning output v2 and product accounting

The model supplies only likely_reads, likely_writes, diagnosis, changes, tests and evidence. The host binds benchmark task_id and optional logical_task_id separately in planning-ab-result/2.
A whole JSON object, optionally inside one complete Markdown JSON fence, is an explicit transport format. Malformed JSON, duplicate fields, model-supplied identity/authority, invalid paths and invalid evidence lines are rejected. No response repair or write permission is introduced. Raw response hash and wire format are retained.

The existing event parser counts source.read as well as read. An assistant response without a final stop cannot become execution_success merely via exit zero and agent_end. Legacy terminal-only event fixtures remain supported; an earlier failed provider attempt does not poison a later confirmed stop.

## Executed local validation

- The five new accounting failures were reproduced on the previous implementation.
- Focused contract/accounting/event suite: 42 passed.
- Complete repository suite: 461 passed, 3 existing optional integration skips, 1 pre-existing SyntaxWarning.
- Wheel and source distribution built. Parser/accounting bytes in the wheel match tested source files. Build dependencies were isolated outside all live/shared environments.
- No model calls, historical-result edits or changes to production write admission.

This versioned experiment protocol does not rescore the original sealed A/B. The next campaign must use v2 instructions and equal execution budgets for both arms. Format validity is not semantic correctness or authority.
