// Time the port's production JavaScript in Node, without creating an editor.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { diffRows } from "../../frontend/editor.js";
import { decodePatch } from "../../frontend/review-ui.js";

const { payload, warmups, iterations } = JSON.parse(readFileSync(0, "utf8"));

function measure(operation) {
  const samples = [];
  for (let i = 0; i < warmups + iterations; i++) {
    const start = performance.now();
    const result = operation();
    const elapsed = performance.now() - start;
    if (!result.length) throw new Error("Expected a nonempty fixture");
    if (i >= warmups) samples.push(elapsed);
  }
  return samples;
}

const lines = decodePatch(payload);
const timings = {
  js_decode: measure(() => decodePatch(payload)),
  js_unified_rows: measure(() => diffRows(lines, false)),
  js_split_rows: measure(() => diffRows(lines, true)),
};

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

console.log(JSON.stringify({
  node: process.version,
  v8: process.versions.v8,
  timings,
  hashes: {
    lines: digest(lines.map((l) => [l.kind, l.text, l.old, l.new, l.hunk])),
    unified_rows: digest(diffRows(lines, false)),
    split_rows: digest(diffRows(lines, true)),
  },
}));
