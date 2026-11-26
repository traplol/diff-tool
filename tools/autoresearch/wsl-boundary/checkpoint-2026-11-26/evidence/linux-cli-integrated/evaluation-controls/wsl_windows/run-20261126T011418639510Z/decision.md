wsl_windows is valid. Its frozen reversed-cross p95 guards fail. Keep the integrated candidate unpromoted.

All6 fresh processes and318 samples pass source/binary identity, native content/comment correctness, fixture and exact Linux app/driver/child cleanup checks. The private master received exit acknowledgement0 and exited255. Its socket is absent and the task-owned host port was recorded free. Exact host controller/master identities are absent now. This analysis made no VM calls, new port checks, retries, tests or builds.

Open by fresh process1/2/3: A 3090.0 / 2035.0 / 1789.0ms; B 2178.0 / 2042.0 / 1725.0ms. No OS cache flush occurred.

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

| Action | A first-use ms | B first-use ms | A strict19 p50/p95/max | B strict19 p50/p95/max |
|---|---:|---:|---:|---:|
| open | 3090.0 / 2035.0 / 1789.0 | 2178.0 / 2042.0 / 1725.0 | n/a | n/a |
| branch_first | 882.0 / 613.0 / 657.0 | 629.0 / 688.0 / 708.0 | 662.0/996.0/996.0 | 681.0/925.0/925.0 |
| branch_final | 705.0 / 635.0 / 646.0 | 629.0 / 689.0 / 634.0 | 602.0/1128.0/1128.0 | 618.0/854.0/854.0 |
| working_tree | 2004.0 / 2047.0 / 2798.0 | 2043.0 / 2430.0 / 2040.0 | 2021.0/3487.0/3487.0 | 2127.0/2991.0/2991.0 |
| stack | 718.0 / 977.0 / 1072.0 | 880.0 / 687.0 / 615.0 | 672.0/788.0/788.0 | 687.0/930.0/930.0 |
| comment_branch | 799.0 / 916.0 / 1008.0 | 870.0 / 828.0 / 740.0 | 723.0/1128.0/1128.0 | 795.0/1375.0/1375.0 |
| comment_worktree | 1880.0 / 2012.0 / 2313.0 | 2224.0 / 2251.0 / 1821.0 | 1809.0/2310.0/2310.0 | 1846.0/2411.0/2411.0 |

Foreground/remainder p50/p95/max ms use the same Open3/final20 scope. Foreground coverage is an interval union.

| Action | A foreground | B foreground | A remainder | B remainder |
|---|---:|---:|---:|---:|
| open | 1608.0/2576.0/2576.0 | 1674.0/1787.0/1787.0 | 427.0/514.0/514.0 | 368.0/391.0/391.0 |
| branch_first | 393.0/558.0/583.0 | 397.0/516.0/556.0 | 276.0/370.0/438.0 | 272.0/354.0/369.0 |
| branch_final | 318.0/661.0/741.0 | 324.0/437.0/462.0 | 285.0/432.0/498.0 | 292.0/417.0/431.0 |
| working_tree | 1698.0/2643.0/2721.0 | 1729.0/2285.0/2349.0 | 314.0/575.0/978.0 | 316.0/642.0/935.0 |
| stack | 349.0/426.0/433.0 | 353.0/403.0/409.0 | 317.0/375.0/646.0 | 301.0/504.0/542.0 |
| comment_branch | 418.0/600.0/654.0 | 431.0/567.0/709.0 | 305.0/501.0/502.0 | 321.0/544.0/666.0 |
| comment_worktree | 1522.0/1928.0/1957.0 | 1477.0/1989.0/2040.0 | 293.0/388.0/436.0 | 301.0/422.0/678.0 |

Failed guard p95 rows are exact order-statistic samples, not paired requests. Maxima and all raw intervals remain in summary.json and ipc-samples.json.

| Action | A p95 total/FG/remainder | B p95 total/FG/remainder | Delta total/FG/remainder |
|---|---:|---:|---:|
| stack | 788.0/433.0/355.0 | 889.0/385.0/504.0 | 101.0/-48.0/149.0 |

The full20, strict repeated19, all-series maxima and all first-use observations remain separate. No outlier is removed and no new maximum gate is introduced. No OS, source, antivirus or noise cause is inferred. The reversed-cross results receive no waiver because the Windows execution policy is unchanged.

The complete integrated matrix must still include the other cells. This result cannot override its failed Windows primary-gain requirement. The full250ms goal remains unmet.
