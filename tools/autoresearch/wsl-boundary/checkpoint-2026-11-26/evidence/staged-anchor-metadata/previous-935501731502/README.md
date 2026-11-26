# Staged-anchor metadata experiment

This isolated source adds a typed metadata proof for unchanged exact Staged M
review anchors. It avoids frozen patch generation and all worktree content reads
when the saved HEAD/index blob and mode facts still match. The existing scoped
and full comparison lookup remains the fallback.

`source/` is a detached clone with its own Git metadata pinned to 1135a59. Root
production source, scoring controls and VM state are unchanged. This candidate is
unmeasured and unpromoted. No performance improvement is claimed.

The Interface is `git::verify_staged_versions(repo, checkout, expected)` returning
an optional `StagedProof`. The proof contains verified versions, base and a
`staged:` location fingerprint. It has no Comparison, Change, patch sections or
conversion into patch/search snapshot identity. Lookup tries an existing displayed
WT comparison first, then batches staged metadata once, then uses existing lookup.

The implementation refreshes stage0 index entries, checks exact raw index and
HEAD-tree path spelling, accepts regular modified modes including chmod-only,
and rejects conflicts, requested skip-worktree, intent-to-add, unsupported modes,
stale checkout/HEAD/index state or unsupported native formats. Sparse omissions
outside requested paths remain eligible. It never hashes or converts worktree
files; clean filters and working-tree encodings cannot change staged OIDs.

Protocol is 2. Both platform workers must be rebuilt from this candidate and
embedded in corresponding GUI builds. Old protocol 1 workers, including preserved
6a/328 artifacts or old BRANCHLINE_GIT_WORKER_PATH overrides, are incompatible;
the existing Hello check rejects them before a new operation is sent. Never
package this candidate using an old worker merely because the GUI builds.

Evidence:

- `candidate.patch`: narrow seven-file patch against pinned HEAD.
- `source.json`: canonical scorer source identity, excluding target artifacts.
- `baseline.json`: base revision and root source status when isolated.
- `proof.json`: checks, logs, decisions and remaining uncertainty.
- `gui-rust-tests-final-serial.log`: 77 passed, 1 existing ignored on exact final source. Requires local loopback
  permission for existing MCP socket fixtures. The initial sandbox attempt's
  EPERM failures are preserved in `gui-rust-tests.log`. Exact final source
  parallel rerun (76 passed, 1 failed, 1 ignored) hit an existing fixture ETXTBSY;
  the serial full-suite retry passed without source changes.
- `worker-tests-final.log`: 30 unit tests and 1 real persistent-stdio test passed.

Host GUI command, from source/ (CARGO_BUILD_JOBS=1):

```sh
CARGO_BUILD_JOBS=1 \
CARGO_TARGET_DIR=/home/max/workspace/merge-viewer-native/src-tauri/target \
PKG_CONFIG_PATH=/home/max/workspace/merge-viewer-native/build/linux-dev/root/usr/lib/x86_64-linux-gnu/pkgconfig \
LIBRARY_PATH=/home/max/workspace/merge-viewer-native/build/linux-dev/root/usr/lib/x86_64-linux-gnu \
LD_LIBRARY_PATH=/home/max/workspace/merge-viewer-native/build/linux-dev/root/usr/lib/x86_64-linux-gnu \
cargo test --offline --manifest-path src-tauri/Cargo.toml --lib
CARGO_BUILD_JOBS=1 cargo test --offline --manifest-path src-tauri/git-worker/Cargo.toml
```

Remaining work requires root's explicit VM release: matching opposite-OS worker
builds, native-platform tests and serial backend/GUI measurements using the pinned
kernel workload and canonical controls. Deterministic mid-read HEAD/index races
are untested because existing code has no mutation seam; no production test hook
was added solely to manufacture such races. Restaging and stale HEAD are covered.

## Prepared native build

The build remains unexecuted. Wait for root's exact `VM STAGED BUILD RELEASED`
message. Current VM ownership belongs to the helper-placement checks/builds.

From the host repository root, build workers, run native checks and build Linux
GUI first with:

```sh
python3 -u build/experiments/staged-anchor-metadata/build-after-release.py --release 'VM STAGED BUILD RELEASED'
```

To include Windows GUI immediately after Linux GUI under the same supervisor,
add `--windows-gui`. No build or GUI timing may overlap this supervisor. The
launcher validates and reuses the unchanged host proof; it does not repeat host
tests. Both workers are rebuilt from the frozen candidate, using the existing
VM worker target cache, static GNU Linux recipe and MSVC/XWIN recipe. Linux GUI
embeds the new PE; optional Windows GUI embeds the new ELF. Both embeddings are
verified byte for byte.

`build-plan.json` pins source, portable Git metadata, host proof/log hashes,
kernel fingerprint and owned VM paths. `input-tar.json` pins the prepared input
tar and scripts. The portable metadata includes the pinned commit's objects;
it has no host-only Git alternates dependency. `vm-build-supervisor.py` performs
all VM phases serially and records command argv, cwd, environment settings,
child PID/start identity, logs, binary hashes and fixture state.

Native Windows validation executes the rebuilt worker unit-test PE from NTFS.
The cross-built stdio integration-test PE is deliberately excluded because its
embedded Cargo child path names the Linux build directory. A separate real
persistent-pipe check launches the actual rebuilt PE against the NTFS kernel,
requires protocol 2 and Windows OS, verifies all five staged versions, and checks
unchanged Hello PID through the final request. The Linux worker receives its
native unit/stdio checks and corresponding kernel proof.

Kernel fingerprint reads use each volume's native Git with optional locks and
diff auto-refresh disabled. Raw index, HEAD and config bytes/stat metadata must
match before and after all work, including a failed build. Only independent
temporary unit-test fixtures may mutate. No cache refresh, fixture preparation,
kernel reset or configuration write is performed.

Prepared output paths use label `staged-anchor-metadata-935501731502`:

- VM record/logs: `/home/max/benchmarks/branchline-boundary/staged-anchor-metadata-935501731502-native/`
- Linux GUI: `/home/max/benchmarks/branchline-boundary/binaries/staged-anchor-metadata-935501731502/branchline`
- Windows GUI/worker/tests: `C:/Users/max/branchline-bench/binaries/staged-anchor-metadata-935501731502/`
- Host ownership/log record, created only after release: `native-build-supervisor.json`.
