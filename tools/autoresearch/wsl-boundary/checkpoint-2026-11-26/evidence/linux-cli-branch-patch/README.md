# Linux CLI branch-patch candidate

This candidate tests one new hypothesis: after Linux Git CLI supplies branch
statistics, the existing CLI patch path may avoid the observed native first-patch
penalty. It adds one Linux filter in `with_patch_sections`. The existing
`diff_patch`, section selection and codecs produce branch patch output. Windows
selection, frozen working-tree sections, blob/revision reads, search, transport,
errors and cancellation code are unchanged.

The base is the exact integrated candidate at
`../linux-cli-integrated/source`, canonical 49-file hash
`c2006e96fdcb418c83b35c02741f3acafe5d79fc4bdfa0608f5256fd3ef176c1`.
The new canonical hash is
`fcc050e9843ae3caa7826a00cbbd684ecc6e8805ce12994f364e21dc96d5e704`.
Both use real Git HEAD `ce75cd6be9f0a0f1d0587aef0ce603d21c0fc3df`.
This is not based on the old b2 pilot.

`source/` owns its Git directory and independently copied objects, has no object
alternates, and retains all 551 tracked files. `baseline-source.json` and
`source.json` record canonical app identities; `baseline-tracked.json` and
`tracked-source.json` cover all tracked files. `candidate.patch` is the complete
incremental diff against c200. `production.patch` contains its one policy line;
`evaluation.patch` contains the test extension. `full-head.patch` also includes
the inherited c200 branch-summary policy relative to ce75. Only `git.rs` and
the existing stdio test change against c200. All old test lines remain.

The stdio extension checks exact branch display rows and hunk starts before
reopen, after the branch tip moves and the worker reopens, and after a worker
restart. It uses the existing real worker and fixture. No harness or dependency
was added.

The motivating observations come from the separate old primary pilot. Its
Open `display_patch` values were A 63.0/37.1/38.2 ms and B 82.9/76.1/82.1 ms.
Its final20 patch p95 changed 13.6 to 53.3 ms for `branch_first`, and 16.1 to
58.3 ms for `comment_branch`. Native summary generation reads changed blobs;
CLI summary generation does not populate libgit2's object cache. That explains
a plausible mechanism, not a measured decoder attribution. These numbers are
not performance evidence for this candidate or for integrated c200. Candidate
Open IPC alone was 524.1–571.0 ms in that pilot, so patch savings alone cannot
meet the 250 ms Open goal.

Preparation is host-only. No tests, builds, SSH, VM calls or scoring ran.
Main and integrated c200 source bytes remain unchanged. The candidate is queued
until c200 completes its full baseline matrix. A fresh KISS-only review is
pending because all four agent slots were occupied at preparation. See
`prepared.json` and `TEST_PLAN.md`. There is no promotion or performance claim.
