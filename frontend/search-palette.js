import { $, el } from "./dialogs.js";
import { findDiffMatches } from "./editor.js";
import { labelPath, refName, pairs, scopeNotes, localScope } from "./review-ui.js";

// Use diff order so Next passes removed lines just before their replacements.
export function fileMatches(contents, patch, query, limit = Infinity) {
  const rows = [];
  let next = 1,
    delta = 0;
  function* addNewBefore(end) {
    while (next < end) {
      const row = { text: contents[next - 1], side: "new", line: next };
      rows.push(row);
      next++;
      yield row;
    }
  }
  function* orderedRows() {
    for (const row of patch) {
      if (row.kind === "+") delta++;
      if (row.kind === "-") {
        yield* addNewBefore(row.old + delta);
        const removed = { text: row.text, side: "old", line: row.old };
        rows.push(removed);
        delta--;
        yield removed;
      }
    }
    yield* addNewBefore(contents.length + 1);
  }
  return findDiffMatches(orderedRows(), query, limit).matches.map(({ line, from, to }) => ({
    line: rows[line].line,
    side: rows[line].side,
    from,
    to,
  }));
}

function localSnippet(text, from, to) {
  let start = text.length > 320 ? Math.max(0, from - 48) : 0;
  let end = Math.max(to, Math.min(text.length, start + 320));
  // Editor offsets use UTF-16. Keep both halves of emoji at crop boundaries.
  if (start > 0 && /[\uDC00-\uDFFF]/.test(text[start])) start--;
  if (end < text.length && /[\uDC00-\uDFFF]/.test(text[end])) end++;
  const prefix = start > 0 ? "…" : "";
  return {
    text: prefix + text.slice(start, end) + (end < text.length ? "…" : ""),
    snippet_from: prefix.length + from - start,
    snippet_to: prefix.length + to - start,
  };
}

export function localPaletteHits(scope, query, contents, patch, source) {
  const matches = scope === "file"
    ? fileMatches(contents, patch, query, 201)
    : findDiffMatches(patch, query, 201).matches;
  const oldText = scope === "file"
    ? new Map(patch.filter((row) => row.kind === "-").map((row) => [row.old, row.text]))
    : null;
  const hits = matches.slice(0, 200).map((match) => {
    let hit, text;
    if (scope === "file") {
      hit = { ...match, localFile: true };
      text = hit.side === "new" ? contents[hit.line - 1] : oldText.get(hit.line);
    } else {
      const { kind, old, new: next } = patch[match.line];
      text = patch[match.line].text;
      hit = { ...match, row: match.line, line: next ?? old, side: kind === "-" ? "old" : "new" };
    }
    return { ...source, ...hit, kind: "text", ...localSnippet(text, hit.from, hit.to) };
  });
  return { hits, truncated: matches.length > 200 };
}

export function metadataHits(query, state) {
  const hits = [];
  const match = (text) => findDiffMatches([{ text }], query, 1).matches[0];
  for (const note of scopeNotes(state, false)) {
    const text = (note.body ?? "").replace(/\r?\n/g, " ");
    const found = match(text);
    if (!found) continue;
    if (hits.length === 100) return { hits, truncated: true };
    hits.push({
      kind: "comment", id: note.id, path: note.path, pair: [note.left, note.right],
      ...localSnippet(text, found.from, found.to),
    });
  }
  if (!localScope(state)) {
    const choices = pairs(state.stack, state.repo.checkout);
    for (const [i, ref] of state.stack.entries()) {
      const text = refName(ref);
      const found = match(text);
      if (!found) continue;
      const pair = choices[i === 0 || state.stack.length === 2 ? 0 : i]?.[1];
      if (!pair) continue;
      if (hits.length === 100) return { hits, truncated: true };
      hits.push({ kind: "branch", pair, ...localSnippet(text, found.from, found.to) });
    }
  }
  return { hits, truncated: false };
}

const groups = { path: "Files", text: "Diff and source", comment: "Comments", commit: "Commits", branch: "Branches" };

export function paletteRows(hits) {
  const rows = new Map();
  hits.forEach((hit, index) => {
    const key = hit.kind !== "text" ? index : JSON.stringify([
      hit.pair, hit.base, hit.head, hit.revision, hit.path, hit.group,
      hit.row, hit.side, hit.line, hit.text, hit.from - hit.snippet_from,
    ]);
    if (!rows.has(key)) rows.set(key, { hit, indices: [] });
    rows.get(key).indices.push(index);
  });
  return rows.values();
}

