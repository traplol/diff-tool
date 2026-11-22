# Review latency results

All three experiments are complete. The integrated app took 353.3 ms for the measured review workflow, down from 397.0 ms in the fresh confirmation baseline. The single-file launcher includes both accepted changes.

| Operation | Original median | Integrated median |
| --- | ---: | ---: |
| Follow 160 comments after staging | 42.49 ms | 42.52 ms |
| Display the annotated page in Unified and Split | 311.95 ms | 277.30 ms |
| Save and refresh a selected inline comment | 44.54 ms | 35.44 ms |
| Full workflow, median of per-run totals | 397.01 ms | 353.30 ms |
| Compact diff with no comments, measured separately | 34.93 ms | 34.97 ms |

## Experiments

1. **Discarded shared indexing of patch lines.** Tracking improved from 42.69 to 14.69 ms. The edit median rose from 42.67 to 50.13 ms and exceeded the experiment's guardrail.
2. **Kept batched Tk writes.** Each pane now inserts text in one call and applies highlighting in groups. The candidate reduced total latency by 5.0%.
3. **Kept indexed comment ranges.** Rendering and refresh use sorted range boundaries to decide which rows need markers. This reduced the candidate's total latency by a further 8.1%.

The final 11.0% improvement compares fresh measurements of the original and integrated sources. The original and integrated runs passed the same 78-test Linux suite with one native NTFS skip. Their text, tag ranges, comment locations, selections, and Markdown matched. Twelve additional rendering checks covered overlapping ranges, Unicode, split padding, wide gutters, and newline markers.

The integrated suite also passed at 1280 × 720, 1920 × 1080, 2560 × 1440, and 3840 × 2160. All performance figures above come from the 1080p desktop.

## Reproduce or resume

The original source snapshot is in `build/autoresearch/review-latency/baseline`, with manifest `b4fb0e7fc9d02edb938a9dd91f7ffa63417df0ae18c528715276fcade531d9ca`. The integrated source is in the checkout at manifest `3a9f256e15432220e11df220897a5a7bcd173483a74d021f99e127451b82cfc5`. The scorer hashes production module contents because the checkout had no commits.

The raw samples, regression logs, and verdicts for the final comparison are under `build/autoresearch/review-latency/runs/confirm-original` and `confirm-integrated`. Their contract is `bd698ef81508b725bfc0d11a2cd5aa65861fa95043f810ed9a35afed43d83916`. The original experimental series used the same workload and oracle. Formatting and a narrower exception handler in the scoring driver account for its earlier contract ID. The previous driver is in `build/autoresearch/review-latency/score-series-1.py`.

The campaign has no pending candidates. To start another series after a source or environment change, use the charter's command on that source with a fresh output directory. [Scoring contract](charter.md) · [Decision log](results.jsonl)
