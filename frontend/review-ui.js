export const WORKTREE = ":worktree:";
export const EMPTY = ":empty:";

// The Rust Git reader hex-encodes byte paths that cannot round-trip through JSON.
export function labelPath(path) {
  if (/^␛git:(?:[0-9a-f]{2})+$/.test(path)) {
    const bytes = Uint8Array.from(path.slice(5).match(/../g), (hex) =>
      parseInt(hex, 16),
    );
    const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
    let decoded = "";
    for (let i = 0; i < bytes.length;) {
      const b = bytes[i],
        length = b < 128 ? 1 : b < 224 ? 2 : b < 240 ? 3 : 4;
      try {
        decoded += decoder.decode(bytes.subarray(i, i + length));
        i += length;
      } catch {
        decoded += "\\x" + b.toString(16).padStart(2, "0");
        i++;
      }
    }
    path = decoded;
  }
  return path
    .replaceAll("\n", "\\n")
    .replaceAll("\r", "\\r")
    .replaceAll("\t", "\\t");
}

export function refName(ref) {
  ref = labelPath(ref);
  if (ref === WORKTREE) return "Working tree";
  if (ref === EMPTY) return "Empty tree";
  if (ref.startsWith("HEAD@")) return "Detached HEAD " + ref.slice(5, 13);
  if (ref.startsWith("refs/remotes/")) return ref.slice(13) + " (remote)";
  return ref.replace(/^refs\/heads\//, "");
}

export function pairs(stack, checkout) {
  const choices = [];
  if (stack.length >= 2) choices.push(["Full stack", [stack[0], stack.at(-1)]]);
  if (stack.length > 2) {
    for (let i = 1; i < stack.length; i++)
      choices.push(["Layer " + i, [stack[i - 1], stack[i]]]);
  }
  choices.push(["Working tree", [checkout, WORKTREE]]);
  return choices;
}

export function scopeNotes(state, entire) {
  if (entire) return state.notes;
  const branches = state.stack.map((r) =>
    r === "HEAD" ? state.repo.checkout : r,
  );
  if (localScope(state))
    return state.notes.filter(
      (n) => n.left === state.repo.checkout && n.right === WORKTREE,
    );
  const committed = pairs(state.stack, state.repo.checkout).slice(0, -1);
  return state.notes.filter((n) =>
    n.right === WORKTREE
      ? branches.includes(n.left)
      : committed.some(
          ([, [left, right]]) => left === n.left && right === n.right,
        ),
  );
}

export function localScope(state) {
  return (
    state.pair[1] === WORKTREE &&
    !state.stack.some(
      (ref) =>
        ref === state.repo.checkout ||
        (ref === "HEAD" && state.repo.checkout.startsWith("HEAD@")),
    )
  );
}

export function fileNotes(state, file) {
  if (!file) return [];
  return state.notes.flatMap((note) => {
    const dest = state.locations[note.id]?.find(
      (d) =>
        d.left === state.pair[0] &&
        d.right === state.pair[1] &&
        d.path === file.path &&
        d.group === file.group,
    );
    return dest ? [{ ...note, old: dest.old, new: dest.new }] : [];
  });
}

export function decodePatch([text, starts]) {
  if (!text) return [];
  const rows = text.split("\n");
  rows.pop(); // Every encoded row has a terminator, including empty code lines.
  let hunk = 0;
  let old = 0,
    next = 0;
  return rows.map((row) => {
    const kind = row[0];
    if (kind === "@") [old, next] = starts[hunk++];
    return {
      kind,
      text: kind === "@" || kind === "\\" ? row : row.slice(1),
      old: kind === "-" || kind === " " ? old++ : null,
      new: kind === "+" || kind === " " ? next++ : null,
      hunk,
    };
  });
}

export function spans(note) {
  return (
    ["old", "new"]
      .filter((side) => note[side]?.length)
      .map((side) => {
        const [a, b] = note[side];
        return side + " L" + a + (a === b ? "" : "–" + b);
      })
      .join(" · ") || "Whole file"
  );
}

export function suggestionSource(note) {
  return note.excerpt
    .split("\n")
    .filter((line) => /^[+ ]/.test(line))
    .map((line) => line.slice(1))
    .join("\n");
}

export function noteDestination(state, note) {
  // Prefer the current comparison, then the working tree, then the note's branch.
  const score = (d) =>
    (d.left === state.pair[0] && d.right === state.pair[1] ? 0 : 4) +
    (d.right === WORKTREE ? 0 : 2) +
    (d.right === note.left ? 0 : 1);
  const locations = state.locations[note.id] || [];
  if (locations.length)
    return locations.reduce((best, d) => (score(d) < score(best) ? d : best));
  if (
    note.right !== WORKTREE &&
    state.repo.refs[note.right] === note.head &&
    state.repo.refs[note.left] === note.left_tip &&
    pairs(state.stack, state.repo.checkout).some(
      ([, p]) => p[0] === note.left && p[1] === note.right,
    )
  ) {
    return { ...note, group: "" };
  }
  return null;
}

export function commentRow(note, destination) {
  const shown = destination || note;
  const source =
    shown.group ||
    (destination && (note.right === WORKTREE || note.applied_anchor)
      ? refName(shown.right)
      : "");
  const body = (note.body || "").split(/\r?\n/).join(" ");
  const kind =
    note.suggestion == null
      ? ""
      : note.applied_location
        ? "Applied suggestion"
        : "Suggested change";
  return {
    path: labelPath(shown.path),
    comparison: refName(shown.left) + " → " + refName(shown.right),
    lines: [source, spans(shown)].filter(Boolean).join(" · "),
    summary: [kind, body].filter(Boolean).join(" · "),
  };
}

export function setFold(folds, note, collapsed) {
  if (!!note.resolved === collapsed) folds.delete(note.id);
  else folds.set(note.id, collapsed);
}
