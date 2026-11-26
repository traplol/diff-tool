# Parallel untracked native R2 controls

Prepared on the host only. No R2 native build, test, benchmark or VM call ran.
No GUI build is requested. Candidate f15 and baseline d5 retain their frozen
canonical 49-file identities and pinned b2 Git HEAD.

The entire r1 attempt remains in the parent directory. Its native candidate
artifact reused the prior tracer executable
`515100518438c763128b627626ceb228954b615e57ee0696321a7f00cb92625e`.
Cargo reported the new manifest with `fresh:true`; frozen source mtimes and the
shared target permitted reuse. Strict worker stderr rejected that run. The r1
attempt establishes no candidate correctness result or speed improvement.

R2 cleans only the owned `branchline-git-worker` root package for the MSVC
release target. It retains dependency caches. Both release and unit artifacts
must report the exact manifest, main source, bin target/kind, release opt level,
test flag and `fresh:false`. R2 copies the reported executable only, checks its
reported filename and owned release path, and rejects the old tracer hash.
Unit test paths may use either Cargo's release/build or release/deps layout.
The compiled Windows suite must list and pass all 28 frozen test names.

A self-contained real b2 Git bundle reconstructs HEAD and the source index
without checking out over candidate files. Canonical app enumeration, every file
hash, Git HEAD/tree and the source hash are checked before and after execution.
The host archive round trip passed these source checks. The launcher repeats
archive verification before any SSH call.

Only the existing component sequence runs: A/B/B/A, each with Hello/Open, first
WT, five repeated WT requests, then frozen patch validation and final Hello.
All 24 full raw trees and all decoded patches must match. Fixed workload,
native Git identity, raw fixture fingerprint, index/config/HEAD hashes and stat
data remain guarded. Worker stderr must remain empty through process exit.
Each native PID/creation/image must remain exact and disappear after graceful
EOF. Forced cleanup invalidates the run. R2 also checks that exact failed r1
supervisor 196994/start15549528 is absent before proceeding.

After root releases the serial VM slot, run:

```sh
python3 build/experiments/parallel-untracked/native-r2/run-native.py \
  --release 'VM PARALLEL UNTRACKED NATIVE R2 RELEASED'
```

The launcher refuses an existing R2 owner record. It copies successful native
evidence and both generated executables back to this directory. Inspect raw
evidence and terminal ownership before interpreting component measurements.
Canonical GUI correctness and scoring remain necessary before promotion.
