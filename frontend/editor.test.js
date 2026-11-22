import { test } from "node:test";
import assert from "node:assert/strict";
import { diffRows, selectedLines, canSuggest } from "./editor.js";

const lines = [
  { kind: "@", text: "@@ -7,4 +7,3 @@", old: null, new: null, hunk: 1 },
  { kind: " ", text: "before", old: 7, new: 7, hunk: 1 },
  { kind: "-", text: "old a", old: 8, new: null, hunk: 1 },
  { kind: "-", text: "old b", old: 9, new: null, hunk: 1 },
  { kind: "+", text: "replacement", old: null, new: 8, hunk: 1 },
  { kind: " ", text: "after", old: 10, new: 9, hunk: 1 },
  { kind: "@", text: "@@ -40 +39 @@", old: null, new: null, hunk: 2 },
  { kind: "+", text: "distant", old: null, new: 39, hunk: 2 },
];

test("uneven split hunks preserve the original Git rows in both layouts", () => {
  assert.deepEqual(diffRows(lines, true), [
    [0, 0],
    [1, 1],
    [2, 4],
    [3, -1],
    [5, 5],
    [6, 6],
    [-1, 7],
  ]);
  assert.deepEqual(diffRows(lines, false).flat(), [0, 1, 2, 3, 4, 5, 6, 7]);
});

test("backward split selections exclude the opposite side and headers", () => {
  assert.deepEqual(selectedLines(lines, { side: "new", anchor: 5, head: 1 }), [
    lines[1],
    lines[4],
    lines[5],
  ]);
  assert.deepEqual(selectedLines(lines, { side: "old", anchor: 0, head: 5 }), [
    lines[1],
    lines[2],
    lines[3],
    lines[5],
  ]);
  assert.deepEqual(
    selectedLines(lines, { side: "both", anchor: 2, head: 4 }),
    lines.slice(2, 5),
  );
  assert.deepEqual(selectedLines(lines, null), []);
});

test("suggestions require consecutive new-side lines of one hunk in a regular file", () => {
  const file = { mode: "100644" },
    replacement = [lines[4], lines[5]];
  assert.equal(canSuggest(file, "both", replacement), true);
  assert.equal(canSuggest(file, "old", replacement), false);
  assert.equal(canSuggest({ mode: "120000" }, "new", replacement), false);
  assert.equal(canSuggest(file, "both", lines.slice(2, 5)), false);
  assert.equal(
    canSuggest(file, "new", [lines[5], { ...lines[7], new: 10 }]),
    false,
  );
});
