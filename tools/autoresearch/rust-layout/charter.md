# Rust desktop layout latency

Stop when the packaged Rust app beats the fixed Python app on every published large-diff median on the Radeon and Xvfb. Measure open in Unified, first Split, return to Unified, repeat Split and their per-sample sum for both the 4k annotated and 40k mixed fixtures. The worst Rust/Python median ratio is the primary metric. A ratio below 1 on every metric meets the timing target. Record all twenty medians and paired win counts.

Use the existing real mouse and pixel probes, window size, viewport, Git fixtures, Python build and output assertions. Each run has one discarded warmup and nine measured Rust/Python pairs per fixture. The apps run serially in alternating order. Keep Git parsing, selections, scroll anchors, inline comments, export, working-tree and stack behavior, accessibility, and Windows/Linux support. Keep all work needed to open or switch a file within the existing measurement boundary. [Workload and measurement](../../benchmarks/large-diffs.md#workload-and-measurement)

## Evaluate

Run from the repository root. The starting checkout has no commits. Preserve each tested change under `build/rust-race` with a source snapshot or patch against the retained baseline. Build and test the candidate source itself. The campaign keeps its scorer and Python control outside the candidate. On this host, the local SDK paths are under `build/linux-dev/root/usr/lib/x86_64-linux-gnu`.

```sh
run=build/rust-race/runs/example
binary=src-tauri/target/release/branchline
driver=build/linux-dev/root/usr/bin/WebKitWebDriver
sdk="$PWD/build/linux-dev/root/usr/lib/x86_64-linux-gnu"
export PKG_CONFIG_PATH="$sdk/pkgconfig" LIBRARY_PATH="$sdk" CARGO_NET_OFFLINE=true
mkdir -p "$run"
sha256sum -c tools/autoresearch/rust-layout/pins.sha256 &&
npm test &&
cargo test --locked --offline --manifest-path src-tauri/Cargo.toml --features custom-protocol &&
npm run tauri -- build --ci --bundles deb &&
xvfb-run -a -s '-screen 0 3840x2160x24' dbus-run-session -- \
  python3 tools/smoke_native.py --binary "$binary" --driver "$driver" &&
timeout 8m python3 tools/benchmarks/gpu_display.py "$run/radeon" --binary "$binary" &&
timeout 8m xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' dbus-run-session -- \
  python3 tools/benchmarks/compare_layouts.py "$run/xvfb" --binary "$binary" &&
python3 tools/autoresearch/rust-layout/score.py "$run/radeon" "$run/xvfb" \
  --binary "$binary" > "$run/verdict.json"
```

Use fresh run directories. Capture command logs and the exact binary hash. Evaluate one display at a time. The Radeon wrapper verifies hardware acceleration and the private Gamescope display. Check its exit status and keep its renderer log. The canonical timing scripts already refuse an existing measurement directory. An incomplete sample set, changed Python or probe, failed correctness check, mismatched binary or nonzero runner exit invalidates a full run. Shorter runs guide experiments.

## Decisions

Keep an intermediate change if it improves a losing phase by at least 3 ms against the best Rust release, passes the correctness gates and preserves previous wins. Investigate regressions exceeding both 3 ms and 10%. Repeat a comparison when the difference lies within its sampling uncertainty or a regression could reflect display scheduling. Confirm an all-metric win against a fresh Python run on both displays. Use browser mount timings for diagnosis. Retain the binary or patch and raw timing evidence for each decision. [Decision log](results.jsonl) · [Current state](state.md)
