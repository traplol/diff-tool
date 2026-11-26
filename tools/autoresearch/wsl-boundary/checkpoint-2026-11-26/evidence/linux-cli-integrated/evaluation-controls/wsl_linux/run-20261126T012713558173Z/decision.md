wsl_linux is valid. Its frozen same-side median and p95 guards fail. Keep the integrated candidate unpromoted.

All6 fresh processes and318 samples pass source/binary identity, native content/comment correctness, fixture and exact Linux app/driver/child cleanup checks. The private master received exit acknowledgement0 and exited255. Its socket is absent and the task-owned host port was recorded free. Exact host controller/master identities are absent now. This analysis made no VM calls, new port checks, retries, tests or builds.

Open by fresh process1/2/3: A 2401.0 / 738.0 / 740.0ms; B 647.0 / 652.0 / 619.0ms. No OS cache flush occurred.

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

| Action | A first-use ms | B first-use ms | A strict19 p50/p95/max | B strict19 p50/p95/max |
|---|---:|---:|---:|---:|
| open | 2401.0 / 738.0 / 740.0 | 647.0 / 652.0 / 619.0 | n/a | n/a |
| branch_first | 642.0 / 393.0 / 420.0 | 412.0 / 366.0 / 388.0 | 457.0/831.0/831.0 | 530.0/1229.0/1229.0 |
| branch_final | 399.0 / 388.0 / 372.0 | 403.0 / 361.0 / 366.0 | 379.0/801.0/801.0 | 545.0/954.0/954.0 |
| working_tree | 791.0 / 543.0 / 491.0 | 454.0 / 511.0 / 513.0 | 469.0/696.0/696.0 | 776.0/1690.0/1690.0 |
| stack | 538.0 / 472.0 / 438.0 | 464.0 / 438.0 / 456.0 | 465.0/536.0/536.0 | 586.0/1497.0/1497.0 |
| comment_branch | 540.0 / 648.0 / 550.0 | 459.0 / 422.0 / 439.0 | 493.0/646.0/646.0 | 601.0/1389.0/1389.0 |
| comment_worktree | 562.0 / 518.0 / 570.0 | 527.0 / 488.0 / 514.0 | 490.0/991.0/991.0 | 665.0/1726.0/1726.0 |

Foreground/remainder p50/p95/max ms use the same Open3/final20 scope. Foreground coverage is an interval union.

| Action | A foreground | B foreground | A remainder | B remainder |
|---|---:|---:|---:|---:|
| open | 440.0/2002.0/2002.0 | 338.0/345.0/345.0 | 313.0/399.0/399.0 | 302.0/321.0/321.0 |
| branch_first | 194.0/409.0/424.0 | 156.0/225.0/538.0 | 262.0/314.0/422.0 | 355.0/570.0/691.0 |
| branch_final | 97.0/185.0/463.0 | 118.0/216.0/325.0 | 275.0/299.0/338.0 | 416.0/601.0/629.0 |
| working_tree | 207.0/285.0/385.0 | 345.0/540.0/730.0 | 259.0/311.0/323.0 | 393.0/652.0/960.0 |
| stack | 158.0/212.0/218.0 | 183.0/259.0/319.0 | 305.0/322.0/326.0 | 362.0/800.0/1238.0 |
| comment_branch | 204.0/245.0/363.0 | 182.0/349.0/463.0 | 288.0/319.0/326.0 | 415.0/813.0/926.0 |
| comment_worktree | 226.0/269.0/538.0 | 293.0/508.0/777.0 | 267.0/453.0/491.0 | 377.0/555.0/949.0 |

Failed guard p95 rows are exact order-statistic samples, not paired requests. Maxima and all raw intervals remain in summary.json and ipc-samples.json.

| Action | A p95 total/FG/remainder | B p95 total/FG/remainder | Delta total/FG/remainder |
|---|---:|---:|---:|
| branch_first | 720.0/424.0/296.0 | 791.0/221.0/570.0 | 71.0/-203.0/274.0 |
| branch_final | 460.0/185.0/275.0 | 740.0/216.0/524.0 | 280.0/31.0/249.0 |
| branch_final | 460.0/185.0/275.0 | 740.0/216.0/524.0 | 280.0/31.0/249.0 |
| working_tree | 574.0/285.0/289.0 | 1000.0/348.0/652.0 | 426.0/63.0/363.0 |
| working_tree | 574.0/285.0/289.0 | 1000.0/348.0/652.0 | 426.0/63.0/363.0 |
| stack | 517.0/212.0/305.0 | 1119.0/319.0/800.0 | 602.0/107.0/495.0 |
| stack | 517.0/212.0/305.0 | 1119.0/319.0/800.0 | 602.0/107.0/495.0 |
| comment_branch | 550.0/234.0/316.0 | 1161.0/348.0/813.0 | 611.0/114.0/497.0 |
| comment_branch | 550.0/234.0/316.0 | 1161.0/348.0/813.0 | 611.0/114.0/497.0 |
| comment_worktree | 688.0/197.0/491.0 | 1016.0/486.0/530.0 | 328.0/289.0/39.0 |
| comment_worktree | 688.0/197.0/491.0 | 1016.0/486.0/530.0 | 328.0/289.0/39.0 |

The full20, strict repeated19, all-series maxima and all first-use observations remain separate. No outlier is removed and no new maximum gate is introduced. No OS, source, antivirus or noise cause is inferred. The reversed-cross results receive no waiver because the Windows execution policy is unchanged.

The complete integrated matrix must still include the other cells. This result cannot override its failed Windows primary-gain requirement. The full250ms goal remains unmet.
