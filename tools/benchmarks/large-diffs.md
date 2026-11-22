# Large-diff benchmarks

## CPU cost of preparing a diff

On the 40,000-line mixed fixture, the Rust encoder took about 1.55 ms. The port's JavaScript decoder then took 4.14–6.17 ms to build selectable lines. Python built the same lines in 29.40–29.99 ms. The port built the split rows faster on this fixture. On the 4,000-line addition, the split results changed order between runs.

Each column shows the median elapsed milliseconds from one fresh headless run. Each stage had five warmups and 31 measured calls. The measurements ran on native Linux on a Ryzen 9 7900X. JavaScript ran in Node 22.18.0 with V8. The Linux desktop app runs the same functions in WebKit's JavaScriptCore. [First run and source hashes](results/cpu-layout.json) · [Confirmation](results/cpu-layout-confirm.json)

| In-memory operation | 4k run 1 | 4k run 2 | 40k run 1 | 40k run 2 |
| --- | ---: | ---: | ---: | ---: |
| Rust port · encode patch for the frontend (Rust) | 0.122 | 0.122 | 1.558 | 1.550 |
| Rust port · decode patch into selectable lines (JS) | 0.140 | 0.213 | 6.166 | 4.141 |
| Python · parse patch into selectable lines | 1.936 | 1.908 | 29.992 | 29.396 |
| Rust port · build unified rows (JS) | 0.025 | 0.027 | 0.508 | 0.491 |
| Python · build unified rows | 0.042 | 0.044 | 0.621 | 0.693 |
| Rust port · build split rows (JS) | 0.187 | 0.202 | 2.431 | 2.411 |
| Python · build split rows | 0.193 | 0.168 | 4.849 | 4.598 |

