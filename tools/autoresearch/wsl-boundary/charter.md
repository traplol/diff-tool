# Windows and WSL repository boundaries

Status: setup and baseline calibration. The scorer contract remains provisional
until all four baseline cells and the failure checks run successfully.

## Objective

Make Branchline review interactions responsive across the Windows/WSL filesystem
boundary. The primary target is less than 250 ms for opening a review, branch comparisons,
switching into and out of the working-tree view, and jumping from a comment to
its correct visible diff location. Cross-boundary performance is the priority.

## Source and environment

- Starting source: `82402a7087cdd54f2d84a7b064adab61f1bf8b00`.
- Campaign branch: `codex/wsl-boundary-perf`.
- Canonical controls: `tools/autoresearch/wsl-boundary/` in this checkout.
- Runtime artifacts: `/home/max/benchmarks/branchline-boundary` in Ubuntu WSL;
  `C:\Users\max\branchline-bench` in Windows. Do not use the user's `test-repo`.
- QEMU Windows VM, Ubuntu-26.04 WSL2. Record Windows/WSL resource allocations,
  versions, app hashes and default rendering settings with each comparison.
- Actual packaged release builds, including frontend assets. No mock backend,
  Linux-only substitute for a Windows executable, or forced special renderer.

## Matrix

| App | Repository storage | Classification |
| --- | --- | --- |
| Windows executable | WSL ext4 via `\\wsl.localhost\Ubuntu-26.04\...` | Primary cross-boundary target |
| WSL Linux app | Windows NTFS via `/mnt/c/...` | Primary cross-boundary target |
| Windows executable | Windows NTFS via `C:\...` | Same-side control |
| WSL Linux app | WSL ext4 via `/home/max/...` | Same-side control |

All cells use the same pinned kernel revision, branch commits, changed files,
working-tree state and review comments. Run resource-sensitive measurements
serially. Never compare results from different workload/source contracts.

## Workload

Linux v6.12, peeled commit `adc218676eef25575469234709c2d87185ca223a`, with
86,680 tracked files. Both replicas use identical sparse exclusions for names
that Windows cannot represent and case-colliding paths. Record the exact list
and materialized count in the fixture manifest; do not silently reduce the
workload. Add a deterministic two-layer review stack and staged, unstaged and
untracked changes. Generate all fixture data outside the timed interactions. Seed a first-layer
(non-checkout-branch) inline comment and a staged working-tree comment so both
comment destinations have strict, unambiguous correctness checks.

## Measurement boundary

Time the actual UI action with the app's monotonic browser clock, through the
native Tauri backend, until the correct file, comparison, diff contents and
comment (when applicable) are visible, followed by two animation frames. A
cleared busy indicator alone is insufficient. Record native IPC sub-timings to
distinguish Git/backend work from rendering. Do not move required refresh or
comment-location work outside the timed interval to improve the score.

Measure repository-open latency separately from process startup and interactions.
Report the first interaction in a fresh process separately from repeated
interactions. Record warmup explicitly. Initial calibration uses at least three
fresh processes per matrix cell. Final repeated-interaction results require
at least 20 samples per action per cell, with raw samples, median, p95 and max.
No OS-wide cache flushing or unrelated service shutdowns on the user's machine.

## Correctness and acceptance

- Primary metric: worst p95 of review opening and the interaction types across both cross
  cells; minimize it. Target: every cross-cell interaction p95 < 250 ms, with
  max and first-use values reported rather than hidden.
- Same-side controls must remain correct and show no material regression; use
  a 10% threshold initially and investigate noise before promotion.
- Preserve exact patch content, staged/unstaged/untracked grouping, immutable
  snapshot behavior, comment anchors and export data.
- Comment jumps must remain correct after external edits, staging and commits.
- Run Rust tests, frontend tests and native workflow checks appropriate to each
  candidate; the final matrix must use the exact delivered source/build hashes.
- Invalid output, missing samples, errors, timeouts or stale artifacts invalidate
  a run. The scorer must reject controlled failure cases before contract freeze.

## Experiments and stopping

The user specified a performance target, so continue measured experiments toward
that target. Change one hypothesis at a time. Keep source snapshots and patches;
freeze evaluation controls before the first production change. Retain a candidate
only after correctness gates pass and improvement exceeds measurement noise.
Record unsuccessful and infrastructure experiments too. Preserve the user's
checkout, existing review databases, open applications and unrelated VM state.

The campaign completes only when the matrix and correctness gates demonstrate
the target, or remains active with an exact checkpoint and next action when
further work is needed. Do not claim a backend-only timing as end-to-end latency.
