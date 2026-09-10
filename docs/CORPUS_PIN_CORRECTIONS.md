# License-file pin correction

The first real one-click source preparation failed closed for all three projects.
Their pinned commits and complete source-tree digests matched; license-file digests did not.
No source, license text, dependency pin, test assertion or acceptance rule was changed.

Read-only audit at implementation commit e2bf5f090184710ed27bed2e2ea75f864fda3c0b:
GitHub Actions run 34130886776, Ubuntu job 101770455646, artifact 10022024116.
`tools/audit_corpus_pins.py` first verifies the existing whole-tree digest, then reads
license and dependency blobs from that exact commit using Git, without executing the project.
All six dependency-file digests already matched raw bytes. None of the three legacy
license pins matched either raw bytes or canonical-JSON text hashing.

Corrections use raw-byte SHA-256, matching the existing bootstrap file-pin convention:

| Project / file | Old suffix | Correct suffix |
|---|---|---|
| HTTPX / LICENSE.md | eb237e056a490d1f290e4dfa3cc342a04c64a89701385f86a847cdbe4d21957d | 4ec59d544f12b5f539a3a716fd321ac58ccd8030b465221f2c880200cdf28d8d |
| Pluggy / LICENSE | de91589cbcc498cb36d3f979e39d4fb1ea1164d5331f6e0ea90a986525310d51 | d6b65e6c213a5d0b577911d34d6e5949b9f59d76c238c5071a2f3fc16cfb2606 |
| Requests / LICENSE | 88046bf22d5b4f4b8cc85079ae6aae5424a3a1999db952ed152828ff325b2c6d | 09e8a9bcec8067104652c168685ab0931e7868f9c8284b66f5ae6edae5f1130b |

ProjectSpec content identities change as intended. Historical evidence is not relabelled
as evidence for the corrected manifests. Whole-tree, license and dependency checks stay strict.
The audit now fails CI if any recorded file pin differs from the exact Git bytes.
