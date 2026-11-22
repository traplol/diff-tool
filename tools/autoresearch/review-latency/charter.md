# Review latency on a heavily annotated diff

Measure the time to follow saved comments after staging, display the annotated diff in Unified and Split, and save an edit to an inline comment. The primary metric is the median of the **sum** of these three completed operations in milliseconds. Lower is better. The small, uncommented diff is a separate guardrail.

## Reproduce

Run from the project root on Linux with Python, Git, Tk, SSH keygen, and Xvfb. Each invocation needs a fresh output directory. Substitute the candidate directory for `baseline` to evaluate a change.

```sh
control=tools/autoresearch/review-latency
scratch=build/autoresearch/review-latency
xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' \
  python3 "$control/score.py" "$scratch/baseline" "$scratch/runs/repeat-01" baseline
```

The source repository had no commits when the campaign began. The baseline is a copy of all nine production modules, including the working changes. Each experiment starts in a separate directory under `build/autoresearch/review-latency` with the last accepted source. Only production modules may change. The scorer, workload, expected output digest, and existing tests stay in the canonical checkout. Each verdict records independent hashes of the source and the evaluation contract.

## Fixture and checks

The workload reviews a 4,000-line added Python file with 160 saved comments. It creates the comments while the file is untracked, stages it, then uses the real Git, SQLite, and Tk implementations. Eight comments start on the first page. Each iteration starts with the same review contents and a fresh view. The scorer runs one warmup and seven measured iterations on a 1920 × 1080 virtual display at 96 DPI. Layout and idle redraws finish before the clock stops. Fingerprinting runs outside the timed intervals.

The scorer validates all seven samples and checks the baseline digest for text, highlighting, card positions, selected lines, tracked locations, and Markdown. A compact diff without comments measures ordinary rendering. Each scored source must compile and pass the frozen 78-test Linux desktop suite, including its one native NTFS skip. The test and workload processes each have a 120-second timeout. Each run retains its samples, log, and final verdict. A failed gate or incomplete measurement yields an invalid run.

The local runs used an AMD Ryzen 9 7900X, Python 3.14.4, Tcl/Tk 8.6.17, and Git 2.53.0. The measured window was 1380 × 840. The renderer measurement starts with the patch already loaded and finishes after both layouts have drawn their first page. The edit measurement includes the SQLite write, reloading the comments, and refreshing the selected lines. Markdown generation provides an output check outside the timed interval.

## Decisions

Run three candidate experiments serially. Keep a change if its median beats the current best by at least 3% and by more than twice the larger median absolute deviation of the two runs. For each primary phase, reject a slowdown greater than both 15% and 3 ms. For the compact diff, reject a slowdown greater than both 20% and 2 ms. If results are close, allow one paired repeat against the current best and require both comparisons to qualify. Allow one retry for a diagnosed infrastructure failure.

Confirm the combined result against fresh runs of the original and integrated source, using the same gates, minimum gain, and guardrails. Freeze the baseline output digest before the first candidate. A change to the scorer, workload, oracle, or fixed tests starts a new series. The decision log and state file identify the baseline, promoted source, and raw evidence. Generated fixtures, source snapshots, and test logs stay under the ignored campaign build directory.
