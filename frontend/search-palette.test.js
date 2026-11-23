import assert from "node:assert/strict";
import test from "node:test";
import { fileMatches, localPaletteHits, paletteRows } from "./search-palette.js";

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

test("palette groups occurrences only when the displayed line and source agree", () => {
  const line = {
    kind: "text", pair: ["refs/heads/base", "refs/heads/head"], base: "a",
    head: "b", path: "a/file", row: 8, side: "new", line: 7, text: "😀 010",
  };
  const hits = [
    { ...line, snippet_from: 3, snippet_to: 4 },
    { ...line, snippet_from: 5, snippet_to: 6 },
    { ...line, group: "Staged" },
    { ...line, side: "old" },
    { ...line, row: 9 },
    { ...line, text: "…010" },
    { ...line, pair: ["base", "layer"] },
    { ...line, revision: "prev" },
    { ...line, path: "b/file" },
  ];
  assert.deepEqual([...paletteRows(hits)].map((row) => row.indices),
    [[0, 1], [2], [3], [4], [5], [6], [7], [8]]);
  assert.deepEqual(hits.slice(0, 2).map((hit) => hit.text.slice(hit.snippet_from, hit.snippet_to)), ["0", "0"]);
});

test("identical previews group only when they show the same source window", () => {
  const hit = { kind: "text", path: "long.js", line: 1, text: "…needle needle" };
  const hits = [
    { ...hit, from: 103, snippet_from: 1, snippet_to: 7 },
    { ...hit, from: 110, snippet_from: 8, snippet_to: 14 },
    { ...hit, from: 203, snippet_from: 1, snippet_to: 7 },
  ];
  assert.deepEqual([...paletteRows(hits)].map(({ indices }) => indices), [[0, 1], [2]]);
});

test("local patch search spends its budget on code and enriches only retained hits", () => {
  let visited = 0, enriched = 0;
  class CountedText extends String {
    *matchAll(pattern) {
      for (const hit of super.matchAll(pattern)) {
        visited++;
        yield hit;
      }
    }
  }
  const patch = [
    { kind: "@", text: "hit ".repeat(500), old: null, new: null },
    { kind: "\\", text: "hit ".repeat(500), old: null, new: null },
    { kind: "+", text: new CountedText("😀 hit ".repeat(1000)), old: null, new: 8 },
    { kind: "+", new: 9, get text() { throw Error("Read past the hit budget"); } },
  ];
  const source = { get path() { enriched++; return "large.js"; } };
  const result = localPaletteHits("patch", "hit", null, patch, source);
  assert.equal(visited, 201);
  assert.equal(enriched, 200);
  assert.equal(result.hits.length, 200);
  assert.equal(result.truncated, true);
  assert.deepEqual(result.hits.map(({ row, line }) => [row, line]), Array(200).fill([2, 8]));
});

test("full-file palette search stops before reading later source rows", () => {
  const contents = ["hit ".repeat(500)];
  Object.defineProperty(contents, 1, {
    get() { throw Error("Read past the hit budget"); },
  });
  const { hits, truncated } = localPaletteHits("file", "hit", contents, [], {});
  assert.equal(hits.length, 200);
  assert.equal(truncated, true);
  assert.equal(hits.at(-1).from, 796);
  assert.equal(hits.at(-1).line, 1);
  assert.equal(hits.at(-1).localFile, true);
});

test("local palette search distinguishes exactly 200 matches from overflow", () => {
  for (const count of [200, 201]) {
    const text = "hit ".repeat(count);
    const patch = [{ kind: "-", text, old: 4, new: null }];
    for (const scope of ["patch", "file"]) {
      const { hits, truncated } = localPaletteHits(scope, "hit", ["", "", ""], patch, {});
      assert.equal(hits.length, 200);
      assert.equal(truncated, count > 200);
      assert.equal(hits[0].side, "old");
      assert.equal(hits[0].line, 4);
      assert.equal(hits[0].text.slice(hits[0].snippet_from, hits[0].snippet_to), "hit");
    }
  }
});

test("long local previews keep bounded Unicode snippets and original editor offsets", () => {
  const text = "😀".repeat(10000) + " needle needle" + "😀".repeat(10000);
  const patch = [{ kind: "+", text, old: null, new: 12 }];
  for (const scope of ["patch", "file"]) {
    const contents = Array(11).fill("").concat(text);
    const { hits, truncated } = localPaletteHits(scope, "needle", contents, patch, {});
    assert.equal(truncated, false);
    assert.deepEqual(hits.map(({ from, to }) => [from, to]), [[20001, 20007], [20008, 20014]]);
    for (const hit of hits) {
      assert.ok(hit.text.length <= 324);
      assert.ok(hit.text.startsWith("…") && hit.text.endsWith("…"));
      assert.ok(hit.text.isWellFormed());
      assert.equal(hit.text.slice(hit.snippet_from, hit.snippet_to), "needle");
      assert.equal(text.slice(hit.from, hit.to), "needle");
    }
    assert.deepEqual([...paletteRows(hits)].map(({ indices }) => indices), [[0], [1]]);
  }
});
