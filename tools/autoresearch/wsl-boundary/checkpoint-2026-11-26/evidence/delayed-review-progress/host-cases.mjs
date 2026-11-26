import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const app = fs.readFileSync(path.join(here, 'source/frontend/app.js'), 'utf8');
const changeWorkspace = app.slice(app.indexOf('async function changeWorkspace('), app.indexOf('async function choose()'));
function harness() {
  const statuses = [], requests = [], timers = new Map(), nodes = new Map();
  let now = 0, timerId = 0, resolve, reject;
  const response = new Promise((yes, no) => { resolve = yes; reject = no; });
  const entry = { path: 'a.rs', group: '' };
  const workspace = (snapshot) => ({ snapshot, repo: { root: '/repo', checkout: 'HEAD', refs: {} },
    pair: ['base', 'head'], stack: ['base', 'head'], notes: [], viewed: [], comparison: { files: [entry] } });
  class Node {
    constructor() { this.options = [{}]; this.attrs = new Map(); this.value = ''; }
    setAttribute(key, value) { this.attrs.set(key, value); }
    removeAttribute(key) { this.attrs.delete(key); }
    replaceChildren() {} append() {} querySelectorAll() { return []; }
  }
  const $ = (id) => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const context = vm.createContext({
    $, document: {}, Option: class {}, initial: workspace(1), WORKTREE: ':worktree:',
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, due: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    status: (text, error) => statuses.push({ text, error: !!error }),
    request: (op, args) => { requests.push({ op, args }); return response; },
    currentFile: () => entry, leaveFile() {}, palette: { reset() {} }, setWidth() {}, setMode() {},
    basename: () => 'repo', labelPath: (value) => value, refName: (value) => value,
    pairs: () => [['Full stack', ['base', 'head']]], choiceIndex: () => 0, localScope: () => false,
    el: () => new Node(), icon: () => new Node(), button: () => new Node(), handle: (fn) => fn,
    renderComparisonStats() {}, activate() {}, visibleFiles: () => [0], files: () => [entry],
    navigate: async () => {},
  });
  vm.runInContext(`
    let state = initial, loading = false, editLock = false, selectedNote, tab = 'Changes',
      openFilter = 'Open', fileIndex = 0, commits;
    const folds = new Map(), positions = new Map(), closedFolders = new Set(), closedSearchFolders = new Set();
    let preferenceWrite = Promise.resolve();
    ${changeWorkspace}
  `, context);
  return { $, statuses, requests, timers, resolve: () => resolve(workspace(2)), reject,
    run: (text) => vm.runInContext(text, context),
    advance(ms) { now += ms; for (const [id, timer] of [...timers]) if (timer.due <= now) { timers.delete(id); timer.fn(); } },
    change: () => vm.runInContext('changeWorkspace("compare", { pair: ["base", "head"] })', context) };
}
const progress = (h) => h.statuses.filter((item) => item.text === 'Reading Git changes…');
const passed = [];
async function check(name, fn) { await fn(); passed.push(name); console.log(`PASS ${name}`); }
await check('fast success starts native work immediately and cancels progress before 200 ms', async () => {
  const h = harness(), done = h.change();
  assert.equal(h.requests.length, 1);
  assert.equal(h.run('loading'), true);
  assert.equal(h.$('app').attrs.get('aria-busy'), 'true');
  h.advance(199); assert.equal(progress(h).length, 0);
  h.resolve(); await done;
  assert.equal(h.run('state.snapshot'), 2);
  assert.equal(h.run('loading'), false);
  assert.equal(h.$('app').attrs.has('aria-busy'), false);
  assert.equal(h.timers.size, 0);
  h.advance(1000);
  assert.equal(progress(h).length, 0);
  assert.equal(h.statuses.at(-1).text, 'Comparison up to date');
});
await check('pending work shows progress at 200 ms without delaying native work or completion', async () => {
  const h = harness(), done = h.change();
  assert.equal(h.requests.length, 1);
  h.advance(199); assert.equal(progress(h).length, 0);
  h.advance(1); assert.equal(progress(h).length, 1);
  assert.equal(h.run('state.snapshot'), 1);
  assert.equal(h.run('loading'), true);
  assert.equal(h.requests.length, 1);
  h.resolve(); await done;
  assert.equal(h.statuses.at(-1).text, 'Comparison up to date');
  assert.equal(h.run('state.snapshot'), 2);
  assert.equal(h.timers.size, 0);
  h.advance(1000); assert.equal(progress(h).length, 1);
});
await check('native rejection preserves the error and clears progress and busy state', async () => {
  const h = harness(), error = new Error('native comparison failed'), done = h.change();
  h.advance(150); h.reject(error);
  await assert.rejects(done, (value) => value === error);
  assert.equal(h.run('state.snapshot'), 1);
  assert.equal(h.run('loading'), false);
  assert.equal(h.$('app').attrs.has('aria-busy'), false);
  assert.equal(h.timers.size, 0);
  h.advance(1000);
  assert.equal(progress(h).length, 0);
  assert.equal(h.requests.length, 1);
});
console.log(JSON.stringify({ passed: passed.length, cases: passed }));
