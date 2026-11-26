# Native worker cache candidate integrated with current main

Prepared only. Every test, build, SSH connection, VM action, application launch,
and score remains held until root explicitly releases that phase. No source was
committed or promoted, and no canonical control or workload was changed.

The hypothesis is that executing each opposite-OS helper from its execution OS's
native filesystem reduces repository-open cost. Windows keeps its verified
embedded ELF source and deploys the executable into WSL's XDG/HOME cache. Linux
discovers Windows LOCALAPPDATA and installs the PE there. Existing process
ownership, raw pipes, request protocol, and verified-source fallback stay intact.

## Source

- `source/` has a real, independent `.git` directory with detached HEAD
  `ce75cd6be9f0a0f1d0587aef0ce603d21c0fc3df`, all 551 tracked files, and no
  objects alternates.
- `source.json` records the canonical 49-file application identity:
  `89f5019903f293ef659f60240d57b412a3b960b3da701490fe632152d9343b75`.
- `before-source.json` records unchanged main before applying the patch:
  `84753293c8688032f4bf99eeb12fe5082a326f3a59d4d71c02d9d9acf2a02497`.
- `candidate.patch` is relative to that main HEAD. Its SHA256 is
  `2d07d19220affe36067f84f3e2d654fd8501487bd346e417e8cccd2dcdfbb7a2`.
- Only `src-tauri/src/git/remote.rs` differs. Its SHA256 is
  `1046beee3c3dbbad93fc6c8837c2d164ac5ecc26bb536bf39fa106f2d6f52cec`,
  exactly the previous `252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500`
  candidate's file, including all its tests and lifecycle handling. Main's
  original remote file is `fd9d6f8384c1fb9e222a575b9dbb32ec5517de20b3b1c13e2c8214cadad9f3ba`.
- The other 550 tracked files match committed main byte for byte. This retains
  current desktop HTTP fixture shutdown fixes and platform-safe search test
  filenames. No Linux CLI summary change or other unqualified candidate is used.

`before-tracked-files.json`, `candidate-tracked-files.json`, and `proof.json`
record the file comparison. `kiss.json` records a fresh, no-history KISS-only
audit of this final diff: simple enough.

## Worker reuse proof

`worker-source-equivalence.json` compares ten exact source, manifest, lock, and
test files against committed b2, current main, and the prior deployment source.
Every byte agrees with the source hashes in the prior native-build record.
The worker entry point includes `git.rs`; its default `storage-worker` feature
excludes `remote.rs`. GNU production inputs and Windows production inputs are
therefore unchanged. The Windows module was compared even though Linux excludes
it. There are no tracked Cargo configuration or Rust toolchain override files.

This makes only these preserved workers eligible for a future GUI-only build:

- GNU ELF: `328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa`.
- MSVC PE: `6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2`.

Before reuse, verify actual preserved bytes, hashes, protocol, and embedding.
No new worker binary, new GUI build, or new native result is claimed. Old GUI
binaries do not represent this integrated source.

## Retained results

`retained-evidence.json` pins the previous host/native, lifecycle, malformed
response, and Windows GUI records without changing them. Both native malformed
response directions passed with cleanup checked before Connection Drop while
pipes were retained. The tested remote bytes exactly match this candidate.

The old Windows GUI series remains a failed performance result. Two fresh
cache-hit Opens improved by 17.08% and 19.49%, but branch-comment p95 regressed
13.46%; branch-first maximum and branch-comment maximum also failed guards.
No sample is dropped, no guard is waived, and that candidate was not promoted.
Reverse-direction GUI performance remains unmeasured. Old and new source
identities cannot share a qualification result.

## Held verification plan

1. Wait for root's explicit release. The live c200 matrix must first terminate
   and finish exact process, fixture, and transport cleanup. Root should assess
   the high-variance series and decide whether to recalibrate the unchanged
   baseline in all four cells before scheduling another candidate. Keep every
   existing failed series and frozen threshold.
2. Recheck HEAD, no-alternates state, all 551 file hashes, canonical source hash,
   patch hash, worker source proof, and referenced evidence hashes. Keep source
   identity identical before and after each subsequent phase.
3. Run the existing full host worker suite and real stdio integration test,
   full GUI Rust library suite, and frontend tests serially against `source/`.
   Use offline locked Cargo commands and the existing host Linux library setup.
   Record exact Cargo compiler-artifact manifests, source paths, test profiles,
   executable hashes, and fresh root producers. Require the current main tests
   and all nineteen source-declared remote tests appropriate to the target cfg.
   The WSL-only ignored command test needs its actual native environment.
4. Run the existing embedded-helper remote tests and actual native Windows and
   Linux remote test executables against this source. Verify native discovery,
   UTF-16 exact-key parsing, missing/empty LOCALAPPDATA fallback, cache repair,
   atomic replacement, quoting, wrong-byte rejection, raw pipes, and owned-child
   cleanup. Use actual opposite-OS worker bytes when enabling embedded-helper
   cfg. Do not treat the old compile-only text fixture as an executable.
5. Build fresh packaged Windows and Linux GUIs from this exact source. A
   GUI-only build may reuse only the two workers proved above after actual
   hash verification. Record fresh GUI library and binary producer artifacts,
   packaged frontend assets, static worker/Windows CRT checks, and byte-exact
   opposite-worker embedding. Never infer a new GUI hash from unchanged worker
   source. Do not copy the old snapshot's incomplete Git packaging procedure.
6. Bind native fidelity and lifecycle evidence to the integrated GUI/remote
   source. Verify native ext4/NTFS helper execution paths and hashes, public root
   identity, cwd, Git environment, immutable snapshots, patch bytes, comment
   anchors, and repository fingerprints. Preserve the passed Drop, EOF,
   protocol-failure, and idle/busy abrupt-parent-death cases. For malformed
   responses, use the existing external test-module fixture with the exact
   remote source prefix, and check disconnection plus owned-child disappearance
   before Connection Drop while pipes remain retained. Keep that fixture
   outside candidate production source.
7. After a separate scoring release, use unchanged canonical controls and the
   pinned workload for all four GUI/storage cells, serially. Keep default
   renderer settings, first-use observations, all raw samples, and all guards.
   Measure absent-native-cache Open separately from fresh-process cache hits;
   installation and discovery stay inside timed Open, with no pre-seeded
   candidate native cache. Treat fresh-process results as fresh-process results.
   Require all correctness and performance gates for this exact integrated
   source before considering promotion.

These are pending checks, not passing results. No new evaluator, supervisor,
runtime control, configuration setting, or benchmark series was created.
