# Campaign state

Updated 2026-11-25 on host `ok`. Goal active; the 250 ms target is not met.

## Current checkpoint

- Campaign branch: `codex/wsl-boundary-perf`. Application source is committed
  through `1135a59f3a51253709d652d1e4ec82fa8b32ce09` and pushed to GitHub.
  Both native workers and both packaged GUI builds passed GitHub CI:
  https://github.com/traplol/diff-tool/actions/runs/45692019847.
- The original VM source checkout and its `test-repo/` are preserved. Generated
  build caches were reused. Benchmark repositories and profiles are separate.
- Current controls are `driver.py`, `launch.py`, `launch_linux.py`, `probe.js`,
  `workload.py` and `score.py`. The current frozen contract is
  `3db306b466166cb39b8c5a9dc27a9739b16df52fa9f83d32bd6656f226026b04`.
  Older contracts and source versions below are historical evidence.
- The portable checkpoint is in `checkpoint-2026-11-25/`. Its manifest records
  copied source patches, evidence paths and checksums. Unfinished candidates
  remain separate from the application source. Both VM-built helper-candidate
  GUIs and their runtime evidence have also been copied to host `ok` under
  `build/checkpoint/vm-sync-2026-11-25/`; all 36 SHA256 receipt entries pass.
  Reverse native runtime gates were not started, and all started VM jobs exited.
- Windows status discovery improved working-tree p95 from 1,974 to 1,283 ms
  and working-tree comment p95 from 1,716 to 1,120 ms in WSL GUI / NTFS tests.
  This candidate still needs Windows GUI controls and final combined validation.
- Across-file pane reuse passed native correctness but made the performance
  pilot slower. It is discarded. Existing unified/split pane reuse remains.
- Native helper placement passed host and native build tests, plus Linux GUI
  / Windows worker runtime gates. Reverse runtime gates and GUI A/B remain.
  Both baseline and candidate fail at the same 270-UTF16-unit fallback image
  path; the 215-unit path passes. The exact path-length failure cause is unproven.
- Staged metadata proof passes 78 GUI tests, 30 worker unit tests and one real
  stdio test, with one existing ignored GUI test. Native platform verification
  and timing remain. It requires matching rebuilt protocol-2 workers.
- All four final matrix cells, fresh/cold scenarios and the complete under-250 ms
  requirement remain incomplete. No candidate is accepted from component timing
  alone. Continue from the source hashes and pending gates in the checkpoint.

The sections below retain the experiment history and original observations.
Later entries supersede earlier running-process and pending-build statements.

## Workload and access

- QEMU Windows SSH access is restored through the existing localhost forward.
  The VM owner authorized VM work; no user action is required.
- Actual Linux v6.12 `adc218676eef25575469234709c2d87185ca223a`, shallow history,
  86,680 tracked files, 29 common sparse exclusions, 86,651 materialized files.
- Deterministic two-layer stack, thirty changed files per layer, five staged,
  five unstaged, five untracked changes. Two genuine review comments cover a
  non-checkout branch and a staged working-tree line.
- Both owned replicas are complete. Git-state fingerprint:
  `db66016f41a604c102cc81121c4e81f9c93db3b3f4430ef51dab5ba1c9da97c2`.
- Manifest: `build/autoresearch/wsl-boundary/workload.json`. Runtime artifacts
  live under that ignored directory and the owned Windows/WSL campaign roots.
- NTFS index stat caches use Git for Windows; ext4 uses Linux Git. Do not
  initialize one platform's cache using the other platform's Git.
- Actual Windows WebView2 and WSLg WebKit sessions work through loopback SSH
  forwards. Only folder-picker selection is substituted. Native repository,
  comparison, patch, comments and MCP operations remain in the timed path.
- Probe failure checks reject wrong markers, native errors and timeouts. A
  complete sample requires exact comparison/files/content and visible target
  comment, followed by two animation frames.

## Recorded controls

- Baseline A is the original source. Immutable source clone:
  `build/autoresearch/wsl-boundary/baseline-source`, source hash
  `fc3c6f04f234cf84be1b80679cb33327843e8d75c950c3854713718921ce0c4a`.
- A valid Windows app / WSL repo run with both comments took 93,399.8 ms to
  open, and 82,243.3–89,824.6 ms for interactions. These are single samples,
  not statistical p95 results. Evidence: `baseline-windows-linux-01/`.
- Linux baseline A is invalid: libgit2 reported sparse omissions as deletions.
  A regression test reproduced the defect before the fix.
- Baseline B contains only the sparse-checkout compatibility fix and its test.
  Source clone: `build/autoresearch/wsl-boundary/baseline-compat-source`.
  Source hash:
  `9f80f37d9f8df6059180ba5ed518e99963afc79ee34142eab2eb6d6f33a4f6f5`.
  Both release builds and 46 Rust tests pass; original A binaries preserved.
- B WSL app / WSL repo run is valid over three interaction repetitions.
  Open: 3,782 ms. Interaction medians: 625–700 ms. Worst interaction first-use:
  948 ms. Evidence: `baseline-compat-wsl-linux-02/`.
- The earlier B run ending with a WebKit element-click error is invalid.
  Pointer actions repair the automation transport; production UI is unchanged.
- The other three B cells and required fresh-process/repeated samples remain
  pending. Do not report a complete matrix or a demonstrated candidate win.

## Candidate in progress

- Hypothesis: keep review storage and public repository identity in the GUI OS,
  but execute Git beside repository storage in a persistent read-only worker.
  This removes per-file boundary traversal and repeated WSL process launches.
- Implemented standalone `src-tauri/git-worker`, shared wire protocol, persistent
  client, Git routing, embedded opposite-OS worker packaging and CI artifacts.
- Frozen working-tree sections remain client-owned and cross the wire as base64.
  Caller-frozen refs survive worker refresh. Search retains its streaming,
  cancellation path. Legacy raw root strings preserve config and draft keys.
- Host validation: 57 GUI Rust tests; 30 focused Git/wire/client tests; worker
  stdio and unit tests pass. Native Windows candidate calibration is valid below.
- Candidate source snapshot hash:
  `24f00e6570ec7420fbbc40c90d3f4f20576a4c73a8a12eb030d98a71e0bbf1ce`.
  Immutable local snapshot: `build/autoresearch/wsl-boundary/candidate-source`.
- Agent `kernel_workload` owns VM packaging. The recorded B Linux GUI is stopped;
  musl prerequisites are installing before Windows and Linux candidate builds.
  Do not run resource-sensitive VM benchmarks until the agent reports free.
