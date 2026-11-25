// Host-only wrapper semantics. This does not validate native GUI behavior or timing.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";

const source = readFileSync(new URL("./inject.js", import.meta.url), "utf8");
const checks = [];
function fixture(inheritedFrame = false) {
  let clock = 0, nativeId = 100;
  const queued = new Map(), listeners = new Map(), seen = [];
  const originalError = Error("original error");
  class View {
    constructor() {
      this.contentDOM = {};
      this.docView = { tile: { view: this } };
      this.contentDOM.cmTile = this.docView.tile;
      this.docView.tile.root = this.docView.tile;
    }
    measure(...args) {
      seen.push({ receiver: this, args });
      if (args[0] === "throw") throw originalError;
      return this;
    }
    update(value) {
      if (value === "nested") return this.lineBlockAtHeight(12);
      return value;
    }
    lineBlockAtHeight(height) { this.measure(false); return { height }; }
  }
  const view = new View();
  const target = {
    addEventListener(event, listener, options) {
      assert.equal(options.capture, true);
      assert.equal(options.once, true);
      listeners.set(event, listener);
    },
    removeEventListener(event, listener, capture) {
      assert.equal(capture, true);
      if (listeners.get(event) === listener) listeners.delete(event);
    },
  };
  function frame(callback, ...args) {
    if (typeof callback !== "function") throw originalError;
    const id = ++nativeId;
    queued.set(id, { callback, requestThis: this, args });
    return id;
  }
  function cancel(id) { queued.delete(id); }
  const window = Object.create(inheritedFrame ? { requestAnimationFrame: frame } : null);
  if (!inheritedFrame) Object.defineProperty(window, "requestAnimationFrame", {
    value: frame, configurable: true, enumerable: false, writable: false,
  });
  window.cancelAnimationFrame = cancel;
  const document = {
    querySelectorAll: () => [view.contentDOM],
    querySelector: () => target,
  };
  const context = vm.createContext({ window, document, performance: { now: () => ++clock } });
  const descriptors = ["measure", "update", "lineBlockAtHeight"].map((key) =>
    [View.prototype, key, Object.getOwnPropertyDescriptor(View.prototype, key)]);
  descriptors.push([window, "requestAnimationFrame", Object.getOwnPropertyDescriptor(window, "requestAnimationFrame")]);
  const install = () => vm.runInContext(source, context);
  const input = (event = "click") => listeners.get(event)({ type: event, timeStamp: ++clock });
  const fire = (id, receiver, ...args) => {
    const request = queued.get(id);
    assert.ok(request, "native request remains queued");
    queued.delete(id);
    return Reflect.apply(request.callback, receiver, args);
  };
  return { window, View, view, target, queued, listeners, seen, originalError,
    descriptors, install, input, fire, cancel, frame, document };
}

for (const inheritedFrame of [false, true]) {
  const f = fixture(inheritedFrame);
  assert.equal(f.install().diagnostic_only, true);
  const api = f.window.branchlineUiPhaseProbe;
  api.arm("#pair", "change", "branch_final");
  f.input("change");
  assert.equal(f.listeners.size, 0);
  const newer = new f.View();
  const token = {};
  assert.equal(newer.update(token), token);
  assert.deepEqual(newer.update("nested"), { height: 12 });
  assert.equal(newer.measure(1, token), newer);
  assert.deepEqual(f.seen.at(-1), { receiver: newer, args: [1, token] });
  assert.throws(() => newer.measure("throw"), (error) => error === f.originalError);
  assert.throws(() => f.window.requestAnimationFrame(null), (error) => error === f.originalError);
  const requestThis = {}, callbackThis = {}, callbackReturn = {};
  const id = f.window.requestAnimationFrame.call(requestThis, function (...args) {
    assert.equal(this, callbackThis);
    assert.deepEqual(args, [123.5, token]);
    newer.update("from frame");
    return callbackReturn;
  }, "native extra argument");
  assert.equal(id, 101);
  assert.equal(f.queued.get(id).requestThis, requestThis);
  assert.deepEqual(f.queued.get(id).args, ["native extra argument"]);
  assert.equal(f.fire(id, callbackThis, 123.5, token), callbackReturn);
  const throwing = f.window.requestAnimationFrame(() => { throw f.originalError; });
  assert.throws(() => f.fire(throwing, callbackThis, 140), (error) => error === f.originalError);
  const cancelled = f.window.requestAnimationFrame(() => assert.fail("cancelled callback ran"));
  assert.equal(f.window.cancelAnimationFrame, f.cancel);
  f.window.cancelAnimationFrame(cancelled);
  assert.equal(f.queued.has(cancelled), false);
  const trace = api.stop();
  const span = trace.events.find((event) => event.kind === "cm.lineBlockAtHeight");
  assert.ok(trace.events.some((event) => event.kind === "cm.measure" && event.parent === span.id));
  assert.ok(trace.events.some((event) => event.kind === "raf.callback" && event.callback_timestamp_ms === 123.5));
  assert.ok(trace.events.some((event) => event.kind === "raf.callback" && event.threw));
  assert.ok(trace.events.every((event) => event.duration_ms >= 0));
  const count = api.snapshot().events.length;
  newer.measure();
  assert.equal(api.snapshot().events.length, count);
  assert.equal(f.queued.size, 0, "probe schedules no additional frames");
  api.arm("#pair"); f.input();
  for (let i = 0; i < 5000; i++) newer.update(i);
  const bounded = api.stop();
  assert.equal(bounded.events.length, 4096);
  assert.ok(bounded.dropped_events > 0);
  api.arm("#pair"); f.input();
  const pending = f.window.requestAnimationFrame(function (timestamp) {
    assert.equal(this, callbackThis);
    return timestamp;
  });
  assert.equal(api.restore().restored, true);
  assert.equal(f.fire(pending, callbackThis, 999), 999);
  for (const [owner, key, original] of f.descriptors)
    assert.deepEqual(Object.getOwnPropertyDescriptor(owner, key), original);
  assert.equal("branchlineUiPhaseProbe" in f.window, false);
  checks.push(`native IDs, cancellation, this, arguments, returns, throws, nesting, new views, memory cap and descriptor restoration (${inheritedFrame ? "inherited" : "own"} rAF)`);
}
const absent = fixture();
absent.document.querySelectorAll = () => [];
assert.throws(absent.install, /No real CodeMirror EditorView/);
assert.equal(absent.window.requestAnimationFrame, absent.frame);
checks.push("missing real view fails before hooks are installed");
const denied = fixture();
Object.defineProperty(denied.View.prototype, "update", { configurable: false, writable: false });
assert.throws(denied.install, /Cannot replace update/);
assert.equal(denied.window.requestAnimationFrame, denied.frame);
assert.deepEqual(Object.getOwnPropertyDescriptor(denied.View.prototype, "measure"), denied.descriptors[0][2]);
checks.push("nonreplaceable descriptor fails before any hook is installed");
console.log(JSON.stringify({ diagnostic_only: true, host_mock_checks: "passed", checks,
  source_sha256: createHash("sha256").update(source).digest("hex"),
  native_gui_validation: "not run", timing_validation: "not run" }, null, 2));
