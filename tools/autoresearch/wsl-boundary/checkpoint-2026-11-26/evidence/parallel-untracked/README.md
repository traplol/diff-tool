# Bounded parallel untracked captures

This isolated experiment follows the exact stateless-status source `d5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb`.
Candidate source: `f15e85e1ec50af3bdc82e792a4d2d1189b67f4e56375679d88e0b035fe587a0f`.
`source/` retains the baseline's pinned b2de070 Git metadata. `baseline-source.json`,
`source.json`, and `candidate.patch` record the exact two-file difference.
Main source and canonical controls are unchanged. No native build, VM call,
benchmark, commit, or promotion occurred.

Hypothesis: the per-file no-index captures remain on the critical path after
untracked discovery completes. In `src-tauri/src/git.rs`, `working_changes_cli`
now processes Git's existing listing in chunks of four, joins every capture in
that chunk, and handles results in listing order. An error prevents later chunks
from starting. The private `untracked_changes` helper contains the former
per-path body, including the symlink temporary directory's lifetime. Command
arguments, partial staging, literal path handling, filters, discovery, first-four
capture concurrency, protocol, and checkout/index guards retain their behavior.
No worker request runs concurrently with another request.

Host correctness passes: 32 worker unit tests, one actual persistent-stdio test,
and 77 GUI-library tests with one existing ignored test. The two new tests cover
more than four mixed entries, Git listing order, exact regular-file metadata/raw
patch parity with one-at-a-time Git captures, empty/binary files, a nested Git
repository, a directory symlink on Unix, frozen output after deletion and staging,
and two unreadable files retaining the first listing error. Binary-content
errors are compared as frozen results. Existing suites cover partial staging,
conflicts, sparse fallback, literal/byte paths and read-only index behavior.
A fresh independent KISS auditor found the final patch "simple enough".

Initial failed test-oracle logs are retained. The first oracle omitted the old
no-index `./` path normalization. The second incorrectly unwrapped the expected
binary file_contents error. Production extraction did not change during either
correction. The first GUI suite retained five sandbox loopback-denial failures;
the same source passed with local loopback available. See `proof.json` and logs.
Native Windows behavior and latency remain untested. There is no speed claim.

## Existing evidence and rank

1. Parallel untracked capture is distinct from existing candidates. The saved
   direct Windows diagnostic (`../windows-wt-trace2/summary.json`, untraced
   cycle0) measured five serial no-index child wall times totaling248.2ms.
   `git.rs` baseline lines1312-1403 run those only after all first four reads
   join. These are read-only independent snapshots of separate paths. Their
   exact saved output and list order remain necessary. A two-batch schedule has
   an ideal lower wall cost around102.1ms for those old single-process durations;
   shared-resource contention can change that, so this is a hypothesis only.
   The affected metric is WT compare/Open foreground IPC, including WT comments
   that load a full view. It does not directly change display_patch or rendering.
2. Repeated native-compatible metadata probes deserve a later diagnostic.
   `working_tree_impl` filters the native handle with supports_working_tree,
   then runs `rev-parse --git-path index` for sparse fallback. The native handle
   may still be usable for HEAD/index metadata, but alternate-index and format
   behavior must match before replacing CLI reads. Saved route Trace2 contains
   one rev-parse per full/scoped WT request. That confirms repetition, not its
   untraced wall cost or an optimization's correctness.
3. Do not duplicate staged-anchor metadata (aba), helper placement (252d), status
   discovery (d5b05), or initial four-capture concurrency (already integrated).
   Pane reuse was discarded. Full sparse native patches failed exact parity in
   the earlier experiment. Existing evidence does not justify reviving them here.

The actual status worker route trace records five no-index start-to-start gaps
around142-151ms, but it is traced and includes different launch overhead from the
old direct command diagnostic. Neither trace is a canonical GUI score. Do not
subtract those times from the latest852ms compare median to predict a result.
The latest302.5ms GUI remainder already exceeds the entire250ms target; this
candidate cannot establish the goal alone.

## Native measurement after release