- Agents `windows_benchmark_rig` and `wsl_git_architecture` review remaining
  foreground overhead and integration correctness on the host only.

## Next actions

1. Record candidate source and embedded-worker binary hashes from builds.
2. Finish the repaired B matrix serially, freeze the evaluation contract, and
   benchmark the exact candidate with identical workload and correctness gates.
3. Profile remaining latency. Suspects are repeated session/comment location
   reconstruction, full worktree scans and synchronous MCP startup.
4. Continue measured improvements until the target and correctness gates pass.
   Final evidence requires twenty samples per action per cell and fresh-process
   calibration. Do not move required work outside the timer.
5. Run a fresh KISS-only subagent against the final diff before any commit.

## First worker candidate native calibration

- Repaired baseline B Windows / WSL: valid one-pass control, opening 13,033.5 ms,
  interactions 2,377.5–8,058.2 ms. This isolates the worker improvement from the
  sparse compatibility correction that accounts for much of baseline A's cost.
- Worker-v1 Windows / WSL: valid three-pass interaction calibration. Opening
  1,913.3 ms; interaction medians 425–619.9 ms, maximum 634.9 ms. Exact source
  hash `24f00e6...`, binary hash `cded5469...`; build record contains full hashes.
- Both runs use contract `4fe7daba...` and the same workload and seeded profile.
  This is provisional evidence; the full matrix and final sample counts remain.
- Git comparison RPCs consume roughly 400–445 ms; patch RPCs 8–11 ms; UI tail
  roughly 30–45 ms. The next performance hypothesis is the full working-tree
  scan performed by comment tracking even during branch comparisons.
- Search correctness review found shared worker preparation could delay the
  foreground after cancellation. Architecture agent is fixing it separately.
- Rig agent is implementing a conservative scoped verification shortcut only
  for unchanged exact M anchors, with full fallback for edits/adds/renames.
- VM build ownership has returned to kernel_workload for the immutable worker-v1
  Linux GUI build and Windows-specific tests. No concurrent VM scoring.

- Both worker-v1 GUIs are packaged and verified, including the two actual
  Windows-only path mapping tests. Linux artifact SHA256:
  `85cc431447f155c7a2f7e952fe5adfb822dfc55b8ca66999d5dcdb57071b4c5b`.
- Idle WSLg RAF cadence is 16–17 ms with document focus true. The ~270 ms
  post-IPC delay is not an idle frame-rate cap. Diagnostic:
  `build/autoresearch/wsl-boundary/raf-diagnostic.json`.
- Agent kernel_workload now owns VM frontend diagnosis using the existing B
  app/profile and host launch record `launch-baseline-compat-wsl-linux-raf.json`.
  No other resource-sensitive VM work may run concurrently.
- Search connection isolation is implemented in root and passes 39 focused
  Git/transport/search checks; it is not in immutable worker-v1 binaries.
- Architecture agent is testing a separate native sparse optimization under
  `build/experiments/owned-native-sparse`; do not promote without correctness
  evidence. True sparse checkout vivifies present excluded files, unlike manual
  skip-worktree with sparse checkout disabled; blanket filtering is incorrect.

## Second candidate and scorer checkpoint

- Scoped-anchor production source is frozen for candidate v2 at
  `build/autoresearch/wsl-boundary/candidate-scoped-v2-source`, source hash
  `f61933d8cfb8ef2b16af120e034868d180b0db0cb1314208d3ff7d923cd48c93`.
  Overlay tar is 911,360 bytes. It includes search isolation and scoped exact-M
  tracking, not the isolated sparse-native experiment.
- The initial v2 identity accidentally included generated helper target files.
  That unscored identity was rejected and preserved in
  `candidate-scoped-v2-rejected-identity.json`. The scorer now enumerates only
  helper src/tests/manifests. Tests verify artifacts do not change source hashes,
  while source edits do. Prior B and v1 source hashes remain unchanged.
- Contract advanced to
  `497db2eebf762b4406ef816823f1e49427c8910c5a75c5ff7fa3b70cb5aeacc7`.
  Keep earlier calibration evidence separate; rerun final controls/candidates.
- Live WSL trace: correct CodeMirror content/marker appears 6 ms after patch IPC,
  busy clears in 6–7 ms, yet the next two RAF callbacks are 120–150 ms apart.
  Heartbeat timers still fire every 16–20 ms. Idle/small repaints have normal
  frame cadence. Kernel agent is testing default GTK backend in an owned runtime
  launcher copy, because the rig explicitly forced X11. No canonical or product
  renderer change has been made.
- Isolated sparse-native candidate: 32 copied Git/wire tests pass, including
  nine new native-vs-Git parity cases. Source patch/proof under
  `build/experiments/owned-native-sparse/`; binary hash
  `9620afc612582ee290f76e7e2d73f4f781576fe33477576162b09f38940d5153`.
  Not promoted, not VM-executed, not performance-scored. Architecture agent is
  preparing a serial backend-only VM comparison script; wait for kernel agent's
  VM release before running it. Backend scores cannot satisfy the GUI target.
- Next VM actions: finish GTK diagnostic; measure sparse-native backend proposal
  serially; build frozen v2 Windows GUI and compare against v1; finish 2x2
  controls/candidates with native GUI correctness and final sample counts.

## Active v2 build

- Full root GUI Rust lib suite passes 63/63, frontend suite 5/5. Logs:
  `scoped-v2-rust-tests.log`, `scoped-v2-frontend-tests.log`.
- Kernel agent owns scoped-v2 Windows build, WSL PID 74473. The new owned VM
  clone was verified against source hash f61933d8...; v1 build caches were copied,
  not shared or overwritten. It will stop after publishing the Windows artifact.
- All graphics diagnostics are finished. Default Wayland did not remove the
  full-switch tail; client viewport differed, so these are diagnostics only.
  Tiny glyph mutation was reverted by the editor before paint and is not valid
  repaint evidence. Persistent 8x8 repaint is valid. Subtree replacement/reveal
  does not by itself reproduce the full ~285 ms delay. No canonical rendering
  or launcher change was made. Owned diagnostic GUI/driver/MCP are stopped.
- Native3 backend harness is ready at
  `build/experiments/owned-native-sparse/{backend_compare,compare_vm}.py`.
  Host real-stdio smoke passed. It must wait until root scores v2 and explicitly
  gives the architecture agent a serial VM resource slot.
- Clean KISS-only review identified two reductions to apply before final commit:
  collapse native working_changes_paths wrapper into working_changes(paths),
  and remove unused wire Request::GitExecutable (OpenResult already carries it).
  No other production simplification was requested. Do not alter frozen v2;
  apply reductions with the next kept integration, then rerun affected checks.

