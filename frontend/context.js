// Each gap begins at the next unread line on both sides. Git describes an empty
// hunk range by the number of the line *before* its insertion point.
export function contextGaps(patch, file) {
  if (file.status === "A" || file.status === "D" || file.group === "Untracked")
    return [];
  const gaps = [];
  let old = 1,
    next = 1;
  for (let i = 0; i < patch.length; i++) {
    const line = patch[i];
    if (line.kind === "@") {
      const range = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(
        line.text,
      );
      if (!range) continue;
      const startOld = Number(range[1]) + (range[2] === "0" ? 1 : 0);
      const startNew = Number(range[3]) + (range[4] === "0" ? 1 : 0);
      const count = startNew - next;
      if (count > 0 && count === startOld - old)
        gaps.push({ at: i, old, new: next, count });
      old = startOld;
      next = startNew;
    } else {
      if (line.old != null) old = line.old + 1;
      if (line.new != null) next = line.new + 1;
    }
  }
  // The Git reader requests three unchanged lines after each edit. A shorter
  // suffix reaches EOF. Otherwise the file lengths resolve the tail on demand.
  if (
    !patch.length ||
    (patch.length >= 3 && patch.slice(-3).every((line) => line.kind === " "))
  ) {
    gaps.push({ at: patch.length, old, new: next, count: null });
  }
  return gaps;
}

export function gapLength(gap, contents) {
  if (gap.count !== null || !contents) return gap.count;
  return Math.max(0, contents.length - gap.new + 1);
}

export const CONTEXT_STEP = 20;

export function expandGap(expanded, gap, count, action) {
  if (action === "collapse" || !count) {
    expanded.delete(gap.at);
    return;
  }
  if (action === "all") {
    expanded.set(gap.at, { top: count, bottom: 0 });
    return;
  }
  const shown = expanded.get(gap.at) ?? { top: 0, bottom: 0 };
  shown[action] += Math.min(CONTEXT_STEP, count - shown.top - shown.bottom);
  expanded.set(gap.at, shown);
}

export function displayContext(patch, gaps, expanded, contents) {
  const controls = [];
  const lines = expanded.size ? [] : patch;
  function appendContext(gap, start, end) {
    for (let i = start; i < end; i++) {
      lines.push({
        kind: " ",
        text: contents[gap.new - 1 + i],
        old: gap.old + i,
        new: gap.new + i,
        contextOnly: true,
      });
    }
  }
  let cursor = 0;
  for (const gap of gaps) {
    const count = gapLength(gap, contents);
    if (count === 0) continue;
    if (lines !== patch) while (cursor < gap.at) lines.push(patch[cursor++]);
    const shown = expanded.get(gap.at);
    const top = shown?.top ?? 0,
      bottom = shown?.bottom ?? 0;
    const remaining = count === null ? null : count - top - bottom;
    const open = remaining === 0;
    const start = lines === patch ? gap.at : lines.length;
    controls.push({
      gap,
      count,
      remaining,
      open,
      before: start + (open ? 0 : top),
    });
    if (shown) {
      appendContext(gap, 0, top);
      appendContext(gap, count - bottom, count);
    }
  }
  if (lines !== patch)
    while (cursor < patch.length) lines.push(patch[cursor++]);
  return { lines, controls };
}
