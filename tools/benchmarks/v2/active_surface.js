// Return the live CodeMirror scrollers that receive pointer input in the diff.
window.reviewSurface = (expected) => {
  const host = document.querySelector("#diff");
  const viewport = host.getBoundingClientRect();
  const visible = [];
  for (const pane of document.querySelectorAll(".bl-diff .cm-scroller")) {
    const rect = pane.getBoundingClientRect();
    const left = Math.max(0, viewport.left, rect.left);
    const top = Math.max(0, viewport.top, rect.top);
    const right = Math.min(innerWidth, viewport.right, rect.right);
    const bottom = Math.min(innerHeight, viewport.bottom, rect.bottom);
    const hits = [];
    if (right > left && bottom > top) {
      for (const x of [0.25, 0.75])
        for (const y of [0.25, 0.75])
          hits.push(pane.contains(document.elementFromPoint(
            left + (right - left) * x, top + (bottom - top) * y,
          )));
    }
    const inactive = pane.closest("[inert], [hidden]");
    if (hits.some(Boolean)) {
      if (!host.contains(pane) || inactive || hits.includes(false) || pane.closest('[aria-hidden="true"]'))
        throw Error("Diff pane is partially obscured or hidden from assistive technology");
      for (let el = pane; el; el = el.parentElement) {
        const css = getComputedStyle(el);
        if (Number(css.opacity) === 0 || css.visibility !== "visible")
          throw Error("Pointer input reaches an invisible diff pane");
      }
      visible.push(pane);
    } else {
      if (!inactive || inactive.contains(document.activeElement))
        throw Error("A background diff editor is still reachable");
      if (!inactive.inert && inactive.getClientRects().length)
        throw Error("Background diff region must be inert or hidden from layout");
    }
  }
  visible.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
  if (expected !== undefined && visible.length !== expected)
    throw Error("Wrong number of interactive diff panes: " + visible.length);
  return visible;
};
