# Next native-cache evaluation

Prepared and host-validated. VM builds and application launches remain blocked
until root says `VM BUILD RELEASED`. The supervisors remain unexecuted. The
separately authorized read-only query component and root native CI smoke have
completed. Root granted one serial VM build supervisor; runtime/scoring remains
blocked until a separate release.

## Source and embedding identity

`build-plan.json` pins b2de070 plus only `src-tauri/src/git/remote.rs`.
Canonical app source hash is
`252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500`.
Full snapshot hash is
`03fecde11c0a48a50b437c089ff6e22d6521ede6352dda4c01477a9f70349739`.
The current query uses exact measured cmd argv and strict UTF-16LE decoding,
case-insensitive exact-key matching and existing local-drive validation. Cmd
unavailable or no exact nonempty environment value uses the unchanged PowerShell
fallback. Current source passed 41 host tests, 16 embedded-cfg tests and the
Windows-target source check; one existing WSL-only test remains ignored.
`host-proof-cmd.json` binds those logs to this exact source and patch.
Previous passing source/patch/results are retained as
`validated-before-localappdata-*`.

Reuse these preserved workers without rebuilding either:

- Windows GUI embeds GNU ELF SHA
  `328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa`.
  Preserved VM path:
  `/home/max/benchmarks/branchline-boundary/helper-placement/placement-v3-01/linux/native/branchline-git-worker`.
- Linux GUI embeds MSVC PE SHA
  `6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2`.
  Preserved VM path:
  `/home/max/benchmarks/branchline-boundary/helper-placement/placement-v3-01/windows/foreign/branchline-git-worker.exe`.

Storage-worker excludes remote.rs, so this candidate changes no worker source.
The supervisor verifies both original hashes, copies them to owned embedding
files, and verifies exact bytes are inside each built GUI.


## Completed read-only query component

`query-component-02/results.json` retains 20 successful native query processes:
five alternating PowerShell/cmd pairs in each cwd. All decoded paths are equal.
The exact candidate PowerShell string and SHA, argv, cwd, raw stdout/stderr,
interop PID/start ticks, executable paths/hashes, first samples and observer cost
are retained. No environment override, Git command, fixture write, build or GUI
was used. The first sandboxed SSH attempt did not reach the VM and is retained
under `query-component-01`.

| Cwd | PowerShell median | cmd median | Median paired saving |
| --- | ---: | ---: | ---: |
| Owned ext4 welcome | 502.58 ms | 107.48 ms | 395.11 ms |
| Actual NTFS kernel | 317.63 ms | 90.41 ms | 228.60 ms |

First ext4 samples were 600.15 ms PowerShell and 139.30 ms cmd. These are fresh
processes with first samples retained, not OS-cold claims. Root rejected the PowerShell-only f2ff source and approved cmd's UTF-16LE
`set LOCALAPPDATA` fast path with retained PowerShell known-folder fallback.
The new source is host-validated; its native GUI performance remains unmeasured.
Do not build a changed query without advancing the source/patch/proof records.

## One runnable supervisor after release

From the host repository root, after the explicit release:

```sh
python3 build/experiments/native-helper-deployment/run-after-release.py --release 'VM BUILD RELEASED'
```

This verifies the completed host proof and each recorded log hash, and reuses
those checks when the exact app source is unchanged. It runs host checks again
only if the app source hash changes. Missing or inconsistent proof for unchanged
source stops the runner. Native VM tests remain required because they use a
different OS and toolchain. It packages only the pinned
snapshot files plus build plan and VM supervisor, transfers to a fresh owned
input directory, and holds one foreground SSH/WSL supervisor until completion.
It does not detach, start a GUI, run a scorer, or seed a native helper cache.

The VM supervisor records PID plus Linux start ticks and each child phase PID,
argv, cwd, selected build environment, start/end, exit and complete log. It runs
with one Cargo/CMake job, executes Linux remote tests, builds the Linux GUI,
builds/runs native Windows remote tests, then builds the Windows GUI. Original
helpers are reused. Each GUI is copied to an owned immutable binary path before
the next build. Both fixture fingerprints are checked before and after against
`db66016f41a604c102cc81121c4e81f9c93db3b3f4430ef51dab5ba1c9da97c2`.

Host phase record: `next-supervisor.json`. Remote phase record:
`/home/max/benchmarks/branchline-boundary/native-helper-deployment-b2de070-03fecde11c0a-native/supervisor.json`.
Inspect a prior record and its process identity before any retry. Do not launch a
second supervisor while its recorded owner is live.

Resulting binaries:

- `/home/max/benchmarks/branchline-boundary/binaries/native-helper-deployment-b2de070-03fecde11c0a/branchline`
- `C:/Users/max/branchline-bench/binaries/native-helper-deployment-b2de070-03fecde11c0a/branchline.exe`

