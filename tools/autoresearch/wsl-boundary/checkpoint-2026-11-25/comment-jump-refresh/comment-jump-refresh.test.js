import assert from "node:assert/strict";
import test from "node:test";
import { createDiff } from "./editor.js";

// File-level threads exercise the real editor controller and comment widgets
// without CodeMirror's browser-only layout. Native line jumps remain a GUI check.
class Node {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.events = {};
    this.attributes = new Map();
    this.style = { setProperty() {} };
    this.classList = { toggle() {}, add() {} };
    this.value = "";
  }
  set textContent(value) { this.value = value; this.children = []; }
  get textContent() { return this.value + this.children.map((child) => child.textContent).join(""); }
  addEventListener(type, listener) { this.events[type] = listener; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key); }
  append(...nodes) {
    for (const node of nodes) { node.parent = this; this.children.push(node); }
  }
  replaceChildren(...nodes) { this.value = ""; this.children = []; this.append(...nodes); }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((n) => n !== this);
  }
  contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
  closest() { return null; }
}

function find(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children) {
    const found = find(child, predicate);
    if (found) return found;
  }
}

function fixture({ folded = false } = {}) {
  const previousDocument = globalThis.document;
  const previousCancel = globalThis.cancelAnimationFrame;
  globalThis.document = {
    createElement: (tag) => new Node(tag),
    activeElement: new Node("body"),
  };
  globalThis.cancelAnimationFrame = () => {};
  const parent = new Node("parent");
  const note = { id: 7, body: "Original feedback", old: [], new: [], resolved: false };
  const folds = new Map(folded ? [[note.id, true]] : []);
  const diff = createDiff(parent, {
    file: { path: "binary", binary: true, added: null, removed: null },
    lines: [], notes: [note], folds,
  });
  return { diff, parent, note, folds,
    card: () => find(parent, (node) => node.dataset.note === note.id),
    cleanup() {
      diff.destroy();
      globalThis.document = previousDocument;
      globalThis.cancelAnimationFrame = previousCancel;
    },
  };
}

test("jump expands a folded thread and redraws its hidden feedback", () => {
  const f = fixture({ folded: true });
  try {
    const before = f.card();
    assert.ok(!before.textContent.includes(f.note.body));
    assert.equal(f.diff.jump(f.note.id), true);
    assert.notEqual(f.card(), before);
    assert.ok(f.card().textContent.includes(f.note.body));
    assert.equal(f.folds.get(f.note.id), undefined);
  } finally { f.cleanup(); }
});

test("jump retains an already-open thread's existing widget", () => {
  const f = fixture();
  try {
    const before = f.card();
    assert.ok(before.textContent.includes(f.note.body));
    assert.equal(f.diff.jump(f.note.id), true);
    assert.equal(f.diff.jump(f.note.id), true);
    assert.equal(f.card(), before);
    assert.equal(f.diff.jump(999), false);
  } finally { f.cleanup(); }
});

test("setNotes still refreshes feedback and jump reopens a newly resolved thread", () => {
  const f = fixture();
  try {
    const before = f.card();
    f.diff.setNotes([{ ...f.note, body: "Updated feedback" }]);
    assert.notEqual(f.card(), before);
    assert.ok(f.card().textContent.includes("Updated feedback"));
    const updated = f.card();
    f.diff.setNotes([{ ...f.note, body: "Resolved feedback", resolved: true }]);
    assert.notEqual(f.card(), updated);
    assert.ok(!f.card().textContent.includes("Resolved feedback"));
    assert.equal(f.diff.jump(f.note.id), true);
    assert.ok(f.card().textContent.includes("Resolved feedback"));
    assert.equal(f.folds.get(f.note.id), false);
  } finally { f.cleanup(); }
});
