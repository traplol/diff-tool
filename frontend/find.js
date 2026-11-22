import { $, el, button } from "./dialogs.js";
import { findDiffMatches } from "./editor.js";
import { labelPath, refName } from "./review-ui.js";

// Use diff order so Next passes removed lines just before their replacements.
export function fileMatches(contents, patch, query) {
  const rows = [];
  let next = 1,
    delta = 0;
  function addNewBefore(end) {
    while (next < end) {
      rows.push({ text: contents[next - 1], side: "new", line: next });
      next++;
    }
  }
  for (const row of patch) {
    if (row.kind === "+") delta++;
    if (row.kind === "-") {
      addNewBefore(row.old + delta);
      rows.push({ text: row.text, side: "old", line: row.old });
      delta--;
    }
  }
  addNewBefore(contents.length + 1);
  return findDiffMatches(rows, query).matches.map(({ line, from, to }) => ({
    line: rows[line].line,
    side: rows[line].side,
    from,
    to,
  }));
}

export function setupFind({ activeEditor, patchLines, searchReview, openHit }) {
  const bar = $("find-bar"),
    input = $("diff-search"),
    scope = $("find-scope"),
    results = $("find-results"),
    prev = $("find-prev"),
    next = $("find-next");
  let hits = [],
    selected = -1,
    truncated = false,
    generation = 0,
    timer,
    running;
  let navigation = Promise.resolve();
  const local = () => scope.value === "patch" || scope.value === "file";

  function status(message, canStep = false) {
    $("find-status").textContent = message;
    prev.disabled = next.disabled = !canStep;
  }
  function count() {
    const total = hits.length + (truncated ? "+" : "");
    status(
      selected === -1 ? `${total} matches` : `${selected + 1} of ${total}`,
      !!hits.length,
    );
  }
  function clear() {
    ++generation;
    clearTimeout(timer);
    if (running) {
      searchReview(running, "").catch(() => {});
      running = null;
    }
    hits = [];
    selected = -1;
    truncated = false;
    results.replaceChildren();
    results.hidden = true;
    activeEditor()?.find("");
  }
  async function show(i) {
    if (!hits[i]) return;
    const token = generation;
    const valid = () => generation === token && selected === i;
    results.children[selected]?.removeAttribute("aria-current");
    selected = i;
    count();
    const item = results.children[i];
    if (item) {
      item.setAttribute("aria-current", "true");
      item.scrollIntoView({ block: "nearest" });
    }
    const hit = hits[i];
    try {
      if (scope.value === "file") {
        await activeEditor()?.revealLine(hit.side, hit.line, hit.from, hit.to);
      } else {
        // A stack jump can still be loading when the next result is selected.
        navigation = navigation
          .catch(() => {})
          .then(() => valid() && openHit(hit, scope.value, valid));
        await navigation;
      }
    } catch (err) {
      if (valid()) status(String(err), !!hits.length);
    }
  }
  function patchFind(step = 0) {
    const result = activeEditor()?.find(input.value, step);
    status(
      !input.value
        ? ""
        : result?.total
          ? `${result.current} of ${result.total}`
          : "No matches",
      !!result?.total,
    );
  }
  function refresh() {
    if (bar.hidden) return;
    const query = input.value,
      kind = scope.value;
    clear();
    if (kind === "patch") return patchFind();
    if (!query) return status("");
    const token = generation;
    status("Searching…");
    async function run() {
      try {
        let found;
        if (kind === "file") {
          const editor = activeEditor();
          if (!editor) return status("Select a text file");
          const contents = await editor.contents();
          if (token !== generation) return;
          found = { hits: fileMatches(contents, patchLines(), query) };
        } else {
          running = kind;
          found = await searchReview(kind, query);
        }
        if (token !== generation) return;
        hits = found.hits;
        truncated = !!found.truncated;
        if (!hits.length) return status("No matches");
        if (kind === "file") return show(0);
        const buttons = hits.map((hit, i) => {
          const b = button("", () => show(i));
          const source = kind === "stack" ? `${refName(hit.pair[1])} · ` : "";
          b.append(
            el(
              "strong",
              `${source}${hit.group ? hit.group + " · " : ""}${labelPath(hit.path)} · ${hit.side} L${hit.line}`,
            ),
            el("code", hit.text),
          );
          return b;
        });
        results.replaceChildren(...buttons);
        results.hidden = false;
        count();
      } catch (err) {
        if (token === generation) status(String(err));
      } finally {
        if (token === generation) running = null;
      }
    }
    timer = setTimeout(run, kind === "file" ? 0 : 180);
  }
  function move(step) {
    if (scope.value === "patch") return patchFind(step);
    if (!hits.length) return;
    const i =
      selected < 0
        ? step < 0
          ? hits.length - 1
          : 0
        : (selected + step + hits.length) % hits.length;
    return show(i);
  }
  function open(kind) {
    if (kind) scope.value = kind;
    const wasHidden = bar.hidden;
    bar.hidden = false;
    $("find").setAttribute("aria-expanded", "true");
    input.focus();
    input.select();
    if (wasHidden || kind) refresh();
  }
  function close() {
    bar.hidden = true;
    $("find").setAttribute("aria-expanded", "false");
    clear();
    status("");
  }
  $("find").onclick = () => open();
  input.oninput = refresh;
  scope.onchange = () => {
    refresh();
    input.focus();
    input.select();
  };
  input.onkeydown = (e) => {
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      move(e.shiftKey ? -1 : 1);
    }
  };
  prev.onclick = () => {
    input.focus();
    move(-1);
  };
  next.onclick = () => {
    input.focus();
    move(1);
  };
  $("find-close").onclick = () => {
    close();
    activeEditor()?.focus();
  };
  $("changes").addEventListener(
    "keydown",
    (e) => {
      if (
        e.key === "Escape" &&
        !bar.hidden &&
        e.target.closest("#find-bar, #find-results, #diff")
      ) {
        e.preventDefault();
        e.stopPropagation();
        close();
        activeEditor()?.focus();
      }
    },
    true,
  );
  return {
    open,
    close,
    refresh,
    fileChanged() {
      if (local()) refresh();
    },
  };
}
