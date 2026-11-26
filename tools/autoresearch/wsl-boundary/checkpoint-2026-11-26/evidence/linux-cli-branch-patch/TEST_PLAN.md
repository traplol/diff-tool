# Held verification plan

Do not run this plan while native build session 36761 owns execution. This
candidate remains queued until integrated c200 completes its full baseline
matrix. Recheck the campaign owner and terminal records before starting any
test, build, SSH call or scorer. No part of this plan has run.

1. Obtain a fresh KISS-only review with no inherited conversation. Give the agent
   the accepted one-policy-line scope, `candidate.patch`, repository instructions
   and nearby `with_patch_sections`/stdio code. Save its result. Do not commit
   before a clean pass.
2. Verify canonical `source_identity(source)` against `source.json`, real ce75
   HEAD, no alternates, and both full tracked manifests. Verify c200 and main
   still match their recorded baselines. Source identity calculation is metadata
   verification, not scoring.
3. Apply `evaluation.patch` to a separate evaluation-only copy of c200. Preserve
   c200 itself and record that copy's distinct source identity. After execution
   is released, run the extended stdio regression on that control and on this
   candidate. This checks the same exact branch output before/after ref movement,
   reopen and worker restart on both implementations.
4. Reuse the existing serial host-gate procedure from
   `../linux-cli-integrated/run-host-gates.py`, directed at this candidate and
   new result files. Keep the existing offline/locked manifests, dependencies,
   single-job limits and GUI library environment. Force fresh root package
   compilation using the established package-only clean/touch procedure; do not
   accept stale Cargo output. Require exact candidate manifest/source paths,
   `fresh:false` root test producers and terminal exit zero. The suite counts
   remain 25 worker unit tests plus one extended stdio test, and 70 GUI tests
   plus the existing ignored test; the extension adds assertions, not a new
   test function. Inspect unexpected names/counts instead of treating counts
   alone as source proof.
5. Run all existing frontend tests without changing them. Relevant Rust coverage
   includes `literal_names_binary_rename_line_numbers_and_scoped_untracked`,
   `streamed_patches_keep_type_change_sections_and_byte_paths`,
   `whole_file_keeps_branch_blob_ids_after_a_rename_and_tip_move`,
   `revision_file_distinguishes_text_binary_and_missing_submodule_objects`, and
   `display_patch_preserves_git_rows_and_frozen_working_tree`. Retain existing
   sparse-checkout, frozen-index, cancellation and child-reaping coverage.
6. Build and validate exact-source Linux/Windows workers and GUI artifacts with
   the existing packaging controls. Record fresh compiler producer paths,
   dependency features, canonical source hash, binary hashes, embedded worker
   bytes, frontend assets and graceful worker cleanup. Run the exact native
   Windows test set from current integrated c200, including its 23 unit names,
   and the same extended real-stdio test. Windows production selection must
   remain native where it was native before. Do not reuse c200 binaries as
   candidate artifacts.
7. Only after c200's full baseline matrix is complete, freeze a separate
   c200-versus-candidate comparison using the unchanged canonical workload,
   scorer and guardrails. Run all four cells serially. Retain at least three
   fresh-process Opens and final20 action samples per cell, with correctness,
   exact source/binary identities, both fixture guards and cleanup evidence.
   Preserve raw `display_patch` IPC and total UI times for Open, branch_first,
   branch_final, stack and branch-comment jumps. Keep first use, p50, p95 and
   max. Do not move required work outside the measurement interval.

Reject invalid content, altered snapshots, errors, stale producers or missing
samples before considering speed. A patch IPC improvement cannot establish the
full Open target while Open IPC itself exceeds 250 ms. Keep this hypothesis
separate from the c200 baseline decision and from any handle-reuse experiment.
