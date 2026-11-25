# Stable file-tree DOM experiment

Prepared source: `69589c0283e3560c6c1edc160064c47f7794068f7a0bdfa824329ab158e73d73`.
Exact b2 baseline: `56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272`.
`baseline-source.json`, `source.json` and `candidate.patch` pin the three-file
change. Main app, canonical controls, parallel-untracked and Git command-cost
candidates remain unchanged. Focused review-ui tests, all five frontend test files and the Vite production
build pass on this exact source. No native build, launch, timing, commit or
promotion has occurred.

Hypothesis: replacing identical file-tree buttons and folder elements on each
fresh comparison array contributes avoidable WebKit layout/rendering work.
Existing UI diagnostics show native WebKit worker CPU in post-IPC frame gaps;
they establish a rendering cost but do not prove this particular change helps.
The renderer and default acceleration settings remain unchanged.

`canReuseFileTree` checks the same repository root and same ordered path, old
path, status and group. Those fields cover button titles/labels, status badges,
folder paths, group labels and index handlers. OIDs, modes, counts and frozen
patch bytes can differ without changing that tree. Reorder, add/remove, rename,
status/group or root changes rebuild it.

On reuse, `fileTree.source` receives the fresh comparison array. Existing index
handlers still resolve the current global state. The editor retains its existing
teardown, fresh file lookup, display_patch request and reconstruction after each
comparison. Viewed indices, filtering and active selection retain their update
paths. Pair/root changes invalidate the tree before either nonempty closed-folder
set is cleared, preserving the existing expanded-folder reset.

Three semantic frontend tests cover snapshot-only differences, each visual
invalidation, ordering/membership, roots and empty trees. They make no source-text
assertions. Root released host checks; the focused file, complete five-file
frontend suite and Vite build each exited0. Source identity remained unchanged.
`frontend-checks.json`, `proof.json` and the three stage logs retain exact commands,
terminal states and hashes. No failures occurred. All jobs have stopped.

A fresh independent KISS pass remains required before any future commit; all four
live slots were occupied when checks finished. Host tests alone cannot verify DOM
identity or fresh editor data.

Native correctness gates must compare real button/folder identities across
same-visual branch refreshes and layer changes, while verifying the newly
selected patch/OIDs/markers. Exercise index clicks, keyboard navigation, viewed
badges, filters, active selection, rename titles/status/group updates,
reorder/add/remove and same-shaped repositories with different roots. Collapse
ordinary and search folders, then change pair with matching visual entries;
verify the reset opens them. Include partial staging and unchanged-file lists
with changed patch content. Keep the canonical end-to-end action boundary and
default rendering settings. Only native A/B evidence can establish a speedup.
