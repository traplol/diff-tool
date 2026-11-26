# Native index-path experiment

This isolated candidate removes work needed only to locate the index filename.
It retains the native repository handle before sparse-checkout policy selection
and uses its private Git directory plus `index`, without opening the index.
`GIT_INDEX_FILE`, `GIT_DIR`, or `GIT_COMMON_DIR` selects the existing Git lookup.
Missing native access also selects that fallback. The working-tree backend
policy, checkout/index consistency checks, frozen outputs and protocol remain
unchanged. There is no new cache or configuration.

`source/` has owned Git metadata at exact b2de070, all 181 tracked files and no
alternates. `baseline-source.json` records the canonical 49-file baseline
identity. `source.json` records the candidate. `baseline-tracked.json` and
`tracked-source.json` cover all 181 files. Only `src-tauri/src/git.rs` and
`src-tauri/src/git_tests.rs` change; `candidate.patch` contains the complete diff.
Production source and canonical controls are untouched. No VM execution or
performance claim is included.

The tests extend sparse-checkout coverage and check linked-worktree private
indexes, Git fallback selection and filename resolution with an invalid
index. The fallback test uses an explicit boolean instead of changing global
environment variables. See `TEST_PLAN.md` for the remaining native checks.

The first host worker invocation reused stale Cargo outputs and ran the old 25
tests. The fresh-producer gate rejected it before GUI tests. Its evidence stays
in `host-gates.json` and `worker-tests.log`. R2 cleans only the worker/app root
packages in the shared target caches, retaining dependencies. It requires exact
candidate manifest paths, `fresh:false` test producers, matching `Compiling`
paths and the new regression name. R2 evidence is in `host-gates-r2.json` and
the `*-r2.log` files.

Host results: 26 worker unit tests and one persistent-stdio test pass. The GUI
suite passes 66 tests with one existing ignored test in the sandbox. Five
existing listener fixtures require local loopback permission; all five pass
when rerun against the same fresh R2 executable with its SHA256 pinned. That
separate evidence is in `gui-loopback-recheck.json` and its log. The GUI suite
therefore has 71 passing tests and one existing ignored test across those
checks. Canonical source bytes remain unchanged throughout.

A fresh KISS-only agent, `/root/open_path_review/index_path_kiss`, reviewed the
final source diff without inherited context and returned `simple enough`.
No commit was made; Git HEAD remains the exact baseline.