## Scoped-v2 first native score

- Actual Windows / WSL run valid over three interaction repetitions. Source
  f61933d8..., Windows binary164c9ef7..., contract497db2ee.... Evidence:
  `candidate-scoped-v2-windows-linux-01/verdict.json`.
- Medians: branch_first369.8ms, branch_final324.1ms, stack359.1ms,
  working_tree407.8ms, branch comment492.4ms, WT comment526.2ms.
- First-use opening2294.2ms and WT1735.6ms are unresolved cold outliers;
  preserve them. Target remains false. No promotion/final acceptance claim.
- Root is stopping the owned Windows app, then architecture agent gets the
  short serial native3 backend experiment slot. No concurrent VM builds.

## Native3 outcome and reverse-path setup

- Native3 backend proof completed on the VM. Artifact:
  `build/experiments/owned-native-sparse/vm-backend-20261125/summary.json`.
- It is invalid under the strict decoded-patch hash gate: two
  mm/kfence/core.c patches differ. Host reproduction traced that to one trailing
  space in the cpp function-context hunk header; code rows and full contents
  match. The invalid verdict is retained; no native3 production promotion.
- WT p50 static v1 382.19ms versus GNU native3 402.14ms (10 each), so the sparse
  algorithm has not demonstrated an improvement. Unchanged-source GNU controls
  are being prepared host-only to isolate build/libc effects; do not treat the
  faster GNU branch timings as an algorithm win.
- Root owns the VM for reverse cross-path GUI testing. Worker-v1 WSL app opened
  the NTFS kernel fixture and seeded both genuine comments successfully:
  `seed-candidate-worker-v1-wsl-windows/verdict.json` is valid.
- Seed app/driver/MCP stopped. Fresh measurement GUI is supervised by host exec
  session55320, record `launch-candidate-worker-v1-wsl-windows-01.json`, profile
  `/home/max/benchmarks/branchline-boundary/profiles/candidate-worker-v1-wsl-windows`.
  Source24f00e6..., binary85cc4314..., WebKit port29225/tunnel19225.
- Wait until architecture agent's host static-control compile finishes before
  recording resource-sensitive GUI timings. No other VM work is allowed yet.
- Optional Windows TCP microbenchmark is prepared only under
  `build/autoresearch/wsl-boundary/windows-mcp-write-profile/` and remains queued.
- Deferred-disposal frontend experiment is isolated, not promoted, under
  `build/experiments/deferred-diff-disposal/`; overlays only app.js/editor.js.
  Existing tests + three focused tests and Vite build pass. Native regressions
  and measurement remain required before any keep decision.

## Reverse cross-path first native score

- Worker-v1 WSL GUI / NTFS kernel run is valid over three repetitions:
  `candidate-worker-v1-wsl-windows-01/verdict.json`, source24f00e6...,
  binary85cc4314..., contract497db2ee....
- Open4117ms; medians branch_first2459ms, branch_final2589ms,
  stack2229ms, working_tree2945ms, branch comment2411ms, WT comment3115ms.
  All correct refs/15 WT paths/markers/comment destinations passed. Target false.
- Root is stopping that owned app/driver/MCP before handing VM to architecture
  agent for short unchanged-source GNU build-control measurements.
- Root applied the two KISS reductions after freezing/scoring v2: removed unused
  wire GitExecutable request; collapsed native WT wrapper into one optional-path
  function. Envelope is compiled only for worker/server or tests. No production
  performance hypothesis changed. Affected checks still need rerun before build.

## Native Windows control and proven cwd fix

- Scoped-v2 Windows GUI / NTFS run is valid over three repetitions:
  `candidate-scoped-v2-windows-windows-01/verdict.json` (source f61933d8...).
  Open1352.6ms; medians branches448/466.5ms, stack439.4ms, WT1722.5ms,
  branch comment525.3ms, WT comment1759.8ms. This shows the Windows WT engine
  remains slow even without cross-boundary repository reads. Target false.
- Cwd proof passed with the exact same Windows worker, no source changes:
  UNC inherited cwd WT median2174.47ms versus NTFS cwd1500.00ms. Startup/Open
  also improved. Full payloads and index state match. Evidence:
  `build/experiments/owned-native-gnu-control/vm-windows-cwd-20261125/`.
- Production remote.rs now sets each worker's storage-side cwd per command;
  Windows->WSL passes separate --cd args, Linux->Windows maps cwd with wslpath.
  No global cwd change. Host remote tests8 passed, one WSL-only test ignored;
  Windows argument test and ignored WSL integration still need actual VM checks.
- Full root tests after cwd/KISS changes pass63, one ignored. Logs:
  `cwd-kiss-rust-tests.log`. Frozen v2 artifacts remain unchanged.
- Unchanged static GNU worker controls are valid: vs serial musl, warm compare
  33.26vs71.79ms, refresh+compare94.80vs220.65ms, WT266.08vs340.88ms. Exact
  output/index checks pass. This is a build/libc/toolchain result, not yet a GUI
  or a specific allocator claim. Source/build evidence under owned-native-gnu-control.
- Smaller sparse early-CLI experiment is ready under owned-sparse-cli, isolated:
  configured sparse=true skips expensive native-index attempts before existing
  CLI fallback. Manual SKIP config=false retains old guard.25 tests pass;
  static/dynamic GNU binaries built. VM measurement pending.
- Root is stopping the Windows control; architecture agent gets a brief serial
  slot to compare static GNU early-CLI against unchanged static GNU, then releases
  VM. No other benchmark/build may overlap.

## Combined-v3 source and active build

- Root integrated the proven early sparse CLI selection and four independent
  read-only CLI captures, preserving existing optional/literal path arguments.
  Independent narrow reviews found no blockers. All threads join before errors
  and before index/head checks. Per-file untracked/conflict work stays serial.
- Combined source frozen at
  `build/autoresearch/wsl-boundary/candidate-combined-v3-source`, hash
  `0560a9511e83f27a55e7018ea59b0fe9b3864887a079eb7bf3e1f647743327ca`.
  Overlay911360bytes; metadata `candidate-combined-v3-build.json`.
- Host integrated gates: GUI Rust65 passed,1 WSL-only test ignored; worker25
  unit tests +1 real stdio integration pass. Logs `combined-v3-*-tests.log`.
- Kernel agent now owns VM combined-v3 build: explicit static GNU Linux helper
  from this exact new source, through existing BRANCHLINE_GIT_WORKER_PATH override
  into the Windows GUI. Default build.sh/CI remain musl pending actual GUI
  validation. It will record compiler/cc/flags, source/helper/GUI hashes, run
  bounded actual cwd-construction checks, copy Windows artifact and STOP before
  Linux GUI build. No resource-sensitive benchmark may overlap.
