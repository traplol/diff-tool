The helper GUI series is valid, but final action regression guards fail. Do not promote from this run.

All six serial fresh processes and 318 samples pass canonical native content/comment correctness, welcome startup readiness, source/executable identities, fixture guards, helper filesystem placement, native PID/cwd/hash and cleanup. The owned native cache was removed; both fixture replicas remain unchanged. GUI, children, helpers and private master/socket were cleaned exactly. Master PID 92513/start 77113449 received exit acknowledgement 0 and exited 255 as expected. Task ports were recorded free; shared host 19225 was untouched. All viewports were 1280×781. No old samples are pooled.

Open observations remain separate: A fresh Opens 3091.1 / 727.6 / 728.2 ms; B initial-install Open 852.9 ms; B later fresh-process cache hits 603.3 / 586.3 ms. The cache-hit pairs improve 17.08% and 19.49%. A1 remains an outlier; one install observation is not an install distribution. None is OS-cold.

Canonical nearest-rank p50/p95/max in milliseconds. Open combines the three observations for completeness; actions use the final twenty including first use. Strict repeated nineteen-sample statistics and all-series maxima remain separately recorded.

| Action | A p50/p95/max | B p50/p95/max | p95 change | max change |
|---|---:|---:|---:|---:|
| open | 728.2/3091.1/3091.1 | 603.3/852.9/852.9 | -72.41% | -72.41% |
| branch_first | 182.9/199.4/215.3 | 183.0/212.6/246.2 | +6.62% | +14.35% |
| branch_final | 134.4/137.2/137.2 | 122.6/137.7/148.1 | +0.36% | +7.94% |
| working_tree | 192.1/207.0/221.7 | 192.6/207.2/215.6 | +0.10% | -2.75% |
| stack | 126.3/141.8/159.0 | 126.4/128.9/137.1 | -9.10% | -13.77% |
| comment_branch | 198.0/214.7/229.2 | 199.2/243.6/276.5 | +13.46% | +20.64% |
| comment_worktree | 211.8/228.2/228.8 | 213.3/228.6/229.7 | +0.18% | +0.39% |

Failed 10% guards: branch-first max +14.35%; branch-comment p95 +13.46% and max +20.64%. The earlier pilot continuation pass does not waive these final failures. All six B action p95 values remain below 250 ms; Open remains above target.

Fresh-process Open and first-use values, ordered process 1/2/3:

| Action | A first use ms | B first use ms |
|---|---:|---:|
| open | 3091.1 / 727.6 / 728.2 | 852.9 / 603.3 / 586.3 |
| branch_first | 486.9 / 127.5 / 129.5 | 129.6 / 135.8 / 155.0 |
| branch_final | 543.8 / 133.9 / 136.1 | 151.1 / 135.9 / 121.2 |
| working_tree | 566.5 / 188.7 / 221.7 | 221.2 / 207.6 / 207.2 |
| stack | 267.8 / 136.6 / 141.8 | 127.0 / 127.7 / 126.1 |
| comment_branch | 228.7 / 213.7 / 214.0 | 200.7 / 213.3 / 199.1 |
| comment_worktree | 213.3 / 230.4 / 228.1 | 213.4 / 212.5 / 214.0 |

Foreground coverage is the union of recorded completed intervals. Remainder is elapsed time outside that union, including UI handling, frames, scheduling and unrecorded work; it is not paint-only time. Figures are p50/p95/max ms.

| Action | A foreground union | B foreground union | A remainder | B remainder |
|---|---:|---:|---:|---:|
| open | 653.3/3023.0/3023.0 | 530.6/787.8/787.8 | 74.3/74.9/74.9 | 71.9/72.7/72.7 |
| branch_first | 144.5/156.5/169.6 | 142.9/167.0/207.1 | 42.6/48.6/50.2 | 42.2/50.5/50.6 |
| branch_final | 88.6/91.3/98.9 | 85.8/95.2/104.6 | 44.6/48.3/48.7 | 38.8/48.5/48.7 |
| working_tree | 153.8/170.1/178.9 | 156.4/170.0/171.5 | 41.7/46.5/47.2 | 43.4/46.2/47.1 |
| stack | 87.0/106.1/114.9 | 87.3/91.5/93.5 | 38.1/44.8/47.5 | 38.5/47.0/47.9 |
| comment_branch | 159.4/175.3/183.0 | 159.7/198.1/232.5 | 39.4/46.2/46.8 | 42.4/47.1/50.3 |
| comment_worktree | 170.8/187.9/190.9 | 169.9/188.1/189.8 | 37.9/42.8/47.0 | 40.9/45.9/47.2 |

Exact relative action intervals follow. These nine A3/B3 rows are all repeated-phase and have no recorded background IPC.

| Action / row | Rep | Total | compare/open interval | patch interval | FG union | Remainder |
|---|---:|---:|---|---|---:|---:|
| branch_first A max | 4 | 215.3 | compare 0.2–157.7 | 161.4–173.5 | 169.6 | 45.7 |
| branch_first A near_p50 | 17 | 182.9 | compare 0.3–129.0 | 132.6–144.2 | 140.3 | 42.6 |
| branch_first B max | 1 | 246.2 | compare 0.2–194.6 | 198.2–210.9 | 207.1 | 39.1 |
| branch_first B p95 | 2 | 212.6 | compare 0.2–147.7 | 152.6–167.2 | 162.1 | 50.5 |
| comment_branch A max | 11 | 229.2 | open 0.2–168.2 | 172.0–187.0 | 183.0 | 46.2 |
| comment_branch A near_p50 | 5 | 198.0 | open 0.1–147.9 | 151.3–163.7 | 160.2 | 37.8 |
| comment_branch A p95 | 16 | 214.7 | open 0.1–161.6 | 165.2–179.0 | 175.3 | 39.4 |
| comment_branch B max | 6 | 276.5 | open 0.1–221.7 | 225.5–236.4 | 232.5 | 44.0 |
| comment_branch B p95 | 1 | 243.6 | open 0.3–185.0 | 188.4–201.8 | 198.1 | 45.5 |

Branch-first B max adds 30.9 ms versus A max: foreground +37.5 ms, remainder −6.6 ms. Compare lasts 194.4 versus 157.5 ms. Branch-comment B max adds 47.3 ms: foreground +49.5 ms, remainder −2.2 ms; native Open lasts 221.6 versus 168.0 ms. Branch-comment p95 adds 28.9 ms: foreground +22.8 ms, remainder +6.1 ms. These observations locate additional recorded time but do not establish its cause.

No absolute action timestamps exist. Screenshot write times and scorer bounds are retained as context in outlier-comparison.json. ipc-samples.json retains all 318 exact foreground unions/remainders and background calls, including pending calls and all original outliers.

A source 56a8fe49 / GUI b1fe0280; B source 252dec09 / GUI 684cbe82. Both use identical static GNU helper 328c0680; baseline executes it from the existing NTFS image and candidate from ext4. Full hashes and exact process records remain in summary.json.

Decision: retain the two cache-hit Open improvements and the failed action guards for investigation. No promotion, automatic retry or source-causality claim. No VM calls, tests, builds or source edits occurred during this host analysis.
