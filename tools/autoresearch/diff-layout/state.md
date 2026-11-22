# Large diff opening and layout switches

The integrated app reduced the median time for opening a file and switching layouts three times from **571.5 ms to 150.9 ms** on the annotated benchmark. The 4,000-line committed file had 160 saved comments. Every measured action completed its paint and passed the viewport, selection, and inline-card checks.

| Action | Starting build | Integrated build |
| --- | ---: | ---: |
| Select the file and open its unified diff | 154.5 ms | 84.4 ms |
| First switch to Split | 141.4 ms | 58.5 ms |
| Return to Unified | 135.0 ms | 5.8 ms |
| Switch back to Split | 141.1 ms | 2.1 ms |
| Small-file switch, separate control | 29.6 ms | 10.8 ms |

Each value is the median of seven measurements following one warmup. The starting and integrated binaries used the same Linux host and 1080p virtual display. In a fresh run of the previous campaign's exact combined draw and first-switch workload, its render phase fell from 281.3 to 124.9 ms. That workload had measured 277.3 ms at the end of the previous campaign.

## Three experiments

1. **Kept cached button measurements.** The Tk profile attributed about 70 ms per layout to repeatedly measuring button text and line heights. The cache holds up to 256 measurements per interpreter and keys them by font, title, and display scale. Each button retains its own mutable font. This cut the four-action sequence from 555.9 to 289.9 ms in the initial comparison.
2. **Discarded shared fonts for static labels.** The candidate missed the performance threshold and produced a highly variable result across repetitions.
3. **Kept one alternate layout for the active file.** Returning to a layout reuses the editor widgets and restores the current selection and scroll position. The app checks comment contents and fold state before reuse, synchronizes Viewed, and releases both layouts on ordinary file or comparison replacement. When both layouts have been opened, it retains their current rendered pages and row mappings for the active file. The candidate took 154.0 ms against its fresh 298.6 ms reference.

## Verification

A second fixture had a 40,000-line tracked file with 10,000 replacements. In three measured repetitions, opening fell from 122.0 to 106.3 ms, the first switch to Split from 72.7 to 49.2 ms, returning to Unified from 54.5 to 6.8 ms, and switching back to Split from 70.6 to 1.8 ms. Both builds produced the same editor content, tags and selection digest.

The packaged launcher passed the 78-test suite at 720p, 1080p, 1440p and 4K with the one native Windows NTFS skip at each resolution. Additional checks exercised comment edits, folds, resolution, Viewed state, rapid switches, resize, second-page selection, and refresh of a changed working file. Font measurements and appearance matched in 55 checks across independent Tk roots and display scales. Native Windows and WSLg timings remain unmeasured.

## Reproduce or resume

All three experiments are complete. The original source snapshot is under `build/autoresearch/diff-layout/baseline`, manifest `3a9f256e15432220e11df220897a5a7bcd173483a74d021f99e127451b82cfc5`. The integrated workspace manifest is `7ca672a9928c8305e777b8afe4a9c37d4b4c4130accd474ee244bfebf873700a`. The simplified alternate-view selection was included in final confirmation and packaging.

The frozen contract is `0bd1c9855194297c856954e7c9ab259a5c9ca565d804eb9da28f00e9b7620839`. Its scorer, workload and oracle are in this directory. Raw samples and logs are under `build/autoresearch/diff-layout/runs`, including `confirm-original` and `confirm-integrated`. To repeat, follow the charter with a fresh run directory. [Methodology](charter.md) · [Decision log](results.jsonl)
