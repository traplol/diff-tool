const paths = {
  branch:
    "M7 7v10m0-3c0-5 10-1 10-7M7 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM17 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z",
  review:
    "M6 7v10m12 0v-5a5 5 0 0 0-5-5h-2m3-3-3 3 3 3M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm12 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z",
  folder:
    "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z",
  file: "M6 3h8l5 5v13H6Zm8 0v6h5",
  files: "M5 4v13h3m-3-8h3m3-5h5l3 3v4h-8Zm0 10h5l3 3v4h-8Z",
  sidebar: "M3 4h18v16H3Zm6 0v16",
  worktree: "M3 5h7l2 2h9v12H3Zm5 8h8m-4-3v6",
  comment: "M4 4h16v12H9l-5 4Z",
  suggest: "m13 6 5 5M5 19l4-1L21 6l-4-4L5 14Zm7 2h9",
  find: "M16 16l5 5M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Z",
  refresh: "M20 11A8 8 0 1 0 18 18m2-13v6h-6",
  export: "M12 15V3m-4 4 4-4 4 4M4 14v6h16v-6",
  edit: "m14 5 5 5M4 20l5-1L21 7l-5-5L4 14Z",
  down: "m6 9 6 6 6-6",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  "expand-up": "M4 4h16M7 16l5-5 5 5m-5-5v10",
  "expand-down": "M4 20h16M7 8l5 5 5-5m-5 5V3",
  expand: "M6 9l6-6 6 6M6 15l6 6 6-6",
  collapse: "m6 3 6 6 6-6M6 21l6-6 6 6",
};

export function icon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const node = document.createElementNS(ns, "svg");
  node.setAttribute("class", "ui-icon");
  node.setAttribute("aria-hidden", "true");
  node.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", paths[name]);
  node.append(path);
  return node;
}