## Native fidelity and lifecycle gates before timing

Run these serially after builds, with separate evidence directories and owned
process records. The build supervisor deliberately stops before these gates.

1. Run actual native cache discovery with a portable inherited LOCALAPPDATA,
   absent LOCALAPPDATA, empty LOCALAPPDATA and a UNC value. Verify UTF-8 Unicode
   output, drive-path validation, known-folder fallback, and original-cache
   fallback. For a WSL-set portable variable, use normal WSLENV transfer semantics
   (`LOCALAPPDATA/w`), not a product-specific option. Keep the exact environment
   in the evidence.
2. Open each actual cross-boundary checkout through the candidate. Record helper
   SHA, native cache path and native filesystem/volume identity. Verify the GUI's
   public root string, worker execution root, cwd and normal read-only Git
   environment. Retain exact request IDs and response frames for the independent
   direct-worker checks. Check canonical fixture fingerprints and raw
   HEAD/index/ref hashes before and after. Do not refresh an index or change Git
   configuration.
3. Check actual missing/native-hit/corrupt native caches and unavailable native
   cache fallback. Only move/delete files created by this run. If a native user
   cache existed before the run, preserve it and isolate through the existing
   OS cache environment variables before testing absence. Retain the original
   state and restoration record. Verify copied wrong bytes fail closed.
4. For actual helpers in both directions, close stdin while idle and busy; wait
   and verify the Hello worker PID is gone. Check normal repository Drop and
   protocol-error cleanup through the production Connection path. Existing host
   tests prove the latter with a fixture, but actual Windows interop still needs
   its own native fault fixture. A real well-behaved worker cannot spontaneously
   return the wrong request ID; do not claim a domain error proves protocol-error
   handling.
5. Abruptly terminate the owned GUI and, separately, its owned MCP process while
   idle and during a real long read-only request. Identify each process by binary,
   PID and creation/start time before stopping it. Check both native worker and
   launcher PIDs repeatedly until exit, and check again after enough time for
   any interrupted install to have completed. There must be no delayed worker
   launch. Record cleanup latency rather than assuming WSL propagates death.
   The worker only observes EOF after its current synchronous request returns;
   this inherited behavior is still a required native proof. Never broad-kill
   worker names or unrelated process trees.

## Timed GUI comparison

Use the unchanged canonical host controls under
`tools/autoresearch/wsl-boundary/`. Launch with `launch.py` for Windows and
`launch_linux.py` for WSLg; keep each Linux launcher in a foreground exec session.
Keep the production renderer and MCP autostart. Reserve currently free loopback
CDP/WebDriver/MCP ports after the prior owner has released them. Record exact
source/binary/helper hashes in every launch record.

Use separate review profiles to seed the two real comment anchors, then stop the
seed process. For an absent-cache sample, restore absence of only the owned
native/source worker cache files after seeding. Leave the review data intact.
Record absence immediately before launch; do not copy, hash or execute a helper
between that record and timed Open. Native location query, directory creation,
validation and installation must occur in product Worker::start inside Open.
For an existing-cache sample, retain the cache created by the previous timed run
and use a fresh GUI process. Do not describe either case as OS-cold.

Measure baseline b2de070 and this candidate as a paired serial series with the
same fixture, comments, environment, launcher and free ports. Both cross cells
and both same-side controls remain required. First use a bounded diagnostic
three-interaction run; only a valid result can proceed to the campaign's complete
sample count. Do not combine the separate status candidate into this source.

Scorer command shape, with real launch record and loopback engine endpoint:

```sh
python3 tools/autoresearch/wsl-boundary/score.py \
  --source build/experiments/native-helper-deployment/source \
  --manifest build/autoresearch/wsl-boundary/workload.json \
  --launch-record OWNED_LAUNCH_JSON --case windows_linux \
  --cdp http://127.0.0.1:OWNED_CDP_PORT \
  --run-dir FRESH_RUN_DIRECTORY --label native-helper-deployment --repetitions 3
```

For WSL cells replace CDP with `--webkit-port OWNED_FORWARDED_PORT --session
ACTUAL_SESSION_ID` and use `--case wsl_windows` or `wsl_linux`. For Windows same-side
use `--case windows_windows`. The host repository must still report pinned
b2de070 when the canonical scorer calculates source identity; stop and create an
isolated pinned Git checkout if root has advanced HEAD. Never override the
scorer's source or completion checks.

A full keep decision requires valid GUI output, all lifecycle/fallback gates,
unchanged fixture identity and an improvement under the same measurement
contract. Native placement component results alone cannot promote this patch.
