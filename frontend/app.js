import { invoke } from "@tauri-apps/api/core";
import {
  canExpandFile,
  contextMenu,
  createDiff,
  isContextMenuKey,
} from "./editor.js";
import { localPaletteHits, metadataHits, setupSearchPalette } from "./search-palette.js";
import { icon } from "./icons.js";
import "./editor.css";
import {
  $,
  el,
  button,
  commentStatus,
  compose,
  details,
  preview,
  stackDialog,
  showBranchFile,
} from "./dialogs.js";
import {
  WORKTREE,
  EMPTY,
  commentRow,
  decodePatch,
  labelPath,
  noteDestination,
  noteFileIndex,
  setFold,
  refName,
  pairs,
  scopeNotes,
  localScope,
  fileNotes,
  suggestionSource,
} from "./review-ui.js";

let state,
  tab = "Changes",
  mode = "unified",
  fileIndex = -1,
  selectedNote,
  editor,
  openFilter = "Open";
let lines = [],
  commits = null,
  editLock = false,
  loading = false,
  sequence = 0;
let fileTree;
const positions = new Map(),
  folds = new Map();
const files = () => state?.comparison?.files ?? [];
const currentFile = () => files()[fileIndex];
const names = ["Changes", "Commits", "Comments"];
for (const node of document.querySelectorAll("[data-icon]"))
  node.replaceWith(icon(node.dataset.icon));
const closedFolders = new Set(),
  closedSearchFolders = new Set();
const basename = (path) => path.split(/[\\/]/).filter(Boolean).at(-1) || path;
const request = (op, args = {}, snapshot = state?.snapshot) =>
  invoke("workspace", { request: { op, ...args }, snapshot: snapshot ?? null });
let preferenceWrite = Promise.resolve();
function savePreference(op, args) {
  preferenceWrite = preferenceWrite
    .then(() => request(op, args))
    .catch((err) => status(String(err), true));
  return preferenceWrite;
}
const status = (message = "", error = false) => {
  $("status").textContent = message;
  $("status").title = message;
  $("status").classList.toggle("error", error);
};
const handle =
  (fn) =>
  async (...args) => {
    try {
      return await fn(...args);
    } catch (err) {
      status(String(err), true);
    }
  };
const on = (id, fn) => {
  $(id).onclick = handle(fn);
};
function activate(node, active) {
  node.classList.toggle("active", active);
  node.setAttribute("aria-pressed", String(active));
}
function empty(node, message) {
  node.replaceChildren(el("p", message, "empty"));
}
function tableMessage(body, message) {
  const row = el("tr"),
    cell = el("td", message, "empty");
  cell.colSpan = body
    .closest("table")
    .tHead.querySelectorAll("th:not([hidden])").length;
  row.append(cell);
  body.replaceChildren(row);
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const field = el("textarea");
    const previous = document.activeElement;
    (document.querySelector("dialog[open]") || document.body).append(field);
    field.value = text;
    field.select();
    const ok = document.execCommand("copy");
    field.remove();
    previous?.focus();
    if (!ok) throw Error("The clipboard is unavailable.");
  }
  status("Copied to clipboard");
}
function positionKey() {
  const f = currentFile(),
    c = state?.comparison;
  return (
    f &&
    c &&
    JSON.stringify([
      state.repo.root,
      c.left,
      c.right,
      f.group,
      f.path,
      f.old_oid,
      f.oid,
    ])
  );
}
function leaveFile() {
  if (editor) {
    positions.set(positionKey(), editor.getPosition());
    editor.destroy();
    editor = null;
  }
  lines = [];
  sequence++;
  $("comment-jump-context").hidden = true;
  $("full-file").disabled = true;
  contextButton({ full: false, expanded: false });
}
function choiceIndex() {
  return pairs(state.stack, state.repo.checkout).findIndex(
    ([, p]) => p[0] === state.pair[0] && p[1] === state.pair[1],
  );
}

