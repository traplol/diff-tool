# Linux CLI branch comparison experiment

Exact source: `a4a08d4123b2c72cfc2c12aa56cefeb06c57316ac647c7d59d7ee58d0b4ba9d5`.
Baseline: b2de070, source `56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272`.
The isolated `source/` has real detached Git metadata, no alternates, and all49
canonical app-file hashes. Root production source and canonical controls are
unchanged. This candidate has no VM build or timing yet and is not promoted.

Hypothesis: the existing Git CLI branch-summary implementation avoids measured
Linux libgit2 first-comparison CPU on the kernel workload. Root's component probe
is recorded at VM path
`/home/max/benchmarks/branchline-boundary/branch-native-vs-cli-1795650681826697344/state.json`;
its local copy is pending. That probe is evidence for the hypothesis, not a score
for this candidate or GUI latency.

The production patch changes one existing `compare_trees` filter condition:
Linux execution selects the existing CLI compatibility command and parser.
Windows and other OS native comparison behavior remains enabled. Logical GUI
platform does not choose this policy: Windows GUI → WSL uses its actual Linux
worker, while WSL GUI → Windows uses its actual Windows worker. Git flags,
merge-base handling, object IDs, error handling, patch paths, APIs, protocol and
configuration retain their existing implementation. No cache or new abstraction.

Host gates pass serially with source unchanged:25 worker unit tests, one real
persistent-stdio test, and70 GUI-library tests with one existing ignored test.
These are the existing pinned b2 suites. No test was added merely to assert the
configuration condition. A fresh independent KISS pass found the final one-line
patch "simple enough". All started host supervisors and test actors are absent.
See `proof.json`, `host-gates.json` and the two test logs. An initial preparation
import failed because the scorer's sibling driver directory was missing from
sys.path; it occurred before source edits and was fixed only in the caller.

Next: build the exact GNU worker, verify native kernel metadata and patch parity,
build a matching Windows GUI that embeds that worker, and run canonical GUI A/B.
Keep initial/fresh-process, first-use and repeated samples separate. Preserve the
normal renderer, exact kernel fixture, markers/comments and two completion frames.
No native or GUI improvement is established by these host gates. The independent
f15 parallel-untracked native-preflight archive remains unchanged and ready.

## Primary native build prepared

`native-build/` contains the serial primary build caller. Its real Git bundle
and tar passed a fresh host extract/init/fetch/read-tree/rev-parse round trip,
including all49 canonical app-file hashes and181 snapshot-file bytes. The caller
repeats this verification before any SSH. It builds only the GNU static worker
and Windows GUI for this first primary experiment. Protocol remains1; no opposite
PE worker, Linux GUI or helper-placement candidate is included.

A separate f15 experiment found stale shared Cargo outputs despite correct input
file hashes. The a4 r1 preparation never ran on the VM and is preserved under
`native-build/previous-r1/`. Current r2 cleans only the root worker/app packages
in the VM's generated target caches, preserves dependency caches, and requires
Cargo JSON producer records for the exact manifest, target, optimized profile
and executable with `fresh:false`. It copies the reported executable paths.
Native unit/stdio artifact records and test names must match the pinned25+1
suite; the packaged GUI must contain custom-protocol assets and the fresh GNU
worker byte-for-byte. Old host a4 gates explicitly compiled both exact candidate
root package paths; `host-producer-proof.json` preserves that evidence without
repeating tests or deleting host release artifacts.

After the root agent releases the serial VM slot:

```sh
python3 -u build/experiments/linux-cli-branch/native-build/build-after-release.py \
  --release 'VM LINUX CLI BRANCH BUILD RELEASED'
```

The native worker runs25 unit tests and one real stdio test. Its kernel proof
checks30 exact metadata/count/OID records for each of main→first, first→final
and main→final. The Windows GUI embeds the verified new GNU worker. Both fixture
fingerprints and index/config/HEAD bytes/stat guards must remain unchanged.
The caller copies terminal native evidence and both binaries back to the host
and verifies their hashes. No VM execution has occurred for this preparation.

`evaluate-windows-wsl.py` reuses the proven canonical caller for the primary
Windows GUI/WSL cell. It requires the completed native producer/build evidence
before running3/3/20 repetitions per variant with the existing profile, comments,
scorer, renderer and two frames. Its separate runtime release is
`VM LINUX CLI BRANCH RUNTIME RELEASED`. Fresh Open and every first-use result
remain separate from repeated results. Full four-cell/cold acceptance remains
necessary before promotion or completing the goal.