- Parallel component VM proof valid: same static GNU dependencies/compiler,
  WT p50 276.56->153.08ms, p95/max394.53->170.94ms (10 each). Exact outputs and
  index state match. Evidence `owned-parallel-cli/vm-static-20261125/`.
- Windows TCP diagnostic was immaterial (~1.139 vs0.368ms median excluding
  connection setup/real handler). No networking source change. Record:
  `windows-mcp-write-profile-result.json`.
- Frontend deferred-disposal remains isolated/unpromoted. Do not fold it into
  combined-v3; measure that hypothesis separately on a Linux GUI after this build.
- Next: confirm combined-v3 build identity and actual cwd tests; native Windows
  app->WSL score against the same seeded profile with>=3 calibration reps; then
  build Linux counterpart and continue reverse/same-side matrix and frontend
  experiment. Final20-sample/fresh-process/first-use acceptance remains pending.

- Latest builder checkpoint: combined-v3 owned VM clone and copied cache exist;
  overlay/source identity verification is underway. Compilation had NOT started
  at the last authoritative report. Do not infer a live build PID from the task
  assignment. Kernel agent was asked to launch immediately after verification,
  skip further setup/tests until artifact exists, and report the actual PID.

- Compilation has now actually started: verified source0560a951..., WSL build
  supervisor PID80830, kernel agent's exec session12832. Static GNU helper phase
  is active and will continue directly into Windows GUI/copy. Optional checks
  are deferred. Revalidate this exact process/log; do not restart on observation
  timeout. Kernel agent owns it and will report artifact identity/resource release.

## Combined-v3 actual Windows / WSL calibration

- Build80830 completed successfully. Exact source0560a951... is unchanged;
  Windows GUI7c2806fe..., embedded static GNU helper328c0680.... The helper
  has no ELF interpreter or dynamic dependencies. Toolchain/build flags are
  recorded in `candidate-combined-v3-build.json`. Default build recipes still
  use musl; this experiment uses the existing prebuilt-worker override.
- Native run `candidate-combined-v3-windows-linux-01` is valid, contract497db2ee,
  same seeded profile/workload, three repetitions. Medians: branch_first212.3,
  branch_final134.6, stack146.5, WT220.2, branch comment228.3, WT comment228.6ms.
- Opening2399.1ms, first branch350.5ms, first WT1358.3ms and first WT comment
  307.3ms remain over target. The actual GUI target is not met. Cold outliers
  are retained; no acceptance or promotion claim.
- Root owns the VM for two additional fresh-process runs, including20 repeats
  in the third process. No builds or other benchmarks may overlap. Architecture
  and rig agents are tracing startup/comment dependency paths host-only.
- Actual cwd integration tests and the Linux combined-v3 GUI remain unbuilt.
  Next after scoring: finish same-source Windows/NTFS control, build Linux
  counterpart, and continue both Linux GUI cells. Opening/cold-use and WSLg
  rendering delays still require measured experiments.

- Windows/WSL now has three completed fresh-process runs. Open2399.1/1322.0/
  1295.1ms. Third process20-cycle run is valid: interaction p95 branch_first199.2,
  branch_final136.4, WT206.9, stack128.2, branch comment229.2, WT comment230.1ms.
  All120 interactions in that process were under250ms (max244.3ms); earlier
  cold outliers remain in separate runs. This does not satisfy opening or final
  cross-direction acceptance. Exact evidence `candidate-combined-v3-windows-linux-03`.
- Same-source Windows/NTFS control also has three fresh processes, third20cycles,
  all valid. Third p50/p95: branch_first401.7/417.8, branch_final356.1/386.6,
  stack330.6/360.1, WT1427.2/1473.7, branch comment416.8/462.0,
  WT comment1463.9/1572.0ms. Open1243.2ms (earlier1337.6/1246.9).
  Evidence `candidate-combined-v3-windows-windows-03`. Windows working-tree
  processing remains slow even on NTFS and needs profiling before the reverse
  direction can meet target. All owned Windows GUI/MCP processes are stopped.
- Rig agent gets a bounded read-only VM Trace2 diagnostic slot (no compilation),
  then kernel agent builds the exact0560 Linux GUI/MSVC helper. Architecture
  agent is tracing serialized MCP startup/duplicate repository opening host-only.
  Root production source remains frozen; small inline-comment redraw proposal
  is isolated in `build/experiments/comment-jump-refresh`, tests not yet run.

- Bounded Windows Trace2 diagnostic completed and released the VM. In the
  exact untracked listing, directory traversal takes878–942ms while index
  parsing takes6–9ms; five serial no-index diffs add248ms untraced. This was a
  component diagnostic under SYSTEM with per-command trust for the exact owned
  fixture, not a GUI score or max-user configuration proof. Index bytes/stat
  unchanged. Evidence `build/experiments/windows-wt-trace2/`.
- Kernel agent now owns exact0560 Linux build: supervisor87357, exec57983.
  Root independently confirmed that exact PID live. MSVC helper phase finished;
  Linux GUI is compiling with it embedded. Logs on VM:
  `build-candidate-combined-v3-windows-helper.log`,
  `build-candidate-combined-v3-linux.log` in the campaign root. Do not restart on
  an observation timeout. Actual cwd tests follow the artifact.
- Comment-jump-refresh isolated checks now pass: three focused cases, all six
  frontend test files and Vite build. Native workflow/performance remain untested;
  production frontend remains unchanged. Rig agent prepares a bounded max-user
  default-vs-fscache flag script without VM execution. Effective config must be
  recorded; no persisted repo/index/config changes are allowed.
- Architecture agent prepared opt-in phase timing in a separate
  `build/experiments/open-phase-trace` overlay. No frozen source changed and no
  build/VM execution yet. It is now testing a separate scoped-tracked-native
  hypothesis host-only. Full sparse working-tree reads must stay on CLI;
  strict raw-patch/wire/index parity is required before any keep decision.

## Combined-v3 complete native matrix calibration

- Linux GUI packaged from unchanged0560 source: f31f3342...,23,259,424bytes,
  embeds exact MSVC helper6a4067eb...,2,720,768bytes. Build metadata is updated
  locally. Actual WSL path test passed. Windows argument-test compilation hit
  its two-minute bound and only its owned process tree was stopped; check remains
  deferred. All build processes are stopped.