export function setupSearchPalette({ search, cancel, openHit, onError }) {
  const dialog = $("search-palette");
  const input = $("palette-query");
  const scope = $("palette-scope");
  const list = $("palette-results");
  const status = $("palette-status");
  let generation = 0, timer, pending = false, hits = [], options = [], marks = [], selected = -1;
  let opening, cancellation, activating = false;

  function invalidate() {
    const token = ++generation;
    clearTimeout(timer);
    if (pending) cancellation = cancel();
    pending = false;
    return token;
  }

  function reveal(index) {
    const mark = marks[index];
    if (!mark) return;
    const area = mark.parentElement;
    const offset = mark.offsetLeft;
    if (offset < area.scrollLeft || offset + mark.offsetWidth > area.scrollLeft + area.clientWidth)
      area.scrollLeft = Math.max(0, offset - 24);
  }

  function revealSelected() {
    const option = options[selected];
    if (!dialog.open || !option) return;
    option.scrollIntoView({ block: "nearest" });
    reveal(selected);
  }

  function select(index) {
    options[selected]?.setAttribute("aria-selected", "false");
    marks[selected]?.classList.remove("palette-current");
    selected = index;
    const option = options[index];
    if (option) {
      option.setAttribute("aria-selected", "true");
      marks[index]?.classList.add("palette-current");
      input.setAttribute("aria-activedescendant", option.id);
      revealSelected();
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  new ResizeObserver(revealSelected).observe(list);

  function close() {
    invalidate();
    dialog.close();
    input.setAttribute("aria-expanded", "false");
    if (opening?.isConnected) opening.focus({ preventScroll: true });
  }

  async function activate(index) {
    const hit = hits[index];
    if (!dialog.open || !hit || activating) return;
    activating = true;
    close();
    try {
      await openHit(hit);
    } catch (err) {
      onError(String(err));
    } finally {
      activating = false;
    }
  }

  function render() {
    options = [];
    marks = [];
    const rows = [...paletteRows(hits)];
    for (const [kind, label] of Object.entries(groups)) {
      const group = el("div", null, "palette-group");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", label);
      const heading = el("div", label, "palette-group-label");
      heading.setAttribute("aria-hidden", "true");
      group.append(heading);
      for (const { hit, indices } of rows) {
        if (hit.kind !== kind) continue;
        const first = indices[0];
        const option = el("div", null, "palette-option");
        option.id = "palette-result-" + first;
        option.dataset.searchKind = kind;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        const title = el("span", null, "palette-title");
        const meta = el("span", null, "palette-meta");
        const path = hit.path ? labelPath(hit.path) : "";
        const source = hit.pair?.map(refName).join(" → ");
        meta.textContent = [hit.group, source, (hit.sha || hit.revision)?.slice(0, 8)].filter(Boolean).join(" · ");
        meta.title = meta.textContent;
        option.append(title, meta);
        let target = title;
        if (kind === "text" || kind === "comment") {
          title.textContent = path + (hit.line ? ` · ${hit.side === "old" ? "Old " : ""}L${hit.line}` : "");
          target = el("code", null, "palette-preview");
          option.append(target);
        }
        title.title = path || hit.text;
        let end = 0;
        for (const index of indices) {
          options[index] = option;
          const { snippet_from: from, snippet_to: to } = hits[index];
          if (from >= to || from == null) continue;
          target.append(hit.text.slice(end, from));
          const mark = el("mark", hit.text.slice(from, to));
          mark.dataset.hit = index;
          marks[index] = mark;
          target.append(mark);
          end = to;
        }
        target.append(hit.text.slice(end));
        option.onmousedown = (e) => e.preventDefault();
        option.onclick = (e) => {
          const index = e.target.closest("mark")?.dataset.hit;
          activate(index == null ? first : Number(index));
        };
        group.append(option);
      }
      if (group.children.length > 1) list.append(group);
    }
    for (const { indices } of rows) reveal(indices[0]);
    select(hits.length ? 0 : -1);
  }

  function refresh() {
    const token = invalidate(), query = input.value, kind = scope.value;
    hits = [];
    options = [];
    marks = [];
    list.replaceChildren();
    select(-1);
    status.textContent = query ? "Searching…" : "Search files, diffs, comments, commits, and branches";
    if (!query) return;
    const delay = kind === "file" || kind === "patch" ? 0 : kind === "branch" ? 130 : 40;
    timer = setTimeout(async () => {
      await cancellation;
      if (token !== generation || !dialog.open) return;
      pending = true;
      try {
        const found = await search(kind, query);
        if (token !== generation || !dialog.open) return;
        hits = Object.keys(groups).flatMap((kind) => found.hits.filter((hit) => hit.kind === kind));
        render();
        status.textContent = !hits.length ? "No matches" : found.truncated
          ? `Showing ${hits.length} results. Refine your search for more.`
          : `${hits.length} ${hits.length === 1 ? "result" : "results"}`;
      } catch (err) {
        if (token === generation) status.textContent = "Search failed. " + String(err);
      } finally {
        if (token === generation) pending = false;
      }
    }, delay);
  }

  input.oninput = refresh;
  scope.onchange = () => {
    refresh();
    input.focus();
  };
  $("palette-close").onclick = close;
  dialog.oncancel = (e) => {
    e.preventDefault();
    close();
  };
  dialog.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    }
    if (e.target !== input) return;
    if (e.key === "Enter") {
      e.preventDefault();
      activate(selected);
    } else if (["ArrowUp", "ArrowDown"].includes(e.key) && hits.length) {
      e.preventDefault();
      const step = e.key === "ArrowUp" ? -1 : 1;
      select((selected + step + hits.length) % hits.length);
    }
  }, true);

  return {
    open(opener) {
      if (activating) return;
      if (!dialog.open) {
        opening = opener ?? document.activeElement;
        scope.value = "all";
        dialog.showModal();
        input.setAttribute("aria-expanded", "true");
        refresh();
      }
      input.focus();
      input.select();
    },
    get openDialog() { return dialog.open; },
    reset(repositoryChanged) {
      if (dialog.open) close();
      if (repositoryChanged) input.value = "";
    },
  };
}
