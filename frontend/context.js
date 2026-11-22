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

export function displayContext(patch, gaps, expanded, contents) {
  const controls = [];
  const lines = expanded.size ? [] : patch;
  let cursor = 0;
  for (const gap of gaps) {
    const count = gapLength(gap, contents);
    if (count === 0) continue;
    if (lines !== patch) while (cursor < gap.at) lines.push(patch[cursor++]);
    const open = expanded.has(gap.at);
    controls.push({
      gap,
      count,
      open,
      before: lines === patch ? gap.at : lines.length,
    });
    if (open) {
      for (let i = 0; i < count; i++) {
        lines.push({
          kind: " ",
          text: contents[gap.new - 1 + i],
          old: gap.old + i,
          new: gap.new + i,
          contextOnly: true,
        });
      }
    }
  }
  if (lines !== patch)
    while (cursor < patch.length) lines.push(patch[cursor++]);
  return { lines, controls };
}
