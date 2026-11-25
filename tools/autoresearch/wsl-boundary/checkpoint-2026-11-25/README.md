# Optimization checkpoint, 2026-11-25

This archive preserves unfinished experiments for review and resumption. No candidate is promoted. It contains patches, source identities and small evidence files. Binaries, profiles, source trees and large build output are excluded.

`manifest.json` records each artifact's SHA256 and size. Copied artifacts also record their original repository-relative path and SHA256. Generated patches and identities record their source files. The manifest excludes itself. Historical absolute paths in copied evidence identify the original machine; they are not portable setup instructions. Original READMEs and proof statuses are preserved as dated records and can lag later evidence.

| Directory | Base and exact source | Evidence and gap |
| --- | --- | --- |
| `status/` | b2de070; d5b05 below | Native parity and worker checks passed. Six valid GUI processes cover Linux GUI → Windows Git. Final 20-repetition WT median: 1839 → 1220.5 ms; p95: 1974 → 1283 ms. Full four-cell matrix and OS-cold scenarios remain incomplete. |
| `native-helper/` | b2de070; 252dec below | Host 41 tests and 16 embedded tests passed; source cross-check passed. Both GUIs built. Authoritative completion is in `native-helper/vm-checkpoint/readiness.json`. Linux GUI → Windows cache/lifecycle gates passed. The retained long-path error also occurs in the unchanged baseline. Reverse runtime gates, corrupted-response client fault injection and GUI latency remain unverified. |
| `staged-anchor/` | 1135a59; aba80d below | Host 78 GUI tests, 30 worker unit tests and one stdio test passed; one GUI test remains ignored. Protocol 2 requires matching rebuilt workers. Native builds, runtime and timing remain pending. |
| `ui-phase-probe/` | Injector SHA in `host-proof.json` | Syntax and mock checks passed. Native execution and timing remain unverified. Diagnostic only. Keep the canonical two completion frames. |
| `comment-jump-refresh/` | Combined-v3 snapshot below | Host tests and build passed in the original record. Native behavior and latency remain unverified. The new focused test is included separately from the product patch. |
| `discarded-pane-reuse/` | Combined-v3 snapshot below | Discarded after four valid pilot processes missed the 10% WT improvement gate. WT median 444 → 475 ms. No 20-repetition run or promotion. New lifecycle test source is included in its patch. |

Exact scorer app source hashes:

- Status: `d5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb`.
- Status baseline: `56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272`.
- Native helper: `252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500`.
- Staged anchor: `aba80d9202698734d4915c9b652d58406e3602c1dc277983e97a7f6b59e80404`.
- Combined-v3: `0560a9511e83f27a55e7018ea59b0fe9b3864887a079eb7bf3e1f647743327ca`.
- Discarded pane reuse: `b1d14ea917f425c692de3f180f85291f0f80d5d11dda1c5aef7119f6b4ff9148`.

Full per-file identities are in `identities/`. b2de070 means `b2de070becf3fcba2d47557efd375221c586f273`; 1135a59 means `1135a59f3a51253709d652d1e4ec82fa8b32ce09`. Combined-v3 uses Git HEAD `82402a7087cdd54f2d84a7b064adab61f1bf8b00` plus its original source changes. A plain checkout of that old commit is not that snapshot.

The status patch was regenerated from exact d5b05 frozen bytes against b2de070 Git blobs. Older a137/0560 status artifacts are excluded. Fresh-process samples are not OS-cold. IPC remainders contain UI work, frames and waits; they do not prove paint cost. The 250 ms campaign target remains unmet.

## Resume from a checkout

From the repository root, use a relative archive path:

```sh
checkpoint=tools/autoresearch/wsl-boundary/checkpoint-2026-11-25
git apply --check "$checkpoint/status/candidate.patch"
```

`patch-checks.json` records successful independent apply checks for all five product patches against current 1135a59, plus exact reconstruction of each original frozen candidate's changed files. Those checks do not validate combined candidates or later revisions. Apply only the selected candidate in an isolated branch after reviewing its base and patch. Do not concatenate these independent patches. Applying a b2de070 patch on 1135a59 changes the full source identity; rebuild and rerun applicable correctness and scoring checks.

The separate comment test belongs at `frontend/comment-jump-refresh.test.js`. Run the UI probe's `node --check inject.js` and `node check.mjs` from its archive directory. Recreate native build paths for the current machine using the source identities and pinned workload controls. Do not execute historical supervisors or assume recorded PIDs still exist. Check current VM ownership before native builds, runtime checks or timing.
