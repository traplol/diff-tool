All four integrated matrix cells are valid. The candidate fails frozen acceptance and remains unpromoted.

The primary branch-group worst p95 is 229.0→224.7ms, a 1.88% improvement. The frozen requirement is at least10%. No older b2/a4 pilot observations are pooled.

All24 fresh processes and1,272 samples pass recorded source/binary/content/comment/fixture and exact actor cleanup gates. Private mux exit acknowledgements, terminal statuses, absent sockets and recorded task-owned port checks pass. This aggregation uses local saved records only.

windows_linux

Open by fresh process1/2/3: A 2024.0 / 883.8 / 863.1ms; B 826.9 / 800.1 / 1996.7ms.

| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |
|---|---:|---:|---:|---:|
| open | 883.8/2024.0/2024.0 | 826.9/1996.7/1996.7 | -6.44% | -1.35% |
| branch_first | 194.7/210.1/224.0 | 170.2/211.4/281.8 | -12.35% | +0.62% |
| branch_final | 134.0/149.4/149.8 | 127.1/155.7/257.0 | -5.15% | +4.22% |
| working_tree | 216.2/220.9/227.7 | 227.8/278.1/355.1 | +5.50% | +25.89% |
| stack | 138.0/148.4/152.3 | 120.6/137.6/139.1 | -12.61% | -7.28% |
| comment_branch | 213.4/229.0/260.2 | 180.3/224.7/229.5 | -15.39% | -1.88% |
| comment_worktree | 228.5/244.1/244.2 | 242.9/337.1/609.3 | +6.39% | +38.10% |

Failed frozen guards: working_tree p95_ms +25.89%; comment_worktree p95_ms +38.10%.

windows_windows

Open by fresh process1/2/3: A 1753.1 / 800.6 / 651.5ms; B 687.7 / 643.3 / 605.2ms.

| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |
|---|---:|---:|---:|---:|
| open | 800.6/1753.1/1753.1 | 643.3/687.7/687.7 | -19.65% | -60.77% |
| branch_first | 428.9/475.1/485.4 | 445.4/636.7/666.4 | +3.86% | +34.01% |
| branch_final | 384.6/416.5/441.0 | 399.4/540.4/565.0 | +3.70% | +29.75% |
| working_tree | 1563.8/1707.0/1760.9 | 1689.5/2287.7/2913.2 | +8.04% | +34.02% |
| stack | 357.1/425.3/438.1 | 376.1/581.9/1028.3 | +5.68% | +36.82% |
| comment_branch | 448.2/523.4/545.5 | 489.5/834.2/942.5 | +9.59% | +59.38% |
| comment_worktree | 1572.9/1727.7/1743.4 | 1697.9/2506.5/3330.2 | +8.60% | +45.08% |

Failed frozen guards: branch_first p95_ms +34.01%; branch_final p95_ms +29.75%; working_tree p95_ms +34.02%; stack p95_ms +36.82%; comment_branch p95_ms +59.38%; comment_worktree p95_ms +45.08%.

wsl_windows

Open by fresh process1/2/3: A 3090.0 / 2035.0 / 1789.0ms; B 2178.0 / 2042.0 / 1725.0ms.

| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |
|---|---:|---:|---:|---:|
| open | 2035.0/3090.0/3090.0 | 2042.0/2178.0/2178.0 | +0.34% | -29.51% |
| branch_first | 662.0/952.0/996.0 | 681.0/868.0/925.0 | +3.40% | -8.82% |
| branch_final | 602.0/1093.0/1128.0 | 618.0/848.0/854.0 | +1.23% | -22.42% |
| working_tree | 2021.0/3204.0/3487.0 | 2072.0/2882.0/2991.0 | +3.60% | -10.05% |
| stack | 672.0/788.0/1072.0 | 674.0/889.0/930.0 | +0.67% | +12.82% |
| comment_branch | 723.0/1101.0/1128.0 | 742.0/1072.0/1375.0 | +5.78% | -2.63% |
| comment_worktree | 1809.0/2310.0/2313.0 | 1821.0/2362.0/2411.0 | -0.43% | +2.25% |

Failed frozen guards: stack p95_ms +12.82%.

wsl_linux

Open by fresh process1/2/3: A 2401.0 / 738.0 / 740.0ms; B 647.0 / 652.0 / 619.0ms.

| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |
|---|---:|---:|---:|---:|
| open | 740.0/2401.0/2401.0 | 647.0/652.0/652.0 | -12.57% | -72.84% |
| branch_first | 457.0/720.0/831.0 | 513.0/791.0/1229.0 | +14.11% | +9.86% |
| branch_final | 377.0/460.0/801.0 | 534.0/740.0/954.0 | +42.72% | +60.87% |
| working_tree | 469.0/574.0/696.0 | 742.0/1000.0/1690.0 | +61.83% | +74.22% |
| stack | 465.0/517.0/536.0 | 546.0/1119.0/1497.0 | +21.72% | +116.44% |
| comment_branch | 493.0/550.0/646.0 | 601.0/1161.0/1389.0 | +21.66% | +111.09% |
| comment_worktree | 490.0/688.0/991.0 | 628.0/1016.0/1726.0 | +31.40% | +47.67% |

Failed frozen guards: branch_first median_ms +14.11%; branch_final median_ms +42.72%; branch_final p95_ms +60.87%; working_tree median_ms +61.83%; working_tree p95_ms +74.22%; stack median_ms +21.72%; stack p95_ms +116.44%; comment_branch median_ms +21.66%; comment_branch p95_ms +111.09%; comment_worktree median_ms +31.40%; comment_worktree p95_ms +47.67%.

Exact p95 order-statistic rows for failed guards follow. These rows are not paired requests. Each maximum and all foreground/background intervals remain in the JSON reports.

| Case/action/guard | A total/FG/remainder | B total/FG/remainder | Delta total/FG/remainder |
|---|---:|---:|---:|
| windows_linux/working_tree/p95_ms | 220.9/176.8/44.1 | 278.1/234.3/43.8 | 57.2/57.5/-0.3 |
| windows_linux/comment_worktree/p95_ms | 244.1/198.5/45.6 | 337.1/285.3/51.8 | 93.0/86.8/6.2 |
| windows_windows/branch_first/p95_ms | 475.1/432.4/42.7 | 636.7/596.7/40.0 | 161.6/164.3/-2.7 |
| windows_windows/branch_final/p95_ms | 416.5/373.1/43.4 | 540.4/498.6/41.8 | 123.9/125.5/-1.6 |
| windows_windows/working_tree/p95_ms | 1707.0/1671.4/35.6 | 2287.7/2244.6/43.1 | 580.7/573.2/7.5 |
| windows_windows/stack/p95_ms | 425.3/379.7/45.6 | 581.9/532.8/49.1 | 156.6/153.1/3.5 |
| windows_windows/comment_branch/p95_ms | 523.4/472.9/50.5 | 834.2/776.8/57.4 | 310.8/303.9/6.9 |
| windows_windows/comment_worktree/p95_ms | 1727.7/1689.7/38.0 | 2506.5/2468.9/37.6 | 778.8/779.2/-0.4 |
| wsl_windows/stack/p95_ms | 788.0/433.0/355.0 | 889.0/385.0/504.0 | 101.0/-48.0/149.0 |
| wsl_linux/branch_first/median_ms | 720.0/424.0/296.0 | 791.0/221.0/570.0 | 71.0/-203.0/274.0 |
| wsl_linux/branch_final/median_ms | 460.0/185.0/275.0 | 740.0/216.0/524.0 | 280.0/31.0/249.0 |
| wsl_linux/branch_final/p95_ms | 460.0/185.0/275.0 | 740.0/216.0/524.0 | 280.0/31.0/249.0 |
| wsl_linux/working_tree/median_ms | 574.0/285.0/289.0 | 1000.0/348.0/652.0 | 426.0/63.0/363.0 |
| wsl_linux/working_tree/p95_ms | 574.0/285.0/289.0 | 1000.0/348.0/652.0 | 426.0/63.0/363.0 |
| wsl_linux/stack/median_ms | 517.0/212.0/305.0 | 1119.0/319.0/800.0 | 602.0/107.0/495.0 |
| wsl_linux/stack/p95_ms | 517.0/212.0/305.0 | 1119.0/319.0/800.0 | 602.0/107.0/495.0 |
| wsl_linux/comment_branch/median_ms | 550.0/234.0/316.0 | 1161.0/348.0/813.0 | 611.0/114.0/497.0 |
| wsl_linux/comment_branch/p95_ms | 550.0/234.0/316.0 | 1161.0/348.0/813.0 | 611.0/114.0/497.0 |
| wsl_linux/comment_worktree/median_ms | 688.0/197.0/491.0 | 1016.0/486.0/530.0 | 328.0/289.0/39.0 |
| wsl_linux/comment_worktree/p95_ms | 688.0/197.0/491.0 | 1016.0/486.0/530.0 | 328.0/289.0/39.0 |

The JSON includes Open3, full20, strict repeated19, all-series26, first-use values and all-scope native foreground/remainder statistics. No observations are dropped and no new hard maximum gate is introduced. The remainder is not pure paint. No timing cause is inferred.

Decision: reject this integrated candidate for promotion. Preserve its isolated source, proofs and measurements. Do not change the frozen acceptance rules or replace controls with the older successful pilot. The full250ms cross-boundary goal remains unmet.