- All four cells now have three fresh processes and20 interactions per action
  in the third process under the same contract497db2ee/source0560. This is a
  valid complete candidate matrix, not target acceptance or a completed baseline
  comparison series. Root finished all Linux scores and stopped every owned
  Linux GUI/WebDriver/MCP before the next component experiment.
- WSL/NTFS third20-cycle p50/p95: branch_first619/643,
  branch_final563/576, stack623/705, WT1856/2151,
  branch comment674/712, WT comment1648/1817ms.
  Fresh opens2614/2790/1716ms. Evidence `candidate-combined-v3-wsl-windows-*`.
- WSL/ext4 third20-cycle p50/p95: branch_first438/501,
  branch_final363/397, stack444/479, WT452/503,
  branch comment484/598, WT comment469/600ms.
  Opens1672/763/829ms. First-process firstWT2335ms remains recorded.
  Evidence `candidate-combined-v3-wsl-linux-*`. Rendering remains an independent
  bottleneck; the canonical renderer/settings/two-RAF gate did not change.
- Root now owns VM for bounded max-user fscache experiment, session58844.
  The driver was repaired to use the proven temporaryPowerShell-file transport;
  Console.In.ReadToEnd over SSH is known to hang. No compilation overlaps.
- Builder prepared separate pending snapshots: deferred-disposal frontend only,
  source75baec38...; opt-in Open phase diagnostics only, source000c433e....
  Both have source/overlay/build-plan records. No build yet; after fscache release
  build Linux deferred candidate then Windows tracing variant with exact v3
  workers through override, preserving the v3 source and packaged artifacts.
- Scoped-native tracking experiment is rejected:29 tests pass, strict cpp raw
  patch parity fails. Evidence is preserved; production unchanged. Root/agent
  traced the difference to libgit2 trimming context before80byte truncation,
  while actual Git-for-Windows2.56.1 and Git2.53 trim after truncation. A separate
  correctness-normalization experiment is planned, no implementation/promote yet.

- Max-user fscache experiment finished valid; real index/HEAD/checkout unchanged,
  exact raw outputs match. System Git config already sets core.fscache=true.
  Default untracked listing p50944.4ms, unstaged234.7ms. Disabling fscache is
  diagnostic only and makes unstaged8996.3ms; there is no eligible optimization
  flag. Evidence `windows-fscache/runs/20261125T175219Z/summary.json`.
- Pinned Git source shows ls-files --others does not attach the index's untracked
  cache, while status does. Rig agent is preparing a private-index status proof;
  no production cache/daemon/config/index change is authorized by that proof alone.
  First scan/setup and real-index invalidation costs must remain visible.
- Builder owns VM supervisor95746, exec75129, A then B. A Linux deferred GUI is
  packaged: cabdc926..., source75baec38..., exact MSVC helper embedding verified.
  B Windows phase-tracing GUI is compiling from000c433e with the exact existing
  GNU helper. Do not benchmark until B releases the VM. Source v3 unchanged.
- Diagnostic-only phase launcher prepared at runtime `launch_open_trace.py`;
  it reuses canonical native launch setup and explicitly enables only
  BRANCHLINE_TRACE_PHASES=1. Its results are phase evidence, not a promoted
  canonical timing win. Stock scoring controls remain unchanged.
- Native context correctness experiment is now host-only under architecture
  agent while VM builds. No timed benchmark overlaps those compiles. Scope and
  parity gates remain narrow; the prior rejected scoped candidate stays intact.

## Open profiling, readiness repair and follow-up candidates

- Both A/B builds completed and95746 exited. A Linux cabdc926... (source75baec38)
  first native3-repetition run is valid but shows no gain: branch_first567,
  branch_final409, WT535, stack497, branch comment842, WT comment606ms medians.
  Open3139ms/firstWT1641ms retained. Evidence
  `candidate-deferred-disposal-v3-wsl-linux-01`. Do not promote deferred disposal.
- B Windows phase build524a24d8..., source000c433e, exact GNU helper328c0680.
  First attempt `open-phase-v3-windows-linux-01` is invalid,0samples: the harness
  clicked while initial startup_path work was still running. The old readiness
  predicate could pass during the brief idle before that asynchronous call.
  App and MCP were stopped by recorded identity; no timeout-driven restart.
- Scorer readiness now requires the completed owned non-Git welcome error as
  well as an idle visible control. This excludes only process/welcome startup;
  all selected-repository work remains inside the button-click timer. JS checks
  cover pre-start idle, loading, completion and hidden welcome; all existing
  failure/self-check gates pass. Contract advanced to
  `3db306b466166cb39b8c5a9dc27a9739b16df52fa9f83d32bd6656f226026b04`.
  Older497db2ee evidence remains a separate provisional comparison series.
- Three fresh B diagnostic runs02–04 are valid under3db306b4. Each saved115
  phase lines. MCP startup takes789–804ms: prelaunch free-port connect350–361,
  first free-port poll350–365, while child repository initialization123–143ms.
  GUI initial worker start247–336ms (Hello185–227ms on main worker), initial
  service comparison122–801ms, and first WT150–1157ms; keep cold variance.
  Evidence `open-phase-v3-windows-linux-0{2,3,4}.{phases.log,stdout.log}` and
  run directories. All owned diagnostic Windows GUI/MCP processes are stopped.
- Native foreground hypothesis is disproved for the tested Linux baseline:
  no-window observer in actual WindowsSession1 saw foreground Branchline RAIL
  window, visible, not minimized, DWM cloak0, msrdc.exe. No activation occurred.
  Evidence `wslg-foreground/runs/20261125T181144Z/report.json`.
  Native foreground-confirmed v3 run `v3-wsl-linux-foreground-01` is valid under
  the repaired contract: medians branch476/375, WT505, stack485, comments497/485ms.
  Open2498ms retained. Its Linux app/driver/MCP have been stopped.
- Private-index proof completed correctly as max, with kernel index/config/
  HEAD/checkout unchanged and11 mutation/invalidation cases passing. Cold copy+
  first status397.5ms, warm private-status median257.6ms. Crucially the final
  REAL-index read-only status was253.7ms (initial428), versus ls-files898–914ms.
  Do not add private cache state on this evidence; first compare stateless status
  in repeated paired runs. Evidence `windows-private-index/runs/20261125T181604Z`.
- MCP port-check candidate58a08170 changes only probe behavior plus tests:
  prelaunch bind-and-drop;25ms startup connects; unchanged350ms HTTP validation,
  identity/auth/registration/deadline. Host5 real-loopback tests pass; registration
  header rerun with fixture token passes. Initial flat-snapshot compile failed
  only on missing unchanged icons; failure log retained, resources copied and
  tests rerun successfully. Logs `mcp-port-host-tests*.log`, token-test.log.