Keep this candidate isolated from staged metadata and helper placement for its
first comparison. Root must release the serial native slot before any build,
correctness check, or timing. Build matching workers and packaged GUIs from the
pinned d5b05 baseline and this exact candidate using the same established compiler,
worker recipe, rendering settings, seeded profile and kernel fingerprint. Record
source, executable and embedded-worker hashes. Do not reuse a newly modified
worker from the shared host test target as a baseline artifact.

Run native correctness first: exact list/group/order, regular raw frozen sections,
decoded rows/content, nested-repository metadata, binary/empty files, partial
staging, conflicts and appropriate symlink paths; verify unchanged index/config/
HEAD bytes and stat data. Untracked-symlink raw headers already contain random
scratch paths in baseline; compare baseline-versus-baseline before interpreting
that known raw drift. The new Unix unreadable-file test is Unix-only. Do not
silently waive an unrelated Windows baseline failure.

Then run the unchanged canonical WSL-GUI to NTFS A/B under contract3db306b4.
Keep Open and first-use separate; retain every correct visible-file/marker check,
comment location, two frames, IPC sub-timing and failure sample. Follow the
existing three-fresh-process setup and third-process20-repetition contract;
collect all actions and same-side/reverse controls before any promotion. Compare
WT and WT-comment p50/p95/max and native compare/Open IPC; branch/stack and
controls retain the10% regression guard. A component gain alone cannot promote.

If the pilot remains ambiguous, use the existing persistent-stdio worker seam
and inherited `GIT_TRACE2_EVENT` for one diagnostic WT call per exact worker under
the native user environment. The saved route harness already captures these
child events. Inspect no-index overlap, status/unstaged regions and the preflight
index probe. Trace2 omits Rust command discovery and all pre-child wall cost.
If that gap matters, add only a temporary diagnostic timer around run_git's
command construction and child output in an isolated overlay. Record start/end,
operation kind and exit status, preserve stdout, and remove the overlay from all
scored builds. No general tracing framework is needed. Literal CLI_TRACE is not
present in the saved source or logs; the existing observed seam is Trace2.

## Native component preflight prepared

`native-plan.json`, `native-experiment.py`, `run-native.py` and `native-input.json`
prepare the next narrow Windows-worker comparison. Host preparation only: both
Python programs pass `ast.parse`, archive source/support bytes match their pins,
and no VM call, native build or test has run for this preflight. The source is
exact f15e85; baseline is the existing exact d5b05 PE, SHA8fafdb05. The input
preserves all49 app-file hashes and the unchanged host proof of32 worker unit
checks, one real stdio check and77 GUI checks with one ignored.

Wait for the root agent to release the serial VM slot, then run:

```sh
python3 -u build/experiments/parallel-untracked/run-native.py \
  --release 'VM PARALLEL UNTRACKED NATIVE RELEASED'
```

The native supervisor builds only the f15e85 MSVC worker and its unit-test PE,
then executes those tests from the owned NTFS directory. It excludes the
cross-built stdio integration test whose embedded Cargo path points to Linux.
The actual PE is exercised through persistent stdio during four serial A/B/B/A
processes. Each runs Hello/Open/one first WT/five repeated WT requests, followed
by full raw-patch marker validation and a final Hello. Both sources use the same
owned NTFS helper image path, repository cwd and unchanged Git environment.
There is no tracer, profiler, added setting or span-parser code.

All24 WT payloads, grouped fifteen entries, raw frozen sections and decoded
patches must agree. Native PID/creation/image identity, clean EOF, zero launcher
exit, empty stderr, source and executable hashes, and index/config/HEAD bytes
and stat fields are required. Forced cleanup invalidates the run. The caller
refuses existing owner/output paths; inspect the same process record before any
versioned retry. First-use and repeated component timings remain separate.
These preliminary backend measurements can justify canonical GUI evaluation;
they cannot promote the candidate or prove the250ms GUI goal. Fresh process is
not OS-cold. The cwd probe uses native cmd with the same Popen cwd and does not
read the worker's PEB.
