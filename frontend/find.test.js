import assert from "node:assert/strict";
import test from "node:test";
import { fileMatches } from "./find.js";

test("full-file search visits hidden, removed and added occurrences in diff order", () => {
  const contents = ["🛠 Hit", "new hit", "middle", "inserted", "last HiT"];
  const patch = [
    { kind: "-", old: 2, text: "hit hit" },
    { kind: "+", new: 2, text: "new hit" },
    { kind: " ", old: 3, new: 3, text: "middle" },
    { kind: "+", new: 4, text: "inserted" },
    { kind: "-", old: 4, text: "deleted HIT" },
  ];
  assert.deepEqual(fileMatches(contents, patch, "hit"), [
    { side: "new", line: 1, from: 3, to: 6 },
    { side: "old", line: 2, from: 0, to: 3 },
    { side: "old", line: 2, from: 4, to: 7 },
    { side: "new", line: 2, from: 4, to: 7 },
    { side: "old", line: 4, from: 8, to: 11 },
    { side: "new", line: 5, from: 5, to: 8 },
  ]);
  assert.equal(fileMatches(contents, patch, "middle").length, 1);
});
