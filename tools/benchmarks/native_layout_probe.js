// Injected by WebDriver into the packaged app. Elapsed times use WebKit's clock.
window.layoutProbe = (() => {
  const $ = (selector) => document.querySelector(selector);
  const panes = () => [...document.querySelectorAll("#diff .cm-scroller")];
  const rows = (pane) => [...pane.querySelectorAll(".cm-line")];
  const frames = async (n = 2) => {
    for (let i = 0; i < n; i++) await new Promise(requestAnimationFrame);
  };

  function line(pane, text) {
    return rows(pane).find((el) => el.textContent.includes(text));
  }

  function topText(pane) {
    const top = pane.getBoundingClientRect().top + 2;
    return (
      rows(pane).find((row) => {
        const bounds = row.getBoundingClientRect();
        return bounds.top <= top && bounds.bottom > top;
      })?.textContent ?? ""
    );
  }

  function check(expected) {
    const editors = panes();
    if (editors.length !== expected.panes)
      throw Error("Wrong number of diff panes.");
    const content = editors.at(-1);
    if (!line(content, expected.marker)) throw Error("Incorrect patch text.");
    if (
      expected.selection &&
      $("#selection").textContent !== expected.selection
    ) {
      throw Error("Selected range changed: " + $("#selection").textContent);
    }
    if (expected.selection && !content.querySelector(".bl-row-picked"))
      throw Error("Selection not drawn.");
    const top = topText(content);
    if (expected.top && !top.includes(expected.top))
      throw Error("Scroll anchor changed: " + top);
    if (
      editors.length === 2 &&
      Math.abs(editors[0].scrollTop - content.scrollTop) > 1
    ) {
      throw Error("Split scroll positions diverged.");
    }
    const card = content.querySelector(".bl-card");
    if (expected.card && !card?.innerText.includes(expected.card))
      throw Error("Inline card missing.");
    if (expected.card && editors.length === 2) {
      const spacer = editors[0].querySelector(".bl-card");
      if (
        !spacer ||
        Math.abs(
          spacer.getBoundingClientRect().top - card.getBoundingClientRect().top,
        ) > 2
      ) {
        throw Error("Inline comment panes misaligned.");
      }
    }
    return {
      selection: $("#selection").textContent,
      top,
      panes: editors.length,
    };
  }

  // Snapshot screen coordinates before starting the external X11 sampler.
  // A real XTest click starts both the display clock and this browser diagnostic.
  let result;
  function arm(selector, expected, [dx, dy]) {
    const control = $(selector);
    if (!control || control.disabled)
      throw Error("Unavailable control: " + selector);
    const container = $("#diff");
    const button = control.getBoundingClientRect();
    const scrollers = panes();
    const pane = scrollers[0].getBoundingClientRect();
    const right = scrollers.at(-1).getBoundingClientRect().right;
    result = new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(Error("Timed out waiting for the timed click/target.")),
        10000,
      );
      control.addEventListener(
        "click",
        async () => {
          const start = performance.now();
          let observer;
          try {
            const ready = await new Promise((mounted) => {
              function checkMounted() {
                const editors = container.querySelectorAll(".cm-content");
                if (
                  editors.length !== expected.panes ||
                  $("#comment").disabled ||
                  $("#filename").textContent !== "policy.py"
                )
                  return;
                if ([...editors].every((editor) => editor.isConnected))
                  mounted(performance.now());
              }
              observer = new MutationObserver(checkMounted);
              observer.observe(container, { childList: true, subtree: true });
            });
            observer.disconnect();
            // Two frames allow CodeMirror's deferred measurement and scroll restoration.
            await frames();
            const frame = performance.now();
            resolve({
              ready_ms: ready - start,
              frame_ms: frame - start,
              state: check(expected),
            });
          } catch (err) {
            reject(err);
          } finally {
            observer?.disconnect();
            clearTimeout(timeout);
          }
        },
        { capture: true, once: true },
      );
    });
    return {
      xy: [
        Math.round(button.left + button.width / 2 + dx),
        Math.round(button.top + button.height / 2 + dy),
      ],
      box: [
        Math.round(pane.left) + dx + 4,
        Math.round(pane.top) + dy + 40,
        Math.floor(right - pane.left) - 20,
        96,
      ],
    };
  }

  async function setTop(text) {
    const pane = panes().at(-1);
    const row = line(pane, text);
    if (!row) throw Error("Missing scroll target: " + text);
    pane.scrollTop +=
      row.getBoundingClientRect().top - pane.getBoundingClientRect().top;
    await frames();
    if (!topText(pane).includes(text))
      throw Error("Could not set scroll anchor: " + topText(pane));
  }

  return {
    arm,
    finish: () => result,
    setTop,
    settle: frames,
    frameControl: async () => {
      const t = performance.now();
      await frames();
      return performance.now() - t;
    },
  };
})();
