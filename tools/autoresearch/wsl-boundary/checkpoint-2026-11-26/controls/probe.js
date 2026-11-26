// Injected into an actual packaged Branchline webview by the canonical scorer.
// Native workspace calls and rendering remain part of every measured action.
window.boundaryProbe = (() => {
  const $ = (s) => document.querySelector(s);
  const frames = async () => {
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
  };
  const calls = [];
  let state;
  let chosenRoot;
  // Tauri defines invoke and __TAURI_INTERNALS__ as non-writable,
  // non-configurable properties. Observe its real custom-protocol transport
  // instead. The native response is consumed once, through the original body
  // reader; large patch data is neither cloned nor decoded a second time.
  const originalFetch = window.fetch;
  window.fetch = async function (input, options = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.protocol !== "ipc:" && url.hostname !== "ipc.localhost")
      return originalFetch.call(this, input, options);
    const command = decodeURIComponent(url.pathname.slice(1));
    let args;
    try { args = typeof options.body === "string" ? JSON.parse(options.body) : undefined; }
    catch { args = undefined; }
    if (command === "choose_repository" && chosenRoot !== undefined) {
      const root = chosenRoot;
      chosenRoot = undefined;
      // Only replace the human folder picker. Every workspace operation still
      // traverses the packaged app's native Tauri backend.
      return new Response(JSON.stringify(root), {headers: {
        "Content-Type": "application/json", "Tauri-Response": "ok",
      }});
    }
    const call = {command, op: args?.request?.op, start: performance.now()};
    calls.push(call);
    try {
      const response = await originalFetch.call(this, input, options);
      for (const method of ["json", "text", "arrayBuffer"]) {
        const read = response[method];
        response[method] = async function (...args) {
          try {
            const result = await read.apply(this, args);
            if (response.headers.get("Tauri-Response") !== "ok")
              call.error = "Native IPC returned an error";
            else if (command === "workspace" && result?.repo && "comparison" in result)
              state = result;
            call.end = performance.now();
            return result;
          } catch (error) {
            call.end = performance.now();
            call.error = String(error);
            throw error;
          }
        };
      }
      return response;
    } catch (error) {
      call.end = performance.now();
      call.error = String(error);
      throw error;
    }
  };
  if (window.fetch === originalFetch) throw Error("Could not observe native IPC transport");
  const rootKey = (path) => {
    if (!/^(?:[a-z]:[\\/]|[\\/]{2})/i.test(path)) return path;
    return path.replaceAll("\\", "/")
      .replace(/^\/\/\?\/UNC\//i, "//")
      .replace(/^\/\/\?\//, "")
      .replace(/\/+$/, "");
  };
  const visible = (node) => !!node?.getClientRects().length;
  function check(expected) {
    if (!state || state.error || state.mcp_warning || state.config_warning ||
        $("#app")?.hasAttribute("aria-busy")) return false;
    if (expected.root && rootKey(state.repo.root) !== rootKey(expected.root)) return false;
    if (expected.right && state.comparison?.right !== expected.right) return false;
    if (expected.left && state.comparison?.left !== expected.left) return false;
    if (expected.file_count !== undefined && state.comparison?.files.length !== expected.file_count)
      return false;
    if (expected.file && $("#filename")?.textContent !== expected.file) return false;
    const panes = [...document.querySelectorAll("#diff .cm-content")].filter(visible);
    if (!panes.length) return false;
    if (expected.marker && !panes.some((p) => p.textContent.includes(expected.marker)))
      return false;
    if (expected.note_body) {
      const note = [...document.querySelectorAll("#diff [data-note]")].find((node) =>
        visible(node) && node.textContent.includes(expected.note_body));
      if (!note) return false;
      const viewport = note.closest(".cm-scroller")?.getBoundingClientRect();
      const box = note.getBoundingClientRect();
      if (!viewport || box.bottom <= viewport.top || box.top >= viewport.bottom)
        return false;
    }
    return true;
  }
  let sample;
  function arm(selector, expected, event = "click", timeout = 180000) {
    const target = $(selector);
    if (!target || target.disabled || !visible(target))
      throw Error("Unavailable measured control: " + selector);
    sample = new Promise((resolve, reject) => {
      let expired = false;
      const deadline = setTimeout(() => {
        expired = true;
        target.removeEventListener(event, input, true);
        reject(Error("Incomplete interaction: " + selector));
      }, timeout);
      async function input() {
        if (expired) return;
        const start = performance.now();
        const firstCall = calls.length;
        try {
          while (!check(expected)) {
            await new Promise(requestAnimationFrame);
            if (expired) return;
          }
          await frames();
          if (expired) return;
          if (!check(expected)) throw Error("Interaction state changed before the frame boundary");
          const end = performance.now();
          const during = calls.slice(firstCall).filter((call) => call.start >= start);
          // The desktop's normal MCP note poll can overlap a long operation and
          // legitimately reject its old snapshot. Its resource cost remains in
          // elapsed_ms, but it is not an action-completion dependency.
          const polling = (call) => call.command === "workspace" && call.op === "refresh_notes";
          const native = during.filter((call) => !polling(call));
          const background = during.filter(polling);
          if (native.some((call) => call.error || call.end === undefined))
            throw Error("Native work failed or remained incomplete at the frame boundary");
          resolve({
            elapsed_ms: end - start,
            ipc: native.map((call) => ({
              command: call.command, op: call.op,
              start_ms: call.start - start, elapsed_ms: call.end - call.start,
            })),
            background_ipc: background.map((call) => ({
              command: call.command, op: call.op,
              start_ms: call.start - start,
              elapsed_ms: call.end === undefined ? null : call.end - call.start,
              pending: call.end === undefined, error: call.error ?? null,
            })),
            correct: true,
            file: $("#filename")?.textContent,
            left: state.comparison.left, right: state.comparison.right,
            file_count: state.comparison.files.length,
          });
        } catch (error) {
          reject(error);
        } finally {
          clearTimeout(deadline);
        }
      }
      target.addEventListener(event, input, {capture: true, once: true});
    });
    // Install a rejection handler before the host sends a separate input command.
    sample.catch(() => {});
    return true;
  }
  return {
    arm,
    chooseRoot: (root) => { chosenRoot = root; },
    finish: () => sample,
    check,
    settle: frames,
    state: () => state,
    calls: () => calls,
    async request(request) {
      if (!state) throw Error("Observe an opened workspace before fixture setup");
      return window.__TAURI_INTERNALS__.invoke("workspace", {request, snapshot: state.snapshot});
    },
  };
})();
