# Opening large diffs and switching layouts

Optimize latency from selecting a large committed file until its annotated diff is drawn and usable. Measure the first Unified → Split switch, the return to Unified, and a repeat switch to Split separately. The primary metric is the median of their per-iteration sum, including file open. The compact file is a separate guardrail.

The fixed fixture has a 4,000-line Python file, 160 review comments and eight visible inline cards on the first page. Each iteration starts from a small file in a fresh app. The large file opens through the file tree, the Git patch worker, and Tk's normal callback. Timers include completed Tk geometry and drawing. State checks outside the timed regions cover text, tag ranges, comment cards, selection, scroll restoration, and split alignment. This campaign has a different measurement boundary from the preceding review-latency campaign.

## Evaluation

Run from the repository root with Git, Python with Tk, Xvfb, and SSH keygen. The scorer takes the source directory, a fresh output directory, and a label.

```sh
scratch=build/autoresearch/diff-layout
xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' \
  python3 tools/autoresearch/diff-layout/score.py "$scratch/baseline" "$scratch/runs/repeat-01" baseline
```

Run one warmup and seven measurements serially. Every run must compile, pass the existing Linux desktop suite with its one Windows-only skip, complete every phase, and match the baseline output oracle. Save raw samples, test logs and a machine-readable verdict in the fresh run directory. Record the source and contract hashes. The canonical fixture and tests are outside the candidate snapshots.

Keep a candidate if the summed median falls by at least 3% and by more than twice the larger median absolute deviation. Reject a slowdown on any individual large-file phase greater than both 15% and 3 ms. For the compact diff, use 20% and 2 ms. For a close result, allow one paired repeat with the same gates. Allow one retry for a diagnosed infrastructure failure. Confirm the final result by evaluating the original and integrated source again serially.

Stop after three candidates. The starting checkout has no commits. Its original nine-module source snapshot and each candidate are preserved under `build/autoresearch/diff-layout`. Only the application source is editable in a candidate. The [decision log](results.jsonl) and [campaign state](state.md) identify the accepted source and evidence. The first Linux measurements use a Ryzen 9 7900X and a 1920 × 1080 virtual desktop at 96 DPI.
