import test from "node:test";
import assert from "node:assert/strict";
import { decodePatch } from "./review-ui.js";

test("compact patches reconstruct the exact selectable Git rows across hunks", () => {
  const a = "@@ -1,2 +1,2 @@";
  const b = "@@ -22 +23,0 @@ fn example";
  const meta = "\\ No newline at end of file";
  const input = [
    a,
    "-one",
    "+",
    " @@ metadata-like content",
    b,
    "-café",
    meta,
    "",
  ].join("\n");
  const lines = decodePatch([
    input,
    [
      [1, 1],
      [22, 23],
    ],
  ]);
  assert.deepEqual(
    lines.map(({ kind, text, old, new: n, hunk }) => [
      kind,
      text,
      old,
      n,
      hunk,
    ]),
    [
      ["@", a, null, null, 1],
      ["-", "one", 1, null, 1],
      ["+", "", null, 1, 1],
      [" ", "@@ metadata-like content", 2, 2, 1],
      ["@", b, null, null, 2],
      ["-", "café", 22, null, 2],
      ["\\", meta, null, null, 2],
    ],
  );
  assert.deepEqual(decodePatch(["", []]), []);
});
