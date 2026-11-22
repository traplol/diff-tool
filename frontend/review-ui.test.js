import test from "node:test";
import assert from "node:assert/strict";
import {
  WORKTREE,
  fileNotes,
  pairs,
  scopeNotes,
  commentRow,
  noteDestination,
  labelPath,
  setFold,
} from "./review-ui.js";

test("working tree outside the stack has a local scope until the user selects the whole repository", () => {
  const notes = [
    { left: "topic", right: WORKTREE },
    { left: "main", right: "next" },
    { left: "next", right: WORKTREE },
  ];
  const state = {
    stack: ["main", "next"],
    repo: { checkout: "topic" },
    pair: ["topic", WORKTREE],
    notes,
  };
  assert.deepEqual(scopeNotes(state, false), notes.slice(0, 1));
  assert.deepEqual(scopeNotes(state, true), notes);
  state.pair = ["main", "next"];
  assert.deepEqual(scopeNotes(state, false), notes.slice(1));
});

test("partially staged files show only comments with verified anchors in that group", () => {
  const note = { id: 9, old: [], new: [3, 3], body: "Saved text" };
  const dest = {
    left: "topic",
    right: WORKTREE,
    path: "src/cache.rs",
    group: "Staged",
    old: [],
    new: [6, 6],
  };
  const state = {
    pair: ["topic", WORKTREE],
    notes: [note],
    locations: { 9: [dest] },
  };
  assert.deepEqual(fileNotes(state, { ...dest, group: "Unstaged" }), []);
  assert.deepEqual(fileNotes(state, dest)[0].new, [6, 6]);
  assert.deepEqual(note.new, [3, 3]);
});

test("detached HEAD layer includes its precommit comments and avoids a duplicate two-ref comparison", () => {
  const notes = [
    { left: "HEAD@abc", right: WORKTREE },
    { left: "refs/heads/other", right: WORKTREE },
  ];
  const state = {
    stack: [":empty:", "HEAD"],
    repo: { checkout: "HEAD@abc" },
    pair: [":empty:", "HEAD"],
    notes,
  };
  assert.equal(pairs(state.stack, state.repo.checkout).length, 2);
  assert.deepEqual(scopeNotes(state, false), [notes[0]]);
});

test("tracked comments display the verified destination, with the saved body and application receipt", () => {
  const note = {
    id: 1,
    path: "old.rs",
    left: "refs/heads/topic",
    right: WORKTREE,
    group: "Unstaged",
    old: [],
    new: [2, 2],
    body: "Please fix\nthis line",
    suggestion: "",
    applied_location: {},
  };
  const staged = {
    left: note.left,
    right: WORKTREE,
    group: "Staged",
    path: "src/rename.rs",
    old: [],
    new: [5, 5],
  };
  const committed = {
    left: "refs/heads/main",
    right: note.left,
    group: "",
    path: "renamed.rs",
    old: [],
    new: [9, 10],
  };
  const state = {
    locations: { 1: [staged, committed] },
    pair: [committed.left, committed.right],
  };
  assert.deepEqual(commentRow(note, noteDestination(state, note)), {
    path: "renamed.rs",
    comparison: "main → topic",
    lines: "topic · new L9–10",
    summary: "Applied suggestion · Please fix this line",
  });
  state.pair = [note.left, WORKTREE];
  assert.equal(
    commentRow(note, noteDestination(state, note)).lines,
    "Staged · new L5",
  );
  state.locations[1] = [];
  assert.equal(commentRow(note, noteDestination(state, note)).path, "old.rs");
});

test("encoded Git paths display readable UTF-8 and retain invalid bytes", () => {
  assert.equal(
    labelPath("␛git:7372632f636166c3a9ff2e7273"),
    "src/café\\xff.rs",
  );
  assert.equal(labelPath("␛git:e2909b6769743a616263"), "␛git:abc");
  assert.equal(labelPath("new\nname"), "new\\nname");
});

test("fold overrides remember only choices that differ from saved resolution", () => {
  const folds = new Map(),
    n = { id: 7, resolved: true };
  setFold(folds, n, false);
  assert.equal(folds.get(7), false);
  setFold(folds, n, true);
  assert.equal(folds.has(7), false);
  n.resolved = false;
  setFold(folds, n, false);
  assert.equal(folds.has(7), false);
});