async function changeWorkspace(op, args) {
  if (loading || editLock) return;
  loading = true;
  $("app").setAttribute("aria-busy", "true");
  status("Reading Git changes…");
  try {
    const previous = currentFile(),
      previousRoot = state?.repo.root;
    const pending = preferenceWrite;
    if (op === "open") await pending;
    const next = await request(op, args);
    leaveFile();
    if (
      previousRoot !== next.repo.root ||
      state?.pair[0] !== next.pair[0] ||
      state?.pair[1] !== next.pair[1]
    ) {
      closedFolders.clear();
      closedSearchFolders.clear();
    }
    palette.reset(previousRoot !== next.repo.root);
    state = next;
    for (const n of state.notes)
      if (folds.get(n.id) === !!n.resolved) folds.delete(n.id);
    if (previousRoot !== state.repo.root) {
      positions.clear();
      folds.clear();
      selectedNote = undefined;
      tab = "Changes";
      openFilter = "Open";
      $("filter").value = "";
      $("scope").value = "current";
    }
    fileIndex = -1;
    commits = null;
    $("welcome").hidden = true;
    $("workspace").hidden = false;
    $("find").disabled = false;
    const name = basename(state.repo.root);
    document.title = name + " · Branchline";
    $("crumb").textContent = name;
    $("repo-name").textContent = name;
    $("project-initial").textContent =
      Array.from(name)[0]?.toUpperCase() || "•";
    $("choose").title = state.repo.root;
    if (op === "open" && pending === preferenceWrite) {
      setWidth(state.width);
      setMode(state.diff_layout);
    }
    const choices = pairs(state.stack, state.repo.checkout);
    $("pair").replaceChildren(
      ...choices.map(([label], i) => new Option(label, String(i))),
    );
    const activePair = choiceIndex();
    $("pair").selectedIndex = activePair;
    const local = state.pair[1] === WORKTREE;
    $("page-title").textContent = local
      ? "Working tree review"
      : activePair === 0
        ? "Branch stack review"
        : "Branch comparison";
    const refs = state.pair.map((ref) => {
      const chip = el("span", "", "ref-chip");
      chip.title = refName(ref);
      chip.append(
        icon(ref === WORKTREE ? "worktree" : "branch"),
        el("span", chip.title),
      );
      return chip;
    });
    $("range").replaceChildren(refs[0], icon("arrow"), refs[1]);
    renderComparisonStats();
    $("stack-review").disabled = state.stack.length < 2;
    $("local-review").disabled = false;
    $("search-review").disabled = false;
    activate($("stack-review"), !local);
    activate($("local-review"), local);
    $("stack").replaceChildren(
      ...state.stack.map((ref, i) => {
        const li = el("li"),
          b = button(
            "",
            handle(() =>
              selectPair(state.stack.length === 2 || i === 0 ? 0 : i),
            ),
          );
        b.append(
          el(
            "small",
            i === 0
              ? "Base"
              : i === state.stack.length - 1
                ? "Head"
                : "Layer " + i,
          ),
          el("span", refName(ref)),
        );
        b.title = refName(ref);
        if (activePair === i && i > 0 && !local)
          b.setAttribute("aria-current", "true");
        li.append(b);
        return li;
      }),
    );
    $("edit-stack").disabled = Object.keys(state.repo.refs).length < 2;
    $("scope").options[0].text = localScope(state)
      ? "Working tree"
      : "Current stack";
    $("export").disabled = false;
    $("refresh").disabled = false;
    for (const b of $("nav").querySelectorAll("button")) b.disabled = false;
    const ids = visibleFiles();
    const keep = ids.find(
      (i) =>
        previousRoot === state.repo.root &&
        previous &&
        files()[i].path === previous.path &&
        files()[i].group === previous.group,
    );
    fileIndex = keep ?? ids[0] ?? -1;
    await navigate(local && tab === "Commits" ? "Changes" : tab);
    const warning = [state.error, state.config_warning, state.mcp_warning]
      .filter(Boolean)
      .join(" · ");
    status(warning || "Comparison up to date", !!warning);
  } finally {
    loading = false;
    $("app").removeAttribute("aria-busy");
    if (state) $("pair").selectedIndex = choiceIndex();
  }
}
async function choose() {
  if (loading) return;
  const path = await invoke("choose_repository");
  if (path) await changeWorkspace("open", { path });
}
function refresh() {
  if (state)
    return changeWorkspace("open", { path: state.repo.root, pair: state.pair });
}
function selectPair(i) {
  const pair = pairs(state.stack, state.repo.checkout)[i]?.[1];
  if (pair) return changeWorkspace("compare", { pair });
}
function setWidth(width) {
  document.documentElement.style.setProperty(
    "--side",
    Math.round(Math.max(150, Math.min(width, window.innerWidth * 0.48, 800))) +
      "px",
  );
}
function showSidebar(show) {
  $("app").classList.toggle("without-sidebar", !show);
  $("sidebar").hidden = $("divider").hidden = !show;
  const toggle = $("sidebar-toggle");
  toggle.title = show ? "Hide project sidebar" : "Show project sidebar";
  toggle.setAttribute("aria-label", toggle.title);
  toggle.setAttribute("aria-expanded", String(show));
}
const compact = matchMedia("(max-width: 900px)");
let sidebarChoice;
const layoutSidebar = () => showSidebar(sidebarChoice ?? !compact.matches);
layoutSidebar();
compact.addEventListener("change", layoutSidebar);
on("sidebar-toggle", () => {
  sidebarChoice = $("sidebar").hidden;
  layoutSidebar();
});
async function navigate(name) {
  if (!state) return;
  tab = name;
  for (const n of names) $(n.toLowerCase()).hidden = n !== tab;
  for (const b of $("nav").querySelectorAll("button")) {
    const current = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(current));
    b.tabIndex = current ? 0 : -1;
  }
  chromeCounts();
  if (tab === "Changes") {
    if (!editor) await pick(fileIndex);
    else renderFiles();
  } else if (tab === "Comments") renderComments();
  else await renderCommits();
}
function chromeCounts() {
  $("nav").querySelector('[data-tab="Changes"] small').textContent =
    files().length;
  $("nav").querySelector('[data-tab="Comments"] small').textContent =
    scopeNotes(state, tab === "Comments" && $("scope").value === "all").length;
  const viewed = state.viewed.length;
  const total = files().length;
  $("viewed-meter").max = Math.max(1, total);
  $("viewed-meter").value = viewed;
  $("progress").textContent =
    `${viewed} of ${total} ${total === 1 ? "file" : "files"} viewed`;
}
function renderComparisonStats() {
  $("comparison-stats").hidden = !state.comparison;
  if (!state.comparison) return;
  const paths = new Set();
  let added = 0;
  let removed = 0;
  for (const file of files()) {
    paths.add(file.path);
    added += file.added ?? 0;
    removed += file.removed ?? 0;
  }
  const count = paths.size;
  $("comparison-files").textContent =
    `${count.toLocaleString()} ${count === 1 ? "file" : "files"} changed`;
  $("comparison-added").textContent = "+" + added.toLocaleString();
  $("comparison-removed").textContent = "−" + removed.toLocaleString();
}
const fileFilter = () => $("filter").value.trim().toLowerCase();
function visibleFiles(q = fileFilter()) {
  return files().flatMap((file, i) => {
    const matches =
      !q ||
      labelPath(file.path).toLowerCase().includes(q) ||
      labelPath(file.old).toLowerCase().includes(q);
    return matches ? [i] : [];
  });
}
function buildFileTree(source) {
  const rows = (source ?? []).map((f, i) => {
    const path = labelPath(f.path),
      parts = path.split("/");
    const b = button("", handle(() => pick(i, true)), "file-item");
    b.dataset.file = i;
    b.title = f.old !== f.path ? labelPath(f.old) + " → " + path : path;
    b.setAttribute("aria-label", b.title);
    activate(b, false);
    const badge = el("span", f.status, "badge"),
      viewed = el("span", "✓");
    badge.dataset.status = f.status;
    viewed.hidden = true;
    b.append(icon("file"), el("span", parts.at(-1), "path"), badge, viewed);
    return { button: b, viewed, directories: parts.slice(0, -1), group: f.group };
  });
  return { source, rows, selected: -1 };
}
function filterFileTree(rows, query) {
  const list = $("file-list"),
    frag = document.createDocumentFragment(),
    closed = query ? closedSearchFolders : closedFolders;
  const folders = new Map();
  function folder(parent, group, directory, label) {
    const key = JSON.stringify([group, directory]);
    if (!folders.has(key)) {
      const details = el("details"),
        summary = el("summary", "", "file-group");
      summary.append(icon("folder"), document.createTextNode(label));
      details.open = !closed.has(key);
      details.ontoggle = () => {
        if (!list.contains(details)) return;
        if (details.open) closed.delete(key);
        else closed.add(key);
      };
      details.append(summary);
      parent.append(details);
      folders.set(key, details);
    }
    return folders.get(key);
  }
  // Move cached buttons off the live tree so WebKit can lay out the new list once.
  list.replaceChildren();
  for (const i of visibleFiles(query)) {
    const { button, directories, group } = rows[i];
    let parent = group ? folder(frag, group, null, group) : frag;
    let directory = "";
    for (const part of directories) {
      directory += part + "/";
      parent = folder(parent, group, directory, part + "/");
    }
    parent.append(button);
  }
  list.append(frag);
  if (!list.firstChild)
    empty(list, rows.length ? "No matching files" : "No changed files");
}
function renderFiles() {
  const source = state.comparison?.files;
  if (!fileTree || fileTree.source !== source) fileTree = buildFileTree(source);
  const { rows, selected } = fileTree;
  const query = fileFilter();
  if (fileTree.query !== query) {
    filterFileTree(rows, query);
    fileTree.query = query;
  }
  if (selected !== fileIndex) {
    if (rows[selected]) activate(rows[selected].button, false);
    if (rows[fileIndex]) activate(rows[fileIndex].button, true);
    fileTree.selected = fileIndex;
  }
  if (fileTree.viewed !== state.viewed) {
    const viewed = new Set(state.viewed);
    rows.forEach((row, i) => {
      const hidden = !viewed.has(i);
      if (row.viewed.hidden !== hidden) row.viewed.hidden = hidden;
    });
    fileTree.viewed = state.viewed;
  }
  chromeCounts();
}
function canApply(note) {
  const f = currentFile();
  return (
    typeof note.suggestion === "string" &&
    !note.resolved &&
    !note.applied_location &&
    !!note.new?.length &&
    ["100644", "100755"].includes(f?.mode) &&
    (state.pair[1] === WORKTREE ||
      state.pair[1] ===
        (state.repo.checkout.startsWith("HEAD@")
          ? "HEAD"
          : state.repo.checkout))
  );
}
async function pick(index, focus = false, jump) {
  if (index === fileIndex && editor) {
    if (jump != null) editor.jump(jump);
    if (focus && tab === "Changes") editor.focus();
    return;
  }
  leaveFile();
  fileIndex = index;
  const f = currentFile(),
    token = sequence,
    snapshot = state.snapshot;
  renderFiles();
  $("filename").textContent = f ? labelPath(f.path) : "Diff";
  $("filename").title =
    f && f.old !== f.path
      ? labelPath(f.old) + " → " + labelPath(f.path)
      : labelPath(f?.path || "");
  $("file-stats").replaceChildren();
  if (f?.added != null)
    $("file-stats").append(
      el("span", "+" + f.added, "added"),
      "  ",
      el("span", "−" + f.removed, "removed"),
    );
  $("viewed").checked = state.viewed.includes(index);
  $("viewed").disabled = !f;
  $("comment").disabled = true;
  $("suggest").disabled = true;
  $("selection").textContent = "Whole file";
  $("selection-help").textContent = "";
  $("diff").replaceChildren();
  if (!f) {
    empty(
      $("diff"),
      state.error ||
        (files().length && fileFilter()
          ? "No changed files match the filter."
          : files().length ? "Choose a file" : "No changes in this comparison"),
    );
    return;
  }
  try {
    const data = await request("display_patch", { file: index });
    if (sequence !== token) return;
    lines = decodePatch(data);
    editor = createDiff($("diff"), {
      file: f,
      emptyBase: state.comparison.base === state.repo.refs[EMPTY],
      lines,
      notes: fileNotes(state, f),
      loadContents: () => request("file_contents", { file: index }, snapshot),
      onContextChange: contextButton,
      mode,
      position: positions.get(positionKey()),
      folds,
      onCompose: newComment,
      onAction: handle(noteAction),
      onStatus: status,
      canApply,
      onCopy: copy,
      onSelection: ({ label, canSuggest, canComment, commentDisabledReason }) => {
        $("comment").disabled = !canComment;
        if ($("selection").textContent !== label)
          $("selection").textContent = label;
        const help = $("selection-help");
        const reason = commentDisabledReason ?? "";
        if (help.textContent !== reason) help.textContent = reason;
        $("suggest").disabled = !canSuggest;
      },
    });
    $("full-file").disabled = !canExpandFile(f);
    if (jump != null) editor.jump(jump);
    if (focus && tab === "Changes") editor.focus();
  } catch (err) {
    if (sequence === token) {
      empty($("diff"), String(err));
      status(String(err), true);
    }
  }
}
function setMode(value, save = false) {
  const changed = mode !== value;
  mode = value;
  activate($("unified"), value === "unified");
  activate($("split"), value === "split");
  editor?.setMode(value);
  if (save && changed) return savePreference("layout", { layout: value });
}
function newComment(selection) {
  const file = currentFile(),
    snapshot = state.snapshot,
    index = fileIndex;
  const indices = new Map(lines.map((line, i) => [line, i]));
  const rows = selection.lines.map((l) => indices.get(l));
  const span = (side) => {
    if (selection.side !== "both" && selection.side !== side) return [];
    const nums = selection.lines.map((l) => l[side]).filter((n) => n != null);
    return nums.length ? [nums[0], nums.at(-1)] : [];
  };
  const n = {
    path: file.path,
    group: file.group,
    old: span("old"),
    new: span("new"),
    excerpt: selection.lines.map((l) => l.kind + l.text).join("\n"),
  };
  if (selection.suggestion) n.suggestion = suggestionSource(n);
  const draftKey = JSON.stringify([
    state.repo.root, "new", state.pair, n.path, n.group,
    selection.side, n.old, n.new, n.excerpt, selection.suggestion,
  ]);
  compose(
    n,
    {
      save: (body, suggestion) =>
        update(
          "create",
          { file: index, rows, side: selection.side, body, suggestion },
          snapshot,
        ),
    },
    draftKey,
  );
}
async function update(op, args, snapshot = state.snapshot) {
  if (editLock || loading)
    throw Error("Wait for the current operation to finish.");
  editLock = true;
  try {
    const changed = await request(op, args, snapshot);
    if (snapshot !== state.snapshot) return;
    Object.assign(state, changed);
    if (op === "resolve") folds.delete(args.id);
    editor?.setNotes(fileNotes(state, currentFile()));
    chromeCounts();
    if (tab === "Comments") renderComments();
    status(op === "delete" ? "Comment deleted" : "Review saved");
  } finally {
    editLock = false;
  }
}
function editNote(note) {
  const snapshot = state.snapshot;
  const draftKey = JSON.stringify([state.repo.root, "edit", note.id]);
  compose(
    note,
    {
      save: (body, suggestion) =>
        update("edit", { original: note, body, suggestion }, snapshot),
      remove: () => update("delete", { id: note.id }, snapshot),
    },
    draftKey,
  );
}
async function noteAction(action, projected) {
  const note = state.notes.find((n) => n.id === projected.id);
  if (!note) throw Error("This comment has been removed.");
  if (action === "edit") return editNote(note);
  if (action === "apply") {
    await update("apply", { original: note, file: fileIndex });
    await refresh();
    return;
  }
  if (action === "resolve" || action === "reopen")
    await update("resolve", { id: note.id, value: action === "resolve" });
}
async function jumpToNote(note) {
  if (loading || editLock) return;
  await refresh();
  note = state.notes.find((current) => current.id === note.id);
  if (!note) throw Error("This comment has been removed.");
  const dest = noteDestination(state, note);
  const branch = note.right === WORKTREE ? note.left : note.right;
  const checkout = state.repo.checkout;
  const isCheckout = branch === checkout || (branch === "HEAD" && checkout.startsWith("HEAD@"));
  const choices = pairs(state.stack, checkout).map(([, pair]) => pair);
  const samePair = (a, b) => a[0] === b[0] && a[1] === b[1];
  const candidates = [
    isCheckout ? [checkout, WORKTREE] : null,
    dest ? [dest.left, dest.right] : null,
    choices.find((pair) => samePair(pair, [note.left, note.right])),
    choices.find((pair) => pair[1] === branch),
  ].filter(Boolean);
  const visited = new Set();
  for (const pair of candidates) {
    const key = JSON.stringify(pair);
    if (visited.has(key)) continue;
    visited.add(key);
    if (!samePair(pair, state.pair)) await changeWorkspace("compare", { pair });
    if (!samePair(pair, state.pair)) return;
    const anchor = state.locations[note.id]?.find((d) => samePair(pair, [d.left, d.right]));
    const exact = anchor
      ? files().findIndex((file) => file.path === anchor.path && file.group === anchor.group)
      : -1;
    const latest = noteFileIndex(files(), note);
    // A partially staged file can have newer edits than its verified staged anchor.
    const newer = exact >= 0 && files()[exact].group === "Staged" &&
      latest >= 0 && files()[latest].group === "Unstaged" &&
      (files()[latest].path === files()[exact].path || files()[latest].old === files()[exact].path);
    const index = exact >= 0 && !newer ? exact : latest;
    if (index < 0) continue;
    const anchored = index === exact;
    if (anchored) setFold(folds, note, false);
    $("filter").value = "";
    const snapshot = state.snapshot;
    await navigate("Changes");
    if (state.snapshot !== snapshot) return;
    editor?.setNotes(fileNotes(state, currentFile()));
    await pick(index, true, anchored ? note.id : undefined);
    if (state.snapshot !== snapshot || index !== fileIndex) return;
    revealFileInTree(index);
    $("comment-jump-context").hidden = anchored || !editor;
    if (!anchored && editor) {
      $("jump-open-original").onclick = handle(() => {
        const original = state.notes.find((current) => current.id === note.id);
        if (original) editNote(original);
      });
    }
    return;
  }
  const snapshot = state.snapshot;
  const current = await request("comment_file", { id: note.id }, snapshot);
  if (state.snapshot !== snapshot) return;
  if (current) {
    showBranchFile({ path: note.path, revision: current.revision }, current.file, current.branch, note);
  } else {
    status("The current file is unavailable. Showing the original comment.");
    editNote(note);
  }
}
function revealFileInTree(index) {
  const list = $("file-list");
  const row = fileTree?.rows[index]?.button;
  if (!row || !list.contains(row)) return;
  for (let node = row.parentElement; node && node !== list; node = node.parentElement) {
    if (node.tagName === "DETAILS") node.open = true;
  }
  if (getComputedStyle(list).visibility !== "visible") return;
  const bounds = list.getBoundingClientRect();
  const rect = row.getBoundingClientRect();
  if (rect.top < bounds.top)
    list.scrollTop -= Math.ceil(bounds.top - rect.top);
  else if (rect.bottom > bounds.bottom)
    list.scrollTop += Math.ceil(rect.bottom - bounds.bottom);
}
function renderComments() {
  chromeCounts();
  const entire = $("scope").value === "all";
  $("comparison-column").hidden = !entire;
  const notes = scopeNotes(state, entire),
    open = notes.filter((n) => !n.resolved).length;
  $("comments-title").textContent =
    open + " open · " + (notes.length - open) + " resolved";
  const rows = notes.filter(
    (n) => openFilter === "All" || n.resolved === (openFilter === "Resolved"),
  );
  const body = $("note-table").tBodies[0];
  const previousIndex = Math.max(
    0,
    Array.from(body.rows).findIndex(
      (row) => Number(row.dataset.id) === selectedNote,
    ),
  );
  const hadFocus = body.contains(document.activeElement);
  if (!rows.some((n) => n.id === selectedNote))
    selectedNote = rows[Math.min(previousIndex, rows.length - 1)]?.id;
  for (const b of $("filters").children)
    activate(b, b.textContent === openFilter);
  const select = (id) => {
    selectedNote = id;
    for (const row of body.rows)
      row.classList.toggle("selected", Number(row.dataset.id) === id);
    const n = rows.find((n) => n.id === id);
    $("open-comment").disabled = !n;
    $("show-diff").disabled = !n;
    $("toggle-resolved").disabled = !n;
    $("toggle-resolved").textContent = n?.resolved ? "Reopen" : "Resolve";
  };
  body.replaceChildren(
    ...rows.map((n) => {
      const row = el("tr");
      row.dataset.id = n.id;
      row.tabIndex = 0;
      const chip = el("td");
      chip.append(commentStatus(n.resolved));
      const destination = noteDestination(state, n);
      if (!destination)
        chip.append(el("div", "Original snapshot", "comment-range"));
      const shown = commentRow(n, destination);
      row.append(el("td", shown.path, "comment-path"));
      if (entire) row.append(el("td", shown.comparison, "comment-range"));
      const summary = el("td", shown.summary, "comment-summary");
      summary.title = shown.summary;
      row.append(el("td", shown.lines, "comment-range"), chip, summary);
      row.onclick = row.onfocus = () => select(n.id);
      row.ondblclick = () => editNote(n);
      row.onkeydown = (e) => {
        if (e.key === "Enter") editNote(n);
      };
      return row;
    }),
  );
  if (!rows.length)
    tableMessage(
      body,
      "No " +
        (openFilter === "All" ? "" : openFilter.toLowerCase() + " ") +
        "comments in this scope.",
    );
  select(selectedNote);
  if (hadFocus) body.querySelector("tr.selected")?.focus();
}
async function renderCommits() {
  const body = $("commit-table").tBodies[0],
    token = state.snapshot;
  if (!commits) {
    if (!state.comparison || state.pair[1] === WORKTREE) {
      tableMessage(body, "Choose a branch comparison to see its commits.");
      $("commits-title").textContent = "Commits";
      return;
    }
    tableMessage(body, "Reading commits…");
    const data = await request("commits");
    if (state.snapshot !== token) return;
    commits = data;
  }
  $("commits-title").textContent = "Commits · " + commits.length;
  body.replaceChildren(
    ...commits.map((c) => {
      const row = el("tr");
      row.tabIndex = 0;
      const values = [c.subject, c.author, c.date, c.sha.slice(0, 9)];
      const show = handle(async () =>
        details("Commit details", await request("details", { sha: c.sha })),
      );
      row.ondblclick = show;
      const openMenu = (position, value = values[0]) =>
        contextMenu(position, [
          ["Copy value", handle(() => copy(value))],
          ["Copy row", handle(() => copy(values.join("\t")))],
          ["Copy full SHA", handle(() => copy(c.sha))],
          ["Commit details…", show],
          ["Fit columns to content", fitColumns],
        ]);
      row.onkeydown = (event) => {
        if (event.key === "Enter") show();
        if (!isContextMenuKey(event)) return;
        event.preventDefault();
        const { left, bottom } = row.getBoundingClientRect();
        openMenu({ target: row, clientX: left + 12, clientY: bottom });
      };
      values.forEach((value, column) => {
        const cell = el("td", value);
        if (column === 3) cell.replaceChildren(el("code", value, "commit-sha"));
        cell.oncontextmenu = (event) => {
          event.preventDefault();
          openMenu(event, value);
        };
        row.append(cell);
      });
      return row;
    }),
  );
  if (!commits.length) tableMessage(body, "No commits in this comparison.");
}
function fitColumns() {
  $("commit-table").classList.add("fit");
}
async function exportReview() {
  if (!state) return;
  const token = state.snapshot;
  status("Checking current comment locations…");
  const entire = tab === "Comments" && $("scope").value === "all";
  const scope = entire
    ? ["repository"]
    : localScope(state)
      ? ["working-tree", state.repo.checkout]
      : ["stack", state.stack];
  const draftKey = JSON.stringify([state.repo.root, "markdown", scope]);
  const drafts = await request("export", { entire });
  if (state.snapshot !== token) return;
  preview(
    drafts,
    copy,
    async (content) => {
      if (await invoke("save_markdown", { content })) status("Markdown saved");
    },
    draftKey,
  );
  status(
    drafts.cached
      ? "Markdown preview uses the displayed comments. Git could not refresh their locations."
      : "Markdown preview ready",
  );
}
function contextButton({ full, expanded }) {
  activate($("full-file"), full);
  $("full-file").textContent = full ? "Changes only" : "Full file";
  $("collapse-context").hidden = full || !expanded;
}
on("full-file", () =>
  $("full-file").getAttribute("aria-pressed") === "true"
    ? editor?.collapseContext()
    : editor?.showFullFile(),
);
on("collapse-context", () => editor?.collapseContext());

