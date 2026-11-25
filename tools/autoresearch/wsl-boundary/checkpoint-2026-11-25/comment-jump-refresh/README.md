# Comment jump refresh experiment

Base: frozen combined-v3 frontend, copied from
`build/autoresearch/wsl-boundary/candidate-combined-v3-source`.
Only frontend files and package manifests are copied; no Rust targets are copied.
Production source and the canonical scorer are unchanged.

Apply `candidate.patch` to a fresh combined-v3 source copy. The two product files
are `frontend/app.js` and `frontend/editor.js`. The optional regression file is
`frontend/comment-jump-refresh.test.js`.

The app already creates the target editor with current notes after its fresh
Open. It also unfolds the destination before creation. This candidate removes
the immediate duplicate setNotes call and lets editor.jump skip another redraw
when the destination is already open. Folded threads still redraw and open;
setNotes still refreshes changed notes and resets resolved-state folds.

All native Open, Compare, Patch, display_patch, comment_file, and file_contents
calls remain unchanged. The change must preserve external ref/checkout/index
freshness, partially staged destination selection, and jump fallback behavior.

The expected contribution is modest. The v3 Windows-to-WSL first WT jump took
307.3 ms: Open249.5 ms, patch12.8 ms, then42.3 ms to presentation. Removing two
duplicate widget redraws may reduce frontend work, but cannot eliminate that
backend first-use cost. Keep the canonical two-RAF gate and report first-use
and repeated results separately.

## Verification status

After the timing slot was released, all three focused regressions passed. All
six frontend test files passed, and Vite built successfully in 594 ms. Native
workflow and latency checks remain pending; this candidate is not promoted.

Reproduce from this directory:

```sh
node frontend/comment-jump-refresh.test.js
npm test
npm run build
```

The focused tests use the real editor controller and file-level comment widgets
with a minimal DOM stub. They verify folded-thread expansion, preservation of an
already-open widget across repeated jumps, updated feedback via setNotes, and
reopening a newly resolved thread. They do not verify populated CodeMirror pane
layout, viewport scrolling, or native focus.

For native verification, repeat line and file-level jumps for open, manually
collapsed, and resolved threads in unified and split layouts. Update/reply/resolve
the note externally, allow the normal refresh poll to apply it, then jump again.
Check that the current body/replies are visible, the thread opens, and the anchor
is scrolled into view. Include staged/unstaged/committed transitions and a jump
that falls back to current-file context. Compare with the unchanged v3 canonical
workload without transport delays or mocked native operations.
