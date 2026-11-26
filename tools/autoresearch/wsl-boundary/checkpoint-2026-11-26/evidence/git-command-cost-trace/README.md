# Git command construction diagnostic

Prepared source: `e72a63dcb70773427a836cc4d68f7e153f08e39c0641a2dd6c01da75be0e9b68`.
Exact baseline: stateless-status `d5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb`.
`trace-overlay.patch` changes only `run_git` in `src-tauri/src/git.rs`.
`baseline-source.json`, `source.json` and `prepared.json` pin identities and scope.
No test, formatter, compilation, build or VM command has run for this overlay.
Main source, the parallel-untracked candidate and canonical controls are unchanged.

The two local Instant spans distinguish `command(root)` from `Command::output()`:

```text
BRANCHLINE_PHASE pid=123 phase=git.command tag=diff.no_index elapsed_us=123
BRANCHLINE_PHASE pid=123 phase=git.child_output tag=diff.no_index elapsed_us=456
```

Tags come from a fixed whitelist. No path, argv, environment, revision name,
Git output or error text appears in these records. The existing command builder,
argument insertion, output handling, exit semantics and errors retain their
behavior. Construction failure emits its measured command span and returns the
original error. Spawn failure emits both spans and returns the original mapped
error. Stderr write errors are ignored. Stdout remains the worker JSON protocol.

This dedicated diagnostic source always emits the records. It adds no flag,
configuration, worker operation, cache, global state or tracing abstraction.
Tag selection, argument insertion and stderr writes are outside both spans.
Writing the first record can delay the following child launch; the records are
component diagnostics, never a GUI score or an uninstrumented request-latency
claim. The two stderr lines are small, but their overhead still needs a control.

## Execute only after root releases the native slot

1. Compile the real MSVC PE storage worker from this pinned source after the
   queued native work completes. Retain source/compiler/executable hashes. Use
   the same helper file placement for the exact d5b05 control and instrumented
   worker, and record that placement separately from the NTFS repository path.
   Do not reuse a mixed-source PE or package this diagnostic into a scored GUI.
2. Launch the actual PE through persistent stdio against the unchanged NTFS
   kernel fixture under the same max-user environment. Match product cwd:
   `Location::Windows::command` sets it to the repository's NTFS path. Record
   actual native cwd without writing configuration. Keep existing user Git
   settings and argv/environment. Do not enable Trace2 or another profiler in
   this first run; those can be a separate diagnostic if required.
3. Reuse the existing `owned-native-sparse/backend_compare.py::Worker` transport
   seam, which already preserves stdout JSON, records outer monotonic request
   timings and redirects stderr directly to an owned file. This avoids a pipe
   reader or logging framework. Call Hello, Open, then one first WT request and
   five repeated WT requests with the returned view/checkout and unrestricted
   untracked paths. Retain first use separately. Use one worker per source,
   serially, and close stdin then wait for its actual exit. The exact baseline
   control can use the same request sequence with its empty diagnostic log.
4. Verify Windows Hello identity and unchanged PID across calls, the canonical
   fifteen grouped files/markers, and exact raw frozen sections/metadata against
   d5b05. Preserve response/error outcomes and before/after index/config/HEAD
   bytes and stat metadata. Stop on an invalid response or fixture mutation.
5. Group stderr values by fixed tag and phase. Report first use and repeated
   p50/max for command construction and child output, with their raw records.
   Sum the five serial no-index spans per request only. The four initial
   captures overlap, so their summed durations are not a critical-path latency.
   Compare whole-request time against the uninstrumented control to expose
   logging overhead. The diagnostic cannot attribute all outer remainder.

The question is whether repeated Windows Git executable discovery/canonicalization
is material beside child execution. A small construction span rejects that
hypothesis. A large construction span justifies a separate, narrowly scoped
experiment with an invalidation/security design. This overlay adds no caching
and establishes no speedup or end-to-end improvement.

## Native caller prepared after checkpoint

`native-plan.json`, `native-diagnostic.py`, `run-native.py` and `native-input.json`
prepare a fixed-path MSVC worker build and component diagnostic. Host preparation
only: both Python programs pass `ast.parse`; no VM command, build, test or app
runtime has run for this diagnostic. The input archive preserves all 49 pinned
source files, the existing `backend_compare.py::Worker` transport, and the exact
workload manifest. No source Git metadata is required by the worker build; source
provenance uses the frozen Git HEAD and per-file hashes.

After the root agent releases the serial VM slot:

```sh
python3 -u build/experiments/git-command-cost-trace/run-native.py \
  --release 'VM GIT COMMAND DIAGNOSTIC RELEASED'
```

The planned order is A/B/B/A with two fresh persistent workers per source. Each
worker runs Hello, Open, one first WT and five repeated WT requests; raw-patch
validation and final identity checks follow that sequence. Both versions execute
from the same owned NTFS helper image path and same NTFS repository cwd. The cwd
probe is a native `cmd /c cd` launched using that same WSL cwd; it does not read the
worker's PEB. The diagnostic preserves raw metadata, frozen sections and all
fifteen patch markers, as well as index/config/HEAD bytes and stat fields.

Per-request stderr is grouped by fixed tag and phase. Only the five serial
no-index command/child spans are summed; the initial four concurrent captures
are not added into a latency figure. A/B outer request times expose apparent
instrumentation cost, with order/cache uncertainty retained. No profiler is
added to either worker environment. Fresh process is not OS-cold. A source or
fixture mismatch, abnormal EOF or required forced cleanup invalidates the run.
The caller refuses existing output/owner records; poll the same live handle or
inspect terminal evidence before a new versioned retry. The input archive and
caller are host-only until the explicit release.
