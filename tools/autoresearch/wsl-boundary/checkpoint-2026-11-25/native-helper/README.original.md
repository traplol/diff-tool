# Native helper deployment candidate

Status: current cmd cache-query revision host-validated. Unmeasured and unpromoted; VM build awaits separate release. No VM access or production source edits.

The full source snapshot starts from current tracked bytes at
`b2de070becf3fcba2d47557efd375221c586f273`. Only
`source/src-tauri/src/git/remote.rs` differs. The initial snapshot manifest is
`source.json`; final identity is `candidate-manifest.json`; the portable narrow
patch is `candidate.patch`; gate results are `summary.json`.

## Behavior

Windows to WSL retains the existing cached ELF as a verified source. A constant
shell program receives its path and SHA as separate arguments. It uses the WSL
user's absolute XDG cache or HOME cache, validates an existing SHA-versioned
worker, or copies to a unique temporary file, checks SHA, sets permissions, and
atomically renames it. The shell then execs the worker with inherited raw pipes.
If cache I/O or permissions are unavailable, the shell removes its temporary
file, verifies the original source SHA again, and execs that source. A copied
file with the wrong SHA fails closed. GNU `mv -T` prevents a cache pathname that
is a directory from swallowing the temporary file.

WSL to Windows first executes the measured constant `cmd.exe /d /u /c
set LOCALAPPDATA` query. Its parser strictly decodes UTF-16LE and matches only
an exact case-insensitive LOCALAPPDATA key. Missing/empty environment or an
unavailable cmd uses the unchanged native PowerShell known-folder fallback.
Invalid Unicode or a non-drive path falls back to the original GUI cache.
Existing wslpath mapping and Rust atomic materialize then install directly on
the Windows volume. The worker is launched directly from that cache path.

PowerShell never owns or forwards worker protocol pipes. The existing direct
`Connection.child`, cwd, Git environment, request IDs, root mapping, read-only
worker operations, and kill/wait handling are unchanged. Initial discovery,
validation, copying and installation all remain in the first Worker::start,
which is inside repository open. No native cache is pre-seeded by this candidate.
The helper bytes embedded in the GUI are unchanged by the source patch.

## Host proof for the current revision

`host-proof-cmd.json` binds the current app source and patch to the
passing logs. Prior source identity and patch remain under
`validated-before-localappdata-*`. Supervisors pass syntax checks and remain
unexecuted; they require the separate `VM BUILD RELEASED` gate.

- `host-all-tests-cmd.log`: 41 pass, 1 existing WSL-required test ignored.
- `host-embedded-tests-cmd.log`: 16 remote tests pass with embedded-helper cfg, 1
  existing WSL-required test ignored. The include bytes are a compile-only text
  fixture, not a claimed executable or placement measurement.
- `windows-source-check-cmd.log`: actual x86_64-pc-windows-gnu check of source
  and tests passes using the existing Rust 1.89 Windows sysroot and mingw tools.
- `windows-source-check.log`: the first build-std attempt failed because offline
  addr2line 0.25.0 was absent. The existing sysroot supplied the passing check.
- Independent KISS review: simple enough.

Bootstrap tests cover new/cache-hit/corrupt repair, concurrent installs,
wrong copied bytes, source changes before fallback, read-only cache, a blocked
destination, temporary cleanup, relative XDG fallback, missing/empty XDG and HOME fallback, spaces, quotes,
metacharacters and Unicode. A native exec test checks that the worker has the
owned shell PID and that NUL, non-UTF-8 bytes and line endings cross pipes exactly.
The existing host protocol-failure test still checks direct-child kill/reap.

Commands, from repository root:

```sh
CARGO_TARGET_DIR=/tmp/branchline-native-helper-target cargo test --offline --manifest-path build/experiments/native-helper-deployment/host-harness/Cargo.toml
CARGO_TARGET_DIR=/tmp/branchline-native-helper-embedded-target BRANCHLINE_GIT_WORKER_PATH=/home/max/workspace/merge-viewer-native/build/experiments/native-helper-deployment/baseline-remote.rs RUSTFLAGS='--cfg branchline_git_worker' cargo test --offline --manifest-path build/experiments/native-helper-deployment/host-harness/Cargo.toml git::remote
CARGO_TARGET_DIR=/tmp/branchline-native-helper-windows-check BRANCHLINE_GIT_WORKER_PATH=/home/max/workspace/merge-viewer-native/build/experiments/native-helper-deployment/baseline-remote.rs RUSTFLAGS='--sysroot /tmp/branchline-windows-check/sysroot --cfg branchline_git_worker' cargo check --offline --target x86_64-pc-windows-gnu --tests --manifest-path build/experiments/native-helper-deployment/host-harness/Cargo.toml
```

## Remaining proof before promotion

Run native deployment and the canonical GUI scorer serially after VM release.
Record cache paths, mount/volume identity and exact worker SHA. Measure both an
absent native cache and an already-correct cache without preparing cache contents
outside timed open. The query component in `query-component-02` rejected PowerShell-only startup
(502.58 ms median from ext4 welcome) in favor of cmd (107.48 ms). This belongs
to the same helper experiment; current GUI/deployment performance is unmeasured.
`query-decision.json` preserves the measured decision without promotion.

On actual Windows and WSL, check native-cache repair and optional fallback,
path quoting, Windows UTF-8 cache discovery, native NTFS materialize permissions
and atomic replacement. Run the existing ignored WSL cwd test. Verify public
root identity and unchanged Git environment, plus the campaign's read-only
repository fingerprint and full correctness gates.

For both directions, verify normal Drop, protocol failure, and abrupt GUI/MCP
death while workers are idle and while a real synchronous read-only request is
active. Check owned launcher/worker PIDs after completion and check that no
worker starts later after the GUI has died. This patch adds no persistent wrapper,
but it does not prove stronger cross-OS cleanup than the existing direct-launch
implementation. The current worker observes EOF after its active operation
returns; immediate termination on abrupt parent death is still a VM question.
An abrupt OS kill can leave an uncommitted cache temporary, as with the existing
NamedTempFile cache path; successful and handled-failure paths clean their files.