- Windows MCP GUI7f841c59... is packaged, exact58a08170 source and GNU helper
  embedding verified. Build supervisor98998 exited. Kernel agent still owns VM
  for the tiny actual-source Windows socket harness (no Tauri test target), then
  releases. Next: actual fresh-process GUI/MCP score of this candidate under3db.
- Pane-reuse prototype is being implemented by rig agent under
  `build/experiments/reuse-diff-panes`, based on0560; app.js/editor.js only plus
  focused tests. It reuses existing views via setDocument/updateContextRows,
  guards callbacks by generation, resets document state, and falls back for
  special/error/repo changes. No production edits or renderer policy changes.
- Header normalizer remains unpromoted. Host30unit+1stdio pass with an explicit
  pre-existing untracked-binary mismatch ignored, but independent review found
  uncancellable streaming fallback and built-in pretrim-selection gaps. Additional
  prepared cases remain unrun. Do not treat it as ready. Files preserved.
- Separate small idea queued: when untracked_paths is Some, constrain only
  ls-files --others to those literal names while preserving the exact post-filter.
  This may accelerate comment fallback without full discovery. Assess malformed
  names, nested repos, metacharacters, byte names, missing paths and transitions.
  Do not combine this with header normalization or alter unrestricted WT reads.

## MCP candidate native results and current handoff

- Tiny Windows actual-module harness passed all5 loopback tests, fixture-token
  header test, and explicit negative-connect timing in0.04s (each phase<150ms).
  Harness00777d6a... includes production probe/register/exchange/tests; unused
  startup seams are stubbed. Real GUI validation followed, so this microcheck
  is not being used as end-to-end acceptance. Evidence
  `mcp-port-windows-check-result.json` and adjacent logs/build record.
- Uninstrumented Windows MCP candidate58a08170 / GUI7f841c59 completed three
  valid fresh processes under contract3db306b4. Open1649.8/846.9/1053.1ms.
  Third20-cycle p95: branch_first199.9, branch_final137.7, WT222.3, stack130.5,
  branch comment213.9, WT comment244.3ms. A branch-comment max1462.6ms and WT
  comment max275.7ms remain unresolved; do not hide them behind passing p95.
  The1.46s sample is native Open1401.7ms, display_patch13.5ms. Evidence
  `candidate-mcp-port-v3-windows-linux-*`. All owned apps stopped.
- Separate MCP-plus-phase sourceecb76dbf..., GUI7d32c703..., helper328c0680
  compiled; supervisor104475 exited. Three valid diagnostic runs completed:
  `mcp-phase-v3-windows-linux-01..03`, third20cycles, logs113/119/1482phase lines.
  MCPensure now201–211ms versus789–804ms before the port fix. Diagnostic warm
  fresh opens648–658ms native total; first1287ms retains cold compare651ms and
  first WT1271ms. Rare1.46s comment spike did not recur in this trace; cause is
  still unproven. All GUI/MCP processes are stopped; no VM benchmark/build active.
- Rig pane-reuse host syntax/focused/full frontend/build checks passed after
  fixing complete row deletion (Text.of([])). Read-only architecture review
  found a visual stacking blocker: making both cached layouts inert can expose
  a later stale layout. Rig is fixing active visual stacking and adding the
  exact A Unified/Split/Unified -> B -> delayedC native case. Recheck tests/hash
  afterward. Populated native reuse, metadata-only, async content, old callbacks,
  alternate layout, and cross-repository teardown remain mandatory before scoring.
- Architecture agent has permission for host-only exact-name listing tests now;
  no other timing is active. Wait for actual test completion before benchmarking.
  Validation must use native-platform path rules, preserving Unix C:foo/colon/
  backslash names, and fall back to the original capture on scoped argv errors.
- Kernel agent is preparing a host-only helper-placement timing driver. Compare
  exact bytes executed from native versus foreign storage in both directions,
  same repo cwd/env/Hello/Open,10 alternating pairs. Copy/hash validation warms
  file caches, so call first samples fresh-process, not OS-cold. No VM execution
  or compilation yet. Native placement is a hypothesis, not a demonstrated win.
- Stateless Windows status control remains queued: existing real-index status
  253.7ms already matches private warm257.6ms. Test repeated paired reads before
  introducing any private-index cache. No private cache or daemon was promoted.
- Root production source remains0560, all changes uncommitted. Default Windows
  helper recipe stillmusl; staticGNU is an experimental override. A final delivered
  source must adopt any proven recipe and be re-scored, reviewed, tested and
  receive a fresh clean KISS-only pass before any commit. Goal remains active.


## User test checkpoint on host ok

The user requested a commit and GitHub push before further optimization. This
checkpoint contains the production worker/routing, sparse-checkout compatibility,
scoped comment verification, parallel read-only CLI captures, storage-side cwd,
and the validated MCP port-check fix. The default embedded Linux worker now uses
the measured static GNU recipe (`x86_64-unknown-linux-gnu`, static CRT and zlib)
instead of musl. The MSVC worker recipe is unchanged. Generated worker targets
are ignored.

Host verification for this checkpoint passed 70 Rust library tests, with one
existing WSL-specific test ignored, five frontend tests, the frontend release
build, and scorer controlled-failure checks. The worker suite passed 25 unit tests and one real stdio integration test. Shell and workflow checks validate the build recipe. Earlier native
four-cell measurements and MCP Windows checks remain provisional evidence for
the corresponding frozen sources; they are not a new exact-source matrix for
this checkpoint. The 250 ms target is not met and the optimization goal remains
active.

Additional work remains isolated under ignored build directories and is excluded
from this commit:

- Pane reuse passed its 17-step core native lifecycle check. Auxiliary special
  file, identical-text metadata, selection and window-size checks remain pending;
  no performance gain has been established.
- Stateless Windows status and exact-name untracked-listing candidates have host
  proofs, but still need native Windows validation and GUI measurements.
- Native-storage helper placement reduced component startup costs in ten paired
  runs per direction, with normal worker shutdown and unchanged repository state.
  It has not been integrated or measured in the GUI. Copy/hash validation warms
  caches, so those samples are not OS-cold measurements.
- Staged-only metadata verification has a reviewed design but no implementation.

All tests and benchmark apps used for the preceding native checks were closed.
No host GUI was opened. The original VM checkout source and test repository are
preserved; generated target output was reused for campaign builds. Runtime
artifacts remain under ignored build directories and the owned VM campaign roots.


## Resume after pushed checkpoint b2de070