async function openSearchHit(hit, valid) {
  if (hit.revision) {
    const snapshot = state.snapshot;
    const contents = await request("branch_file", {
      path: hit.path,
      revision: hit.revision,
    });
    if (valid() && state.snapshot === snapshot)
      showBranchFile(hit, contents, hit.pair[1] === WORKTREE ? hit.pair[0] : hit.pair[1]);
    return;
  }
  if (state.pair[0] !== hit.pair[0] || state.pair[1] !== hit.pair[1]) {
    await changeWorkspace("compare", { pair: hit.pair });
  }
  if (!valid()) return;
  const c = state.comparison;
  if (
    !c ||
    c.left !== hit.pair[0] ||
    c.right !== hit.pair[1] ||
    c.base !== hit.base ||
    c.head !== hit.head
  ) {
    throw Error(
      "This comparison changed. Refresh the search to locate this match.",
    );
  }
  const i = files().findIndex(
    (f) => f.path === hit.path && f.group === hit.group,
  );
  if (i < 0) throw Error("This file changed. Refresh the search.");
  if (fileIndex !== i) $("filter").value = "";
  const snapshot = state.snapshot;
  await navigate("Changes");
  if (!valid() || snapshot !== state.snapshot) return;
  await pick(i, true);
  if (!valid() || snapshot !== state.snapshot || fileIndex !== i) return;
  revealFileInTree(i);
  if (hit.kind === "path") return;
  const revealed = hit.localFile
    ? await editor?.revealLine(hit.side, hit.line, hit.from, hit.to)
    : editor?.revealPatchRow(hit.row, hit.from, hit.to);
  if (!revealed) throw Error("This match is no longer in the displayed diff.");
}

