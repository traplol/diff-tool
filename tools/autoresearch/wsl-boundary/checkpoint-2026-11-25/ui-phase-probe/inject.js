// Diagnostic only. Inject after a real text diff is mounted in the packaged app.
(() => {
  "use strict";
  const name = "branchlineUiPhaseProbe";
  if (name in window) throw Error(`${name} already exists; restore it first`);
  const contents = [...document.querySelectorAll("#diff .cm-content")];
  const views = contents.map((content) => {
    const tile = content.cmTile?.root;
    const view = tile?.view;
    return view?.contentDOM === content && view.docView?.tile === tile ? view : null;
  }).filter(Boolean);
  if (!views.length) throw Error("No real CodeMirror EditorView found through contentDOM.cmTile.root.view");
  const prototype = Object.getPrototypeOf(views[0]);
  if (views.some((view) => Object.getPrototypeOf(view) !== prototype))
    throw Error("Mounted CodeMirror views have different prototypes");

  const capacity = 4096;
  const events = [];
  const viewIds = new WeakMap();
  const patches = [];
  let nextView = 0, nextCall = 0, currentCall = null;
  let active = false, installed = true, action = 0, armed;
  let label = "", actionStart = null, stopped = null, dropped = 0;
  const now = () => performance.now();
  const short = (text) => String(text).slice(0, 160);
  function add(event) {
    if (events.length < capacity) events.push(event);
    else dropped++;
  }
  function viewId(view) {
    if ((typeof view !== "object" && typeof view !== "function") || view === null) return null;
    if (!viewIds.has(view)) viewIds.set(view, ++nextView);
    return viewIds.get(view);
  }
  function timed(kind, receiver, original, args, metadata) {
    const id = ++nextCall, parent = currentCall, session = action, start = now();
    currentCall = id;
    let threw = true;
    try {
      const result = Reflect.apply(original, receiver, args);
      threw = false;
      return result;
    } finally {
      const end = now();
      currentCall = parent;
      if (installed && active && session === action)
        add({ kind, id, parent, start_ms: start, duration_ms: end - start, threw, ...metadata });
    }
  }
  function prepare(owner, key, replacement, requireOwnFunction = false) {
    const descriptor = Object.getOwnPropertyDescriptor(owner, key);
    if (requireOwnFunction && typeof descriptor?.value !== "function")
      throw Error(`EditorView.${key} has no own function descriptor`);
    if ((!descriptor && !Object.isExtensible(owner)) ||
        (descriptor && !descriptor.configurable && !("value" in descriptor && descriptor.writable)))
      throw Error(`Cannot replace ${key} while preserving its descriptor`);
    const next = descriptor && "value" in descriptor
      ? { ...descriptor, value: replacement }
      : { configurable: true, enumerable: descriptor?.enumerable ?? true, writable: true, value: replacement };
    patches.push({ owner, key, descriptor, next });
  }
  for (const method of ["measure", "update", "lineBlockAtHeight"]) {
    const original = Object.getOwnPropertyDescriptor(prototype, method)?.value;
    prepare(prototype, method, function (...args) {
      if (!installed || !active) return Reflect.apply(original, this, args);
      const metadata = { view: viewId(this) };
      if (method === "lineBlockAtHeight" && typeof args[0] === "number") metadata.height = args[0];
      return timed(`cm.${method}`, this, original, args, metadata);
    }, true);
  }
  const originalFrame = window.requestAnimationFrame;
  if (typeof originalFrame !== "function") throw Error("requestAnimationFrame is unavailable");
  prepare(window, "requestAnimationFrame", function (...args) {
    const callback = args[0];
    if (!installed || !active || typeof callback !== "function")
      return Reflect.apply(originalFrame, this, args);
    const requested = now(), request = ++nextCall, parent = currentCall, session = action;
    let nativeId = null, threw = true;
    const wrapped = function (...callbackArgs) {
      if (!installed || !active) return Reflect.apply(callback, this, callbackArgs);
      return timed("raf.callback", this, callback, callbackArgs, {
        request, native_id: nativeId, requested_ms: requested,
        request_action: session, request_parent: parent,
        callback_timestamp_ms: typeof callbackArgs[0] === "number" ? callbackArgs[0] : null,
        lag_ms: now() - requested,
      });
    };
    try {
      nativeId = Reflect.apply(originalFrame, this, [wrapped, ...args.slice(1)]);
      threw = false;
      return nativeId;
    } finally {
      if (installed && active && session === action)
        add({ kind: "raf.request", id: request, parent, start_ms: requested,
          duration_ms: now() - requested, native_id: nativeId, threw });
    }
  });
  function disarm() {
    if (armed) armed.target.removeEventListener(armed.event, armed.listener, true);
    armed = undefined;
  }
  const unmeasured = [
    "EditorView constructor, app closures, patch decoding and widget construction outside the hooked methods",
    "Native compositor, rasterization, GPU, presentation and the reason for a delayed frame callback",
    "The purpose of opaque frame callbacks, including scorer readiness versus its required completion frames",
    "Callbacks requested before installation or while the probe was inactive",
    "Native IPC; use the unchanged boundaryProbe records",
  ];
  function snapshot() {
    return { diagnostic_only: true, clock: "performance.now", label, action,
      action_start_ms: actionStart, stopped_ms: stopped, active,
      capacity, dropped_events: dropped, events: events.slice(), unmeasured: unmeasured.slice() };
  }
  const api = Object.freeze({
    arm(selector, event = "click", actionLabel = selector) {
      if (!installed) throw Error("Probe has been restored");
      if (active || armed) throw Error("Stop the current probe action before arming another");
      if (typeof event !== "string" || !event || event.length > 80) throw Error("Invalid input event");
      const target = document.querySelector(selector);
      if (!target) throw Error(`Missing input target: ${short(selector)}`);
      const listener = function (input) {
        actionStart = now();
        disarm();
        events.length = 0;
        dropped = 0;
        stopped = null;
        label = short(actionLabel);
        action++;
        active = true;
        add({ kind: "input", id: ++nextCall, parent: currentCall, start_ms: actionStart,
          duration_ms: 0, event: short(input.type), event_timestamp_ms: input.timeStamp });
      };
      armed = { target, event, listener };
      target.addEventListener(event, listener, { capture: true, once: true });
      return { armed: true, selector: short(selector), event };
    },
    snapshot,
    stop() {
      disarm();
      if (active) stopped = now();
      active = false;
      return snapshot();
    },
    restore() {
      const result = api.stop();
      if (!installed) return { ...result, restored: true };
      installed = false;
      const errors = [];
      for (const patch of [...patches].reverse()) {
        try {
          if (patch.descriptor) Object.defineProperty(patch.owner, patch.key, patch.descriptor);
          else if (!Reflect.deleteProperty(patch.owner, patch.key)) throw Error(`Cannot remove ${patch.key}`);
        } catch (error) { errors.push(error); }
      }
      if (errors.length) throw new AggregateError(errors, "Could not restore every diagnostic hook");
      return { ...result, restored: true };
    },
    info: () => ({ diagnostic_only: true, capacity, mounted_views: views.length,
      methods: ["measure", "update", "lineBlockAtHeight"], unmeasured: unmeasured.slice() }),
  });
  prepare(window, name, api);
  const applied = [];
  try {
    for (const patch of patches) {
      Object.defineProperty(patch.owner, patch.key, patch.next);
      applied.push(patch);
    }
  } catch (error) {
    installed = false;
    for (const patch of applied.reverse()) {
      if (patch.descriptor) Object.defineProperty(patch.owner, patch.key, patch.descriptor);
      else Reflect.deleteProperty(patch.owner, patch.key);
    }
    throw error;
  }
  return api.info();
})();