- User test checkpoint `b2de070becf3fcba2d47557efd375221c586f273` is on
  `origin/codex/wsl-boundary-perf`; working source was clean after push. Native
  GitHub worker builds passed for GNU Linux and MSVC Windows; GUI packages were
  still building when checked. The optimization goal remains active.
- Exact baseline source snapshot `checkpoint-b2de070-source` is pinned to this
  commit, source hash `56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272`.
  It will be built in the same VM toolchain as the next status candidate.
- Stateless Windows status candidate is freshly rebased with only its two-file
  patch, source `d5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb`.
  Ten alternating native paired reads with actual product argv passed exact raw
  NUL-list equality and unchanged index/config/HEAD bytes and metadata. No user
  cache/monitor overrides were added. Median ls-files891.038ms versus
  status276.255ms, a69.0% component reduction; worst values970.095/328.720ms.
  Evidence `candidate-stateless-status-b2de070-native/{results,summary}.json`.
  Native worker tests and GUI build are pending under one live serial supervisor
  PID111496. Do not claim an end-to-end speedup yet.
- Native helper deployment is a separate source-only prototype. WSL→Windows
  discovers LOCALAPPDATA, maps it with wslpath, uses existing atomic materialize,
  and launches the PE directly from NTFS. Windows→WSL uses a positional constant
  shell script to copy/hash/exec the ELF from WSL cache. Current child and raw
  stdio ownership are retained; no PowerShell process wrapper or job framework.
  Native validation/performance is still pending. Discovery needs a fallback to
  existing GUI cache for redirected/unavailable Windows cache paths.
- Pane-reuse auxiliary harness passed Python syntax,46 constant JS body syntax
  checks, and real worker host-fixture checks for identical text and special
  files. Native UI gates remain pending. Added720p/1080p/1440p/4K and720×460
  minimum checks with actual client-size bounds. The prototype source now has
  its own pinned Git metadata, preserving its original b1d14ea9 identity after
  the user checkpoint commit; no app files changed during this repair.


## Native status comparison and pane correctness gates

- All six matched status GUI runs completed valid under contract3db306b4, using
  the same VM compiler and unchanged default GPU/MCP settings. Final20 samples
  in WSL app→NTFS: WT median/p95/max1839/1974/1997ms baseline versus
  1220.5/1283/1284ms candidate; WT-comment1622.5/1716/1736 versus
  1078/1120/1138. P95 improved35.0%/34.7%. Unaffected branch/stack p95 varies
  within3%. Candidate remains isolated;250ms target not met.
- All fresh Open samples retained: baseline2606/1422/1358ms versus
  candidate1515/1360/1376. These are fresh processes, not OS-cold samples.
  Third-process Open regressed1.3%, so do not attribute a general Open gain.
- Candidate WT median foreground IPC union915ms (compare852, patch62.5),
  non-IPC302.5ms. WT-comment IPC808.5ms (Open768.5, patch42), remainder269.5.
  Remainder includes handling/render/frames/waits, not directly measured paint.
  Exact summary and identities:status-gui-ab-20261125T195712607225Z-summary.json.
  Exec30135 exited0; all retained launch supervisors exited0, recorded app/driver
  identities absent and ports29225/28867 free before the next experiment.
- Pane auxiliary03 passed all20 native checks: identical-text owner/syntax/group,
  polling/edit/resolve/reopen, suggestion Apply, six special-file fallbacks,
  resize/keyboard/note reflow, zero and nonzero scroll restoration, context/full
  file/keyboard range,720p/1080p/1440p/4K and actual720×460 client size.
  Evidence:pane-reuse-aux-native-03/report.json plus screenshots. Minimum image
  reveals a pre-existing header-search label wrapping outside the topbar; no
  pane-reuse regression shown, but compact header needs a follow-up UI fix.
- Auxiliary01 failed because its script switched files before the save dialog
  completed. Auxiliary02 captured transient scroll427px while a pending layout
  restoration was returning to0. Auxiliary03 records both transient427 and
  settled0, restores0 across files, and preserves entry8 at3px with nonzero
  scroll301. These were harness synchronization errors, not proven app defects.
- Pane source remainsb1d14ea9, unchanged. It now has native correctness gates
  and is queued for matched canonical A/B against0560 on WSL/ext4. No reuse
  performance gain is claimed yet. Auxiliary app/supervisors stopped cleanly.
- Native helper deployment latest LOCALAPPDATA-aware revision passed39 host
  tests,14 embedded tests, and Windows-target source compilation. Official
  sourcef2ffb3cc; no VM deployment/timing yet. Missing/empty HOME cache fallback
  is fixed and tested. Build supervisors are prepared but unexecuted, gated on
  explicit VM BUILD RELEASED after native UI timing ends.
- Pushed CI follow-ups39293a7 and1135a59 fix Windows-invalid test filenames,
  asynchronous stack row selection, collapsed-note test expectations, and use
  one socket with checked write/graceful response finish in the MCP fixture.
  Latest host70Rusttests pass1ignored. Actual prior native MCP test passed
  100/100serial repetitions, but Windows CI had failed before_launch=true with
  Err(port in use) at192ms; exact IO cause remains unproven. Production timeouts
  and listener validation are unchanged. CI1135a59 still needs verification.


## Pane performance decision

The pane-reuse performance pilot completed four valid runs, six samples per
action. It failed the predeclared continuation gate and is discarded for this
workload. No 20-repetition jobs ran. Working-tree median was 444 ms for baseline
and 475 ms for reuse; branch-first 428.5 versus 519.5 ms, branch-final 356.5
versus 435.5 ms, stack 442 versus 514 ms, and working-tree comment 482.5 versus
555.5 ms. Native correctness passed; performance did not.

The added cost is outside foreground native IPC. WT IPC stayed near 192 ms,
while its non-IPC remainder rose from 258 to 285 ms; branch-final remainder
rose from 263 to 335.5 ms. These are UI/render/frame/wait intervals, not a
proven paint diagnosis. Preserve both cold/fresh outliers and all raw evidence.
Decision: build/autoresearch/wsl-boundary/pane-reuse-v3-decision.json.

Exec34954 stopped at the review gate with code 3. All recorded apps/drivers
and their supervisors were verified stopped; ports 29225 and 28867 are free.
The next candidate remains native helper placement. Before building its two
GUIs, compare the exact PowerShell cache query with native cmd environment
lookup in both ext4 and NTFS cwd, since discovery startup could erase the
measured native-image gain. The cache-query component test owns the VM briefly;
no GUI/timing/build may overlap it. Current CI fixture smoke follows, then
helper builds after explicit VM BUILD RELEASED.


## Current live work and verified checkpoint

