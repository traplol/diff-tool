import test from "node:test";
import assert from "node:assert/strict";
import { contextGaps, displayContext, gapLength } from "./context.js";
import { decodePatch } from "./review-ui.js";
import {
  canExpandFile,
  canSuggest,
  diffRows,
  findDiffMatches,
} from "./editor.js";

test("expanding individual gaps preserves patch objects and both sides' line numbers", () => {
  const patch = decodePatch([
    "@@ -3 +3,2 @@\n-old\n+new\n+extra\n@@ -7,4 +8,4 @@\n-last\n+end\n i\n j\n k\n",
    [
      [3, 3],
      [7, 8],
    ],
  ]);
  const contents = {
    old: ["a", "b", "old", "c", "d", "e", "last", "i", "j", "k", "f"],
    new: ["a", "b", "new", "extra", "c", "d", "e", "end", "i", "j", "k", "f"],
  };
  const gaps = contextGaps(patch, { status: "M" });
  assert.deepEqual(
    gaps.map((g) => [g.at, g.old, g.new, gapLength(g, contents.new)]),
    [
      [0, 1, 1, 2],
      [4, 4, 5, 3],
      [10, 11, 12, 1],
    ],
  );
  assert.equal(displayContext(patch, gaps, new Set()).lines, patch);
  const partial = displayContext(patch, gaps, new Set([4]), contents.new);
  assert.deepEqual(
    partial.lines.slice(4, 7).map((l) => [l.old, l.new, l.text]),
    [
      [4, 5, "c"],
      [5, 6, "d"],
      [6, 7, "e"],
    ],
  );
  assert.equal(partial.lines[8], patch[5]);
  assert.deepEqual(
    partial.controls.map((c) => [c.before, c.open]),
    [
      [0, false],
      [4, true],
      [13, false],
    ],
  );
  const full = displayContext(
    patch,
    gaps,
    new Set(gaps.map((g) => g.at)),
    contents.new,
  );
  for (const side of ["old", "new"]) {
    assert.deepEqual(
      full.lines.filter((l) => l[side] != null).map((l) => l.text),
      contents[side],
    );
  }
  const split = diffRows(full.lines, true);
  assert.deepEqual(split[0], [0, 0]);
  assert.deepEqual(split.at(-1), [
    full.lines.length - 1,
    full.lines.length - 1,
  ]);
  assert.equal(findDiffMatches(full.lines, "f").matches.length, 0);
  assert.equal(canSuggest({ mode: "100644" }, "new", [full.lines[0]]), false);
});

test("zero-length ranges, empty files and pure renames expose the right context", () => {
  const patch = decodePatch(["@@ -2,0 +3 @@\n+extra\n", [[2, 3]]]);
  const gaps = contextGaps(patch, { status: "M" });
  assert.deepEqual(gaps[0], { at: 0, old: 1, new: 1, count: 2 });
  assert.equal(gaps.length, 1); // No trailing context after a change at EOF.
  const rename = {
    status: "R",
    old_mode: "100644",
    mode: "100644",
    added: 0,
    removed: 0,
  };
  assert.equal(canExpandFile(rename), true);
  const renamed = contextGaps([], rename);
  assert.deepEqual(
    displayContext([], renamed, new Set([0]), ["same"]).lines[0],
    { kind: " ", old: 1, new: 1, text: "same", contextOnly: true },
  );
  assert.deepEqual(displayContext([], renamed, new Set(), []).controls, []);
  assert.equal(canExpandFile({ ...rename, added: null, removed: null }), false);
  assert.equal(canExpandFile({ ...rename, mode: "160000" }), false);
  assert.deepEqual(
    contextGaps(decodePatch(["@@ -0,0 +1 @@\n+new\n", [[0, 1]]]), {
      status: "A",
    }),
    [],
  );
});
