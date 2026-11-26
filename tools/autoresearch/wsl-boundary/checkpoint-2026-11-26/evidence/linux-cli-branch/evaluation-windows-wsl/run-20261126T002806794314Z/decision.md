The primary a4 series is valid and passes its frozen one-cell qualification. Keep the candidate for further verification; do not promote from this cell alone.

All six serial fresh processes and318 samples pass canonical content/comment correctness, startup readiness, exact source/binary identities, both-fixture guards and recorded app/child cleanup. The private master received exit acknowledgement0 and exited255; its socket is absent and host port19223 was recorded free. Exact master/controller identities are absent now. No VM inventory or new port check ran during this analysis.

Open A: 1354.2 / 714.3 / 730.6 ms; B: 714.8 / 665.3 / 696.5 ms. A1 remains an outlier. Openmedian 730.6→696.5ms improves4.67%, below10%. Process2/3 pair improvements are -6.86% and-4.67%. These are fresh-process observations, not OS-cold.

Worst p95 1354.2→714.8ms passes the10% primary gate, but is dominated by A1 Open. Independent branch-group worst p95 227.3→179.9ms improves20.85%, so corroboration passes through branch interactions rather than Openmedian. Every final20 action p95/max and freshOpenmedian/p95/max10% guard passes. There are no failed guards to waive.

Canonical nearest-rank p50/p95/max below use all3 Opens or the final20 action samples including first use. Strict repeated19, all-series26 and every first-use value remain in summary.json; no sample is removed.

| Action | A p50/p95/max ms | B p50/p95/max ms | p95 change | max change |
|---|---:|---:|---:|---:|
| open | 730.6/1354.2/1354.2 | 696.5/714.8/714.8 | -47.22% | -47.22% |
| branch_first | 183.3/197.4/198.6 | 150.4/161.9/164.5 | -17.98% | -17.17% |
| branch_final | 134.2/148.5/169.0 | 105.9/118.1/123.1 | -20.47% | -27.16% |
| working_tree | 203.0/230.5/232.4 | 191.2/207.0/217.9 | -10.20% | -6.24% |
| stack | 126.8/139.4/157.8 | 109.9/112.0/121.7 | -19.66% | -22.88% |
| comment_branch | 198.0/227.3/228.5 | 151.4/179.9/180.6 | -20.85% | -20.96% |
| comment_worktree | 212.7/228.7/230.2 | 211.2/214.2/214.5 | -6.34% | -6.82% |

All B final20 action p95/max values are below250ms. Fresh Open remains665–715ms and fails the goal. The other matrix cells, cold scenarios and final delivered-source acceptance remain incomplete.

First use by fresh process1/2/3:

| Action | A first-use ms | B first-use ms |
|---|---:|---:|
| open | 1354.2 / 714.3 / 730.6 | 714.8 / 665.3 / 696.5 |
| branch_first | 313.6 / 129.1 / 129.1 | 113.8 / 114.9 / 113.8 |
| branch_final | 181.8 / 140.3 / 125.7 | 137.0 / 121.6 / 110.0 |
| working_tree | 245.3 / 219.0 / 203.3 | 221.1 / 188.8 / 204.5 |
| stack | 164.5 / 126.4 / 124.3 | 117.6 / 108.8 / 109.7 |
| comment_branch | 242.1 / 213.3 / 197.9 | 165.3 / 165.7 / 167.5 |
| comment_worktree | 259.2 / 198.4 / 213.2 | 212.5 / 228.5 / 196.6 |

Foreground IPC coverage is the union of completed intervals. Remainder includes UI handling, rendering, frames, scheduling and unrecorded work; it is not paint-only. Figures use the same sample scope as the first table.

| Action | A foreground p50/p95/max | B foreground p50/p95/max | A remainder p50/p95/max | B remainder p50/p95/max |
|---|---:|---:|---:|---:|
| open | 655.6/1269.5/1269.5 | 621.6/653.9/653.9 | 75.0/84.7/84.7 | 65.1/74.9/74.9 |
| branch_first | 143.5/153.3/158.2 | 103.6/115.3/116.2 | 40.8/47.7/48.4 | 45.7/48.3/48.9 |
| branch_final | 87.9/100.0/132.8 | 68.5/72.1/74.8 | 42.2/48.5/49.4 | 37.8/48.5/51.0 |
| working_tree | 157.6/188.9/193.4 | 153.5/165.2/170.8 | 41.4/46.7/47.1 | 40.1/47.1/47.1 |
| stack | 86.4/94.5/109.8 | 69.3/71.6/77.0 | 42.6/48.0/49.5 | 40.2/45.4/45.6 |
| comment_branch | 158.4/178.5/180.6 | 114.5/131.3/135.4 | 40.7/49.8/50.8 | 40.5/49.5/50.6 |
| comment_worktree | 167.8/181.6/182.4 | 166.9/176.2/176.6 | 40.8/47.2/47.8 | 39.1/46.4/47.3 |

ipc-samples.json retains all318 raw samples and exact relative foreground/background intervals, pending calls, unions and remainders. summary.json retains p95/max/near-p50 rows for every action and source process. No failed-guard rows exist in this run. Observed WT improvements are not isolated causal evidence for a branch-only edit.

Decision: retain a4 as a qualified primary candidate for the remaining matrix and integration checks. No promotion, retry, VM action, tests or builds occurred during this host analysis. The250ms full goal remains unmet.
