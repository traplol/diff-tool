# Validation plan

Host Rust gates must run serially after root releases host resources. The
initial live GUI series ended before any candidate test or build was started.
Use the candidate manifests and the existing shared dependency caches. Clean
only package `branchline-git-worker` in the worker target and package
`branchline` in the GUI target before each suite. Retain JSON compiler records
and require exact candidate manifests, executable test artifacts with
`fresh:false`, the exact `Compiling` path and the added regression name.
Canonical 49-file source identity must match before and after both suites.

The worker unit and persistent-stdio suites cover the shared Git implementation.
The GUI library suite covers note tracking and review integration. Both suites
include these targeted cases:

- Existing sparse-checkout parity compares complete metadata and frozen
  patches/content with Git, then verifies index bytes, mtime and inode.
- The sparse test now verifies index-path resolution remains available when
  native working-tree reads are disabled.
- A linked worktree must select its private Git directory's index, distinct
  from the main repository's index and the common directory's index.
- The override branch must ignore a supplied native handle and use Git's
  repository root. Missing native access must use the same fallback.
- Replacing the private index with invalid bytes must not prevent filename
  resolution. Filename lookup must not open or parse index entries.
- Existing snapshot tests retain old patches after worktree/index changes and
  reject stale checkout metadata after a commit.

No frontend files change, so frontend tests add no targeted coverage.

Before promotion, use a separately authorized native slot to rebuild the exact
worker and matching GUI. Retain fresh producer records and verify the embedded
worker bytes. On both operating systems, check real isolated-child environment
overrides for `GIT_INDEX_FILE`, `GIT_DIR` and `GIT_COMMON_DIR` without changing
the test runner's environment. Confirm the selected index path against Git for
ordinary, sparse and linked worktrees. Keep native fixture HEAD/config/index
bytes and stat guards unchanged. Run the unchanged canonical GUI comparison
with fresh Open, first use and repeated samples kept separate. Host tests and
the removed subprocess do not establish an end-to-end improvement.
