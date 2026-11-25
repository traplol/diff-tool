# Optimization checkpoint, 2026-11-25

Copied back from the Windows VM to host `ok`. This archive preserves the latest optimization work for review and resumption. Application code remains committed through `1135a59`; experimental patches remain separate. No new candidate is promoted by this checkpoint.

`manifest.json` records every artifact's SHA256 and size. Copied artifacts retain their original path and SHA256. Binaries, full source trees, profiles and large build output stay in the local `build/` directories. Historical absolute paths and PIDs identify recorded runs; do not execute old supervisors or use those PIDs as current ownership.

| Directory | Current result | Remaining work |
| --- | --- | --- |
| `status/` | Exact d5b05 source measured separately in all four GUI/storage combinations. Windows/NTFS WT p95 1501.7 → 956.9 ms; WSL/NTFS 1974 → 1283 ms. Windows/WSL repeated actions are below 250 ms. | WSL/ext4 branch-first maximum 480 → 544 ms exceeds the 10% guard. Cause remains unproved; the sample is retained. Opening and first use still miss the goal. No final combined-source matrix. |
| `native-helper/` | Exact 252dec source passes placement, corruption repair, fallback and lifecycle gates in both directions. Real malformed-response client tests prove native process cleanup before Connection Drop with pipes retained. | GUI A/B for absent and existing native helper caches. Both baseline and candidate have the retained long-path failure. |
| `staged-anchor/` | Exact aba80d source passes 78 GUI tests, 30 worker unit tests and one stdio test; one GUI test ignored. Protocol 2 needs both rebuilt workers. | Native attempt failed before building because extracted Git metadata was incomplete. A real-bundle packaging correction is prepared separately; native retry and timing are pending. |
| `parallel-untracked/` | Exact f15e85 source, based on d5b05, passes 32 worker tests, one stdio test and 77 GUI tests; one ignored. | Native parity and matched GUI measurements. |
| `stable-file-tree/` | Exact 69589c source passes frontend tests and Vite build. | Native behavior, independent KISS and timing. |
| `git-command-cost-trace/` | Exact e72a63 diagnostic separates Git command construction from child execution. | Unbuilt and unmeasured; diagnostic only. |
| `ui-phase-probe/` | Native diagnostics attribute about 77% of sampled WebKit process CPU to 12 llvmpipe workers. Observer overhead and original failures are preserved. | Diagnostics do not establish an optimization score. Normal graphics policy and completion frames remain unchanged. |
| `discarded-initial-geometry/` | Exact 071ee1 source passes native correctness gates. Four valid pilot processes show WT median 452 → 469 ms. | Discarded after failing the predefined continuation gate. No 20-repetition runs. |
| `comment-jump-refresh/` | Original combined-v3 source passes recorded host checks. | Native behavior and timing. |
| `discarded-pane-reuse/` | Four valid pilots show WT median 444 → 475 ms. | Discarded. Existing unified/split pane reuse remains. |

Fresh-process measurements are not OS-cold measurements. IPC remainders include UI work, frames and waits. The full 250 ms opening, first-use and cross-platform goal remains active and unmet.

## Reproduce source patches

The original five patches and their reconstruction checks remain in `patch-checks.json`. The new patch chains are checked in `followup-patch-checks.json`. Source identities record exact base commits and per-file hashes. Patches are independent experiments; do not concatenate them.

- Status, helper, geometry and file-tree patches start from `b2de070becf3fcba2d47557efd375221c586f273`.
- Parallel-untracked and Git-command-trace start from that base plus the archived exact status patch.
- Staged metadata starts from `1135a59f3a51253709d652d1e4ec82fa8b32ce09`.
- The original combined-v3 base and reconstruction instructions remain in the previous Git revision of this README and in `identities/`.

Apply a selected patch in an isolated checkout, rebuild the required workers and GUI, and rerun its pending gates. Applying a patch on a later revision changes its full source identity. Check current VM ownership before any native execution.