GitHub native CI for pushed commit `1135a59f3a51253709d652d1e4ec82fa8b32ce09`
is green for both workers and both packaged desktop builds:
https://github.com/traplol/diff-tool/actions/runs/45692019847.
The current smoke harness also passed on the VM against the unchanged b2
runtime, covering the complete comment/export/suggestion/stage/commit workflow
and actual 720p through 4K client sizes. Its owned MCP process was verified
absent and port 28869 free. Log: build/checkpoint/native-smoke-1135a59.log.

The helper placement gate found that the PowerShell-only location query would
erase its expected gain. From the product's ext4 cwd, median query time was
502.58 ms versus 107.48 ms for native `cmd.exe /d /u /c set LOCALAPPDATA`.
From NTFS cwd it was 317.63 versus 90.41 ms. All 20 outputs decoded to the same
absolute Windows cache path. These are process/query costs, not GUI results or
OS-cold data. Evidence: native-helper-deployment/query-component-02/.

The revised helper candidate uses that measured cmd fast path, strict UTF-16LE
parsing and exact case-insensitive environment key, with the previous query and
GUI cache fallbacks. Host 41 tests and 16 embedded tests pass; Windows-target
source compilation passes. Official app source:
`252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500`.
Snapshot `03fecde11c0a48a50b437c089ff6e22d6521ede6352dda4c01477a9f70349739`.

A single helper build supervisor is live on the VM: PID 121613, start ticks
14259473; host runner PID 4180899, exec session 19070. Last verified child
121695 was in linux-remote-tests. Inspect this same owner before any retry;
never restart because an observation expired. Record:
`/home/max/benchmarks/branchline-boundary/native-helper-deployment-b2de070-03fecde11c0a-native/supervisor.json`.
The agent owns the VM for serial tests and both GUI builds. No GUI, native-cache
preseeding or scoring is authorized during builds. Native cache/lifecycle gates
and exact GUI comparisons remain required afterward.

A separate host-only staged-anchor metadata candidate is being implemented at
`build/experiments/staged-anchor-metadata`. It adds a typed metadata proof and
worker operation for unchanged Staged M notes, preserves displayed-snapshot
precedence, index/HEAD guards and all existing frozen-patch paths. It is not
verified or promoted. New matching workers must be built for that operation;
old 6a/328 helpers cannot be reused. The agent has been asked to version the
internal protocol accordingly. No VM work is authorized for that candidate yet.

The goal remains active. The latest concrete progress is the measured 35%
status improvement, the rejected pane-reuse hypothesis, green cross-platform
CI, successful complete native smoke, and elimination of the costly helper
query before GUI measurement. The final four-cell matrix, genuinely cold
scenarios and the complete under-250 ms requirement are still incomplete.


Staged verifier handoff: the host-only candidate is now frozen at source
`935501731502ce5f5fbe144284c0564073f52dd3087af11604f58cbb2fe72c9f`.
Snapshot: `build/experiments/staged-anchor-metadata/source`; seven-file patch,
README, proof and baseline records are adjacent. Exact final GUI suite passed
77 tests with one existing ignored; protocol-2 worker passed 30 unit tests and
one real stdio test. An initial ETXTBSY fixture failure was retained; the exact
final serial rerun passed without a workaround. Independent review corrected
raw unsupported tree-mode handling, and final KISS said simple enough.
All host test sessions exited. No production changes, VM validation or timing.
Fresh matching Linux and Windows workers are mandatory for native builds;
old protocol-1 helpers must not be reused. Next native work remains queued behind
the live helper-deployment build supervisor 121613 / host exec 19070.


## Latest native deployment and verifier correction

The helper build supervisor 121613 / host exec 19070 completed successfully.
Both immutable GUIs were packaged with matching preserved workers and source /
fixture checks: Linux SHA 67815591856441398d6d026bb9f828a1d67a71f73b3c241b802715f033a0fcbf;
Windows SHA 684cbe8293d3c737c23aaa026da190b75117d9121668ca4c838672c1152675a9.
Native runtime correctness now owns the VM; do not restart those builds.

The first Linux GUI → NTFS gate installed the exact worker in a previously
absent, owned Unicode/metachar native cache. Public root, pinned refs and full
30-file stack were correct. After the unchanged canonical two-frame settle,
12 consecutive rAF intervals were 16–17 ms (median 16.5), visible and focused at
1280×800. This is an idle diagnostic, not a comparison-frame or latency score.
Log: build/experiments/native-helper-deployment/first-linux-gate.log.

Native hit/no-rewrite, normal Connection Drop, corrupt-cache repair, short
blocked-cache fallback, cmd-unavailable PowerShell fallback, actual worker
invalid-op/EOF checks, busy EOF, and GUI/MCP idle/busy death cleanup have passed
in Linux GUI → Windows gates. The last completed supervisor was 130686 /
start ticks 14476753 / exec 25690. Busy requests were observed with actual Git
children; native workers exited in bounded probes. A prior 270-UTF16-unit
foreign fallback path timed out; the 215-unit short path passed. Preserve that
failure and compare the unchanged baseline on the same path before assigning
cause. Reverse Windows GUI → WSL gates and same-path baseline remain pending.
No scoring or performance promotion has occurred.

The staged verifier review found and reproduced a new alternate-index bug:
libgit2 read default index A while Git honored GIT_INDEX_FILE=B, leading the
unguarded proof to invent a Staged location instead of the CLI's Unstaged one.
A direct presence guard now declines this shortcut before local/worker routing.
The isolated child regression and all 78 GUI tests / 30 worker tests / one
stdio test pass; one existing GUI test remains ignored. New source:
aba80d9202698734d4915c9b652d58406e3602c1dc277983e97a7f6b59e80404.
Previous 935 source, proof and tar are retained in previous-935501731502.
Refreshed native tar/plan are unexecuted and still require VM STAGED BUILD RELEASED.

Windows baseline/status GUI controls are prepared, unexecuted, with an exact
VM WINDOWS CONTROLS BUILD RELEASED gate. Runner:
build/autoresearch/wsl-boundary/windows-controls-b2de070-build.py.
They must use the verified native GNU 328 helper and the same VM compiler/cache.

A bounded source-free UI phase injector is prepared under
build/experiments/ui-phase-probe. It hooks existing CodeMirror calls and rAF
callbacks without adding frames, native requests, geometry reads or polling.
Host syntax/mock checks pass. It has not run on the VM. Use it after the current
owner releases the UI, preserve the full canonical timing, and do not attribute
unmeasured gaps to painting. Existing comment-jump-refresh is a separate,
host-tested but unmeasured frontend candidate; do not recreate or promote it
without native evidence.