async function searchPalette(scope, query) {
  const captured = state;
  const file = currentFile();
  const capturedEditor = editor;
  let result;
  if (scope === "file" || scope === "patch") {
    if (!capturedEditor || !file || !captured.comparison)
      throw Error("Choose a text file for this scope.");
    const contents = scope === "file" ? await capturedEditor.contents() : null;
    if (captured !== state || editor !== capturedEditor) throw Error("The displayed file changed.");
    const { base, head } = captured.comparison;
    result = localPaletteHits(scope, query, contents, lines, {
      pair: captured.pair, base, head, path: file.path, group: file.group,
    });
  } else {
    result = await invoke("search_review", {
      snapshot: captured.snapshot, scope, query,
    });
  }
  if (state !== captured) throw Error("The review changed. Open search again.");
  if (scope === "all") {
    const metadata = metadataHits(query, captured);
    result.hits.push(...metadata.hits);
    result.truncated ||= metadata.truncated;
  }
  for (const hit of result.hits) hit.snapshot = captured.snapshot;
  return result;
}

const palette = setupSearchPalette({
  search: searchPalette,
  cancel: () => invoke("search_review", { snapshot: state.snapshot, scope: "all", query: "" }).catch(() => {}),
  onError: (message) => status(message, true),
  async openHit(hit) {
    if (loading || editLock || hit.snapshot !== state.snapshot)
      throw Error("The review changed. Open search again.");
    const root = state.repo.root;
    const valid = () => root === state.repo.root && !$("dialog").open;
    if (hit.kind === "comment") {
      const note = state.notes.find((note) => note.id === hit.id);
      if (note) await jumpToNote(note);
    } else if (hit.kind === "commit" || hit.kind === "branch") {
      if (!state.pair.every((ref, i) => ref === hit.pair[i]))
        await changeWorkspace("compare", { pair: hit.pair });
      if (!valid() || !state.pair.every((ref, i) => ref === hit.pair[i]))
        throw Error("This comparison is no longer available.");
      if (hit.kind === "commit") {
        await navigate("Commits");
        const token = state.snapshot;
        const data = await request("details", { sha: hit.sha });
        if (valid() && state.snapshot === token) details("Commit details", data);
      } else {
        await navigate("Changes");
        $("pair").focus();
      }
    } else {
      await openSearchHit(hit, valid);
    }
  },
});
function openPalette(opener) {
  if (state && !loading && !editLock && !$("dialog").open) palette.open(opener);
}
on("find", () => openPalette($("find")));
for (const id of ["choose", "welcome-open"]) on(id, choose);
on("refresh", refresh);
on("search-review", () => openPalette($("search-review")));
on("stack-review", () => selectPair(0));
on("local-review", () => selectPair($("pair").options.length - 1));
on("export", exportReview);
on("fit", fitColumns);
on("edit-stack", () =>
  stackDialog(
    state,
    (base, branch) => request("discover", { base, branch }),
    (refs) => changeWorkspace("set_stack", { refs }),
  ),
);
on("split", () => setMode("split", true));
on("unified", () => setMode("unified", true));
on("comment", () => editor?.comment());
on("suggest", () => editor?.suggest());
on("toggle-resolved", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) return update("resolve", { id: n.id, value: !n.resolved });
});
on("open-comment", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) editNote(n);
});
on("show-diff", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) return jumpToNote(n);
});
$("pair").onchange = handle(() => selectPair($("pair").selectedIndex));
$("scope").onchange = renderComments;
for (const b of $("filters").children)
  b.onclick = () => {
    openFilter = b.textContent;
    renderComments();
  };