The runner starts from the same Git patch bytes for each implementation. It checks every line's text, kind, hunk and old/new line numbers, then compares every source-line index and empty cell in both layouts. The 40k fixture produces 50,001 unified rows and 40,001 split rows. Git, file reads, IPC, editor documents, comment placement and drawing are outside these timings. Both apps reuse the open file's rows when returning to an existing layout. WSLg click-to-visible latency was not measured. [Run the CPU comparison](../../README.md#compare-large-diff-performance)

## Historical desktop timings with an X11 presentation override

The packaged Rust app beat Python on 20 of 20 median timings and 20 of 20 on a fresh confirmation. The earlier Rust release won 5 of 20 under the same visible-pane checks. Each run used one discarded warmup and nine measured pairs per fixture and display. Windows and native Wayland were outside the timing runs. [Baseline](../autoresearch/rust-layout/releases/v2-baseline/verdict.json) · [First run](../autoresearch/rust-layout/releases/release-02/verdict.json) · [Confirmation](../autoresearch/rust-layout/releases/release-02-confirm/verdict.json)

Each cell shows Rust / Python median milliseconds from the confirmation. The sequence is the median of the four timings summed within each pair.

| Action | Radeon 4k | Radeon 40k | Xvfb 4k | Xvfb 40k |
| --- | ---: | ---: | ---: | ---: |
| Open in Unified | 48.2 / 104.2 | 85.1 / 137.8 | 43.9 / 96.4 | 85.3 / 134.9 |
| First Split | 33.4 / 87.9 | 36.9 / 73.2 | 33.2 / 71.2 | 38.8 / 63.8 |
| Return to Unified | 13.2 / 22.8 | 10.3 / 19.9 | 11.8 / 16.6 | 9.5 / 17.0 |
| Repeat Split | 12.0 / 21.3 | 11.9 / 16.2 | 9.5 / 14.1 | 9.5 / 13.1 |
| Four-action sequence | 109.0 / 246.3 | 149.6 / 243.1 | 98.1 / 199.7 | 141.8 / 230.6 |

Rust transfers the patch body once with the line numbers that start each hunk. The editor builds each layout on first use and keeps both live for the selected file. Only the front layout accepts pointer and keyboard input. The timed Linux build also forced WebKit to use software rendering on X11 and flushed pending GTK paint on idle. The current app leaves both decisions to the graphics libraries. [Git patch transport](../../src-tauri/src/git.rs) · [Layout switch](../../frontend/editor.js) · [Timed source manifest](../autoresearch/rust-layout/releases/release-02/source.sha256)

The visible-pane probe uses hit testing to identify the editor the user can interact with. The same external process still measures a real mouse click through the final stable diff pixels. Both releases used the identical Python archive, Git fixtures, selection and comment checks. Native smoke tests covered 720p, 1080p, 1440p, and 4K, plus an expanded comment that wrapped to a new height after resizing the sidebar. [Run the comparison](../../README.md#compare-large-diff-performance) · [Scoring contract and decisions](../autoresearch/rust-layout/state.md)

Python reference timings varied between sessions, particularly on the Radeon. For 20 of 20 metrics, the slower of the two final Rust medians still beat the fastest Python median observed across the baseline and both release runs. Raw samples include the pixel sampling interval for every action. [Baseline samples](../autoresearch/rust-layout/releases/v2-baseline/radeon/samples.jsonl) · [First Radeon samples](../autoresearch/rust-layout/releases/release-02/radeon/samples.jsonl) · [Confirmation samples](../autoresearch/rust-layout/releases/release-02-confirm/radeon/samples.jsonl)

## Historical WebKit acceleration experiment on the Radeon

Both rendering paths ran on the same 60 Hz RX 7900 XT display. The software column used the earlier build with the X11 override. The accelerated build used identical frontend assets and changed one WebKit setting from `Never` to `Always`. Only the software build used the immediate paint hook. WebKit’s AMD graphics-engine counters increased in both accelerated warmups.

Median click-to-stable-pixel time in milliseconds, from nine measured pairs per fixture after one discarded warmup. The runner alternated which mode went first and checked patch text, selection, scroll position and comment state.

| Action | 4k software | 4k accelerated | 40k software | 40k accelerated |
| --- | ---: | ---: | ---: | ---: |
| Open in Unified | 45.3 | 73.1 | 83.7 | 116.7 |
| First Split | 34.0 | 49.8 | 36.7 | 43.9 |
| Return to Unified | 16.8 | 37.0 | 11.4 | 47.5 |
| Repeat Split | 13.2 | 47.2 | 15.0 | 46.2 |

The test measures opening and layout switching on WebKitGTK/X11. Windows and native Wayland use their platform defaults. [Summary and GPU counters](results/radeon-renderer-comparison.json) · [Paired samples](results/radeon-renderer-comparison.jsonl)

## Earlier release with reattached CodeMirror panes

On the 40k mixed diff, reusing a layout cut the time from the browser click handler to the panes being mounted from 6–9 ms to 1 ms. Visible switches still took about 50 ms on the Radeon. Python returned to Unified in 19 ms and to Split in 16 ms.

Rust creates each layout on first use and keeps both for the current file. Switching back reattaches the existing editors, carries over the current selection and scroll anchor, and refreshes comments that changed while the layout was inactive. Leaving the file releases both layouts. [Editor implementation](../../frontend/editor.js)

### Radeon RX 7900 XT

Median milliseconds from click to stable sampled pixels. Both Rust releases ran in the same session, each against the same Python package. The Python columns below come from the run paired with the updated release. Each run used one warmup and nine measured pairs per fixture.

| Action | 4k Rust before | 4k Rust reuse | 4k Python | 40k Rust before | 40k Rust reuse | 40k Python |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Open in Unified | 88.3 | 88.2 | 95.5 | 179.5 | 179.2 | 126.5 |
| First switch to Split | 42.8 | 42.1 | 73.2 | 39.1 | 45.9 | 60.6 |
| Return to Unified | 41.7 | 42.7 | 19.1 | 46.7 | 49.7 | 19.3 |
| Repeat switch to Split | 48.9 | 48.5 | 15.6 | 49.1 | 49.3 | 16.1 |
| Four-action sequence | 221.8 | 221.5 | 204.0 | 314.6 | 321.7 | 224.0 |

Rust won the first switch to Split in all nine pairs on both fixtures. Python won every return switch and every complete sequence. The two Rust runs had overlapping ranges on the first 40k switch (36.6–48.7 ms before and 39.8–50.0 ms after). The median sampling interval at the final pixel change was 2.8 ms in the updated run. [Before samples](results/before-reuse-radeon.jsonl) · [Pane-reuse samples](results/pane-reuse-radeon.jsonl)

The browser timing starts when WebKit dispatches the click and ends when the active editors appear in the document. On the 4k diff, the two return switches fell from 4 and 5 ms to 2 and 1 ms by that measure. The external pixel timing also includes input delivery and presentation. The benchmark cannot attribute the remaining latency to a particular stage.

The updated Linux executable has SHA-256 `94fa21213db987a786d771388a27152fcdcb331eee12e3d260ce37e7100099e8`. The original executable and Python archive hashes appear below. The same click and pixel probes measured both releases.

### Linux virtual framebuffer

Median click-to-visible milliseconds on Xvfb, with the same workload and number of samples.

| Action | 4k Rust before | 4k Rust reuse | 4k Python | 40k Rust before | 40k Rust reuse | 40k Python |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Open in Unified | 92.4 | 93.4 | 62.5 | 186.6 | 185.3 | 133.0 |
| First switch to Split | 45.4 | 43.5 | 66.8 | 44.2 | 50.5 | 58.1 |
| Return to Unified | 42.9 | 41.5 | 15.3 | 43.9 | 43.5 | 16.3 |
| Repeat switch to Split | 49.0 | 47.2 | 12.1 | 48.2 | 48.0 | 11.7 |
| Four-action sequence | 229.8 | 225.3 | 159.6 | 322.5 | 322.9 | 221.7 |

Both cached switches landed within 2 ms of the original Rust medians on Xvfb. The median sampling interval at the final pixel change was 2.9 ms. [Before samples](results/before-reuse-xvfb.jsonl) · [Pane-reuse samples](results/pane-reuse-xvfb.jsonl)

## Before pane reuse on the Radeon RX 7900 XT

Rust opened the annotated 4,000-line diff 9 ms sooner than Python and the mixed 40,000-line diff 42 ms later. Rust won the first switch to Split on both fixtures. Python won both return switches. The ordering for each action held in all nine paired observations for that fixture.

Median milliseconds from a real mouse click to stable sampled diff pixels on a 60 Hz, GPU-backed Xwayland display.

| Action | Python · annotated 4k | Rust · annotated 4k | Python · mixed 40k | Rust · mixed 40k |
| --- | ---: | ---: | ---: | ---: |
| Open file in Unified | 97.4 | 88.7 | 136.8 | 178.8 |
| First switch to Split | 72.0 | 43.0 | 61.0 | 49.0 |
| Return to Unified | 18.5 | 41.8 | 19.2 | 48.5 |
| Repeat switch to Split | 15.8 | 48.3 | 15.6 | 49.2 |
| Four-action sequence | 204.1 | 222.1 | 229.9 | 324.8 |

Gamescope hosted a private compositor with its headless backend. The X11 client reported hardware acceleration on the RX 7900 XT. Kernel graphics-engine counters advanced for WebKit processes attached to the Radeon render device during the run. Each app had a 1380 × 840 window. The median uncertainty interval at the final pixel transition was 2.7 ms, and the largest was 6.2 ms. [Raw paired samples](results/linux-radeon.jsonl)

In this baseline, Python retained the alternate diff view for the active file. Rust destroyed the CodeMirror panes and built the new layout on each toggle. The 40k open path passed 50,001 patch line records from Rust to the webview. File-open latency includes Git, transport, document construction and rendering. [Python layout switch](../../branchline/app.py) · [Rust patch command](../../src-tauri/src/service.rs)

## Before pane reuse on the Linux virtual framebuffer

Median milliseconds from a mouse click to the final sampled diff pixels, with a 1380 × 840 window on a 1920 × 1080 Xvfb desktop. Lower values are faster. For each file, the same implementation won each individual operation in all nine measured pairs.

| Action | Python · annotated 4k | Rust · annotated 4k | Python · mixed 40k | Rust · mixed 40k |
| --- | ---: | ---: | ---: | ---: |
| Open file in Unified | 93.4 | 98.2 | 133.5 | 185.3 |
| First switch to Split | 68.2 | 46.4 | 58.0 | 46.2 |
| Return to Unified | 16.2 | 41.0 | 16.5 | 43.0 |
| Repeat switch to Split | 11.9 | 48.8 | 11.8 | 48.0 |
| Four-action sequence | 190.3 | 232.0 | 219.8 | 332.8 |

The four-action sequence is the median of the four timings summed within each repetition. The individual medians can add up to a different number. The median uncertainty interval at the final pixel transition was 3.0 ms across the 144 measured actions, and the largest was 7.0 ms. [Raw paired samples](results/linux-xvfb.jsonl)

## Workload and measurement

- **Annotated additions.** A 4,000-line added Python file has 160 two-line comments. The test selects new lines 10–11 and scrolls to line 3 before the first switch. In Split it selects lines 13–14 and scrolls to line 5 before switching back.
- **Mixed changes.** Every fourth line in a 40,000-line Python file changes, giving 10,000 removals, 10,000 additions and 50,001 unified patch rows including the hunk header. The test selects new line 16. This fixture has no comments.
- Each sample starts in a fresh app window with the same small file selected in an already loaded branch comparison. Both implementations read the same Git checkout and SQLite review database. File opening includes the application’s normal Git patch request. Application startup, initial stack discovery and comment tracking during comparison loading precede the timer. Operating-system caches stay warm.
- Each fixture has one discarded warmup pair and nine measured pairs. The apps run serially and alternate which build runs first. Each iteration checks the resulting layout, patch content, and selection. The annotated case also checks comment rendering, the scroll anchor, and split-pane alignment. The Python output matches the earlier campaign’s correctness fingerprints.
- A separate process injects mouse press and release with XTEST and samples four six-pixel-high strips across the editor, spanning both pane positions. It records the first sample of the final stable pixel state. The harness waits for the expected UI state and for a further 120 ms of stable pixels to identify that final state. That settling period is outside the reported latency. These are visible-content samples from the display server. A physical monitor and input-device latency are outside the measurement.
- The earlier Python campaign timed Tk’s internal widget update calls. This comparison retimed Python and the Rust release with the same click and pixel boundary. Figures from the two campaigns use different timing boundaries. [Earlier Python workload](../autoresearch/diff-layout/state.md)

The test host ran Ubuntu 26.04.1, Linux 7.0.0-43-generic, an AMD Ryzen 9 7900X, Git 2.53.0, Python 3.14.4, Tk 8.6.17, and WebKitGTK 2.52.6. Rust used the optimized Linux Branchline 0.2.0 binary. The harness verified the imported Python modules were byte-identical to the shipped Python archive.

| Build | SHA-256 |
| --- | --- |
| Rust Linux executable | `2e475d97e72f7173ab2298adae7941f30fe3d1c090468ac14877956996c6aced` |
| Python archive | `e7545f67c6460a923cb5cc716095f814afaad90b433422ceb6b272836fec4193` |

## Reproduce

The commands below reproduce the original benchmark for releases that attach only the active panes to the diff. For the current release, use the visible-pane runner. [Current benchmark commands](../../README.md#compare-large-diff-performance)

Run the Linux build steps in the project directory. The comparison needs Git, Tk, Xvfb, xauth, xdpyinfo, D-Bus, libX11, libXtst and WebKitWebDriver. Pass a fresh output directory. The default is nine measured pairs per fixture.

```sh
python3 tools/benchmarks/restore_python_reference.py
npm ci
npm run tauri -- build --no-bundle
```

```sh
xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' \
  dbus-run-session -- python3 tools/benchmarks/compare_layouts.py \
  build/benchmarks/repeat-01 --binary src-tauri/target/release/branchline \
  --driver /path/to/WebKitWebDriver
```

For the hardware-accelerated run, install Gamescope, Xwayland, xwd, and glxinfo, and use the wrapper below. It creates a private display and records the renderer information on standard output.

```sh
python3 tools/benchmarks/gpu_display.py build/benchmarks/radeon-repeat-01 \
  --binary src-tauri/target/release/branchline --driver /path/to/WebKitWebDriver
```

The runner writes individual measurements, per-phase medians and ranges, paired differences, bundle hashes and environment information in the output directory. Every repository and review used by the benchmark lives in that directory.
