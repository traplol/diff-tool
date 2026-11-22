# Rust layout campaign

The packaged Rust app met the target in two independent runs. It won **20 of 20 medians** on each. The largest Rust/Python ratio was 0.790 in the first run and 0.731 in the confirmation. The starting pane-reuse release won 5 on the same probes. [Baseline](releases/v2-baseline/verdict.json) · [Release](releases/release-02/verdict.json) · [Confirmation](releases/release-02-confirm/verdict.json)

The source manifest has SHA-256 `d4e3aaed539d3099d9b00d0f4a8a3d7bdc00ab9ca6d5cdee4e5bfa2428af204c` and the timed Linux executable has SHA-256 `d0892b279f70886429c144baff4e4cacef53c3b33ba6808e25c79c74198f45d1`. Both timed displays used Linux X11. That build forced software rendering and flushed GTK paint on idle. The current Linux app requests hardware acceleration by default and lets GTK schedule paints. [Source manifest](releases/release-02/source.sha256) · [CPU and historical desktop timings](../../benchmarks/large-diffs.md)

The new renderer keeps both CodeMirror layouts for the active file. The earlier readiness probe counted every editor in the document. This series identifies the front layout by hit testing and checks that background editors are inert. It preserves the mouse-to-stable-pixels clock, Python archive, nine measured pairs, review fixtures and semantic checks. The original executable was remeasured before promotion. [Visible-pane probe](../../benchmarks/v2/active_surface.js) · [Pinned extension](../../benchmarks/v2/pins.sha256) · [Reproduction commands](../../../README.md#compare-large-diff-performance)

The packaged GUI passed layout checks from 720p through 4K. Its workflow tests covered stack and working-tree review, suggestions, inline comments, editing, resolution and Markdown export. A separate regression widened the sidebar by 220 pixels with a wrapping comment above the scroll anchor, then checked rapid switches, selection, keyboard focus and the edited comment across layouts. [Resize regression](../../check_diff_resize.py)

## Intermediate release

The first retained release won **14 of 20** published medians, up from 5. It transfers compact Git patches to the editor, uses WebKit's software backing store on X11, and draws the inline disclosure triangle with CSS. All file opens, first switches to Split and full four-action sequences beat Python in all nine measured pairs on both displays. [Release verdict](releases/release-01-arrow/verdict.json)

Six warm-switch medians trailed Python in Release 01. On Radeon, repeat Split takes an extra 0.8 ms on the 4k diff and 0.3 ms on the 40k diff. On Xvfb, returning to Unified takes an extra 6.3–6.6 ms and repeat Split takes an extra 4.3–4.4 ms. The worst Rust/Python ratio fell from 4.09 to 1.41. The target was below 1 for all twenty metrics on fresh paired runs. [Radeon samples](releases/release-01-arrow/radeon/samples.jsonl) · [Xvfb samples](releases/release-01-arrow/xvfb/samples.jsonl)

That candidate was `build/rust-race/candidates/arrow`, with source manifest SHA-256 `cf4d48dea36bdc1d7fd98a9874c6146ba2e0ff352c852a7a612f02c10782ce9e`. Its tested release binary is `build/rust-race/arrow-linux`, SHA-256 `960db2608b4b47c09f7b7bb62192bd22c3800a0b2a9f9b2454933b798c5a34dd`. It passed the native desktop smoke test, including 720p to 4K layout checks.

## Starting point

The starting source on the unborn `trunk` branch is preserved under `build/rust-race/control`. Its source manifest has SHA-256 `984b7400a8c19e002a084d4a17b4eafd3cede80b79c4c80652134ade232e3be5`. The verified pane-reuse release has SHA-256 `94fa21213db987a786d771388a27152fcdcb331eee12e3d260ce37e7100099e8`.

The two successful baseline runs are `build/benchmarks/pane-reuse-radeon` and `build/benchmarks/pane-reuse-xvfb`. Their report, binary, source snapshot and negative controls are in `build/rust-race/control`. The scorer rejected an incomplete pair, wrong visible state, wrong executable, missing final summary and duplicated display data. Contract SHA-256 is `37a59da4d55d2cecefb1412a3d9c9d9be2234f678e6afae77ab2f441d6505b0a`. [Scoring contract](charter.md) · [Pinned inputs](pins.sha256) · [Decision log](results.jsonl)

## Pilot results

Five candidate builds and two diagnostic runs have completed. Each pilot used one warmup and three measured pairs per fixture. All reproduced the expected selections, diff text, scroll positions, comment cards and Python output fingerprints. All five candidate builds passed their JavaScript and Rust tests.

On Xvfb, compact patch transport alone reduced the 40k open to 106.9 ms, versus 132.2 ms for the paired Python control. Selecting the software backing store alone reduced return switches to 13.7–17.4 ms. Combining both changes with scroll restoration and flushing GTK damage on idle won eight of ten Xvfb medians. The remaining losses were the repeat switch to Split, at 17.0 vs 11.6 ms on the 4k diff and 15.4 vs 11.6 ms on the 40k diff. [Pilot samples](../../../build/rust-race/runs/converge/joinedflush/xvfb/samples.jsonl)

Subsequent pilots tested paint containment, parking inactive panes, read-only editor surfaces, and keeping stacked pane layers or textures in memory. None beat the paired Python repeat-Split medians on both fixtures. The resident-layout experiments used a diagnostic probe that selected the visible panes. Short-run measurements and source locations are in the decision log.

The seventh pilot round combined retained layers, GTK damage flushing and an unchanged-selection-label check. All ten Xvfb medians beat Python over three pairs, including repeat Split at 9.5 ms vs 12.8 ms on the 4k diff and 8.4 ms vs 11.7 ms on the 40k diff. This candidate used the diagnostic visible-pane probe. Release 01 was the formal result when those pilots finished. A separate native-surface candidate failed during its first Rust file open because the sampled diff pixels did not change. The first damage-flush control launched the wrong binary. Its corrected run measured the intended rendering path.

Use `python3 build/rust-race/pilot.py RUN --binary EXECUTABLE` for short-run diagnostics.