for (const b of $("nav").querySelectorAll("button")) {
  b.disabled = true;
  b.onclick = handle(() => navigate(b.dataset.tab));
  b.onkeydown = (event) => {
    const i = names.indexOf(b.dataset.tab);
    const next = {
      ArrowRight: (i + 1) % names.length,
      ArrowLeft: (i + names.length - 1) % names.length,
      Home: 0,
      End: names.length - 1,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = $("nav").querySelector(`[data-tab="${names[next]}"]`);
    target.focus();
    target.click();
  };
}
$("viewed").onchange = handle(async () => {
  const file = fileIndex,
    value = $("viewed").checked,
    token = state.snapshot;
  try {
    await request("viewed", { file, value }, token);
    if (state.snapshot !== token) return;
    state.viewed = state.viewed.filter((i) => i !== file);
    if (value) state.viewed.push(file);
    renderFiles();
  } catch (err) {
    if (state.snapshot === token && fileIndex === file)
      $("viewed").checked = state.viewed.includes(file);
    throw err;
  }
});
$("filter").oninput = handle(async () => {
  closedSearchFolders.clear();
  const ids = visibleFiles();
  if (!ids.includes(fileIndex)) await pick(ids[0] ?? -1);
  else renderFiles();
  if (fileFilter()) revealFileInTree(fileIndex);
});
$("filter").onkeydown = (e) => {
  if (e.key === "Enter") editor?.focus();
  if (e.key === "Escape") {
    e.preventDefault();
    $("filter").value = "";
    $("filter").oninput();
  }
};
let dragging = false;
const divider = $("divider");
const persistWidth = handle(
  () =>
    state &&
    savePreference("width", {
      width: Math.round($("sidebar").getBoundingClientRect().width),
    }),
);
divider.onpointerdown = (e) => {
  dragging = true;
  divider.setPointerCapture(e.pointerId);
  e.preventDefault();
};
divider.onpointermove = (e) => {
  if (dragging) setWidth(e.clientX);
};
divider.onpointerup = () => {
  dragging = false;
  persistWidth();
};
divider.onpointercancel = () => {
  dragging = false;
};
divider.onkeydown = (e) => {
  if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
    e.preventDefault();
    setWidth($("sidebar").offsetWidth + (e.key === "ArrowRight" ? 12 : -12));
    persistWidth();
  }
};
document.addEventListener(
  "keydown",
  handle(async (e) => {
    if ($("dialog").open) return;
    const key = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && ["f", "p"].includes(key)) {
      e.preventDefault();
      return openPalette();
    }
    if (palette.openDialog) return;
    if ((e.ctrlKey || e.metaKey) && ["o", "b", "e"].includes(key)) {
      e.preventDefault();
      if (key === "o") return choose();
      if (!state) return;
      if (key === "b") return $("edit-stack").click();
      if (key === "e") return exportReview();
      return;
    }
    if (e.key === "F5") {
      e.preventDefault();
      return refresh();
    }
    if (
      state &&
      !e.defaultPrevented &&
      e.altKey &&
      ["ArrowDown", "ArrowUp"].includes(e.key) &&
      !e.target.closest("input, select, textarea, [role=menu]")
    ) {
      e.preventDefault();
      await navigate("Changes");
      const ids = Array.from(
        $("file-list").querySelectorAll("button[data-file]"),
      )
        .filter(
          (b) => b.getClientRects().length && !b.closest("details:not([open])"),
        )
        .map((b) => Number(b.dataset.file));
      if (!ids.length) return;
      const direction = e.key === "ArrowDown" ? 1 : -1,
        from = ids.indexOf(fileIndex);
      const next =
        from < 0
          ? direction > 0
            ? 0
            : ids.length - 1
          : (from + direction + ids.length) % ids.length;
      await pick(ids[next], true);
    }
  }),
);
setMode("unified");
for (const id of ["export", "edit-stack", "refresh"]) $(id).disabled = true;
handle(async () =>
  changeWorkspace("open", { path: await invoke("startup_path") }),
)();
