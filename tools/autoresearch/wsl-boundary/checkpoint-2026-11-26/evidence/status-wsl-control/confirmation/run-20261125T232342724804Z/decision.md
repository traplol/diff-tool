A4/B4 is a valid separate confirmation pair, but the WT-comment maximum fails the 10% guard. No waiver or promotion follows. The original six runs remain unchanged and are not pooled.

Both twenty-repetition processes pass canonical native content/comment and two-frame gates, completed welcome startup error, source/executable identities and exact app/driver/MCP/supervisor cleanup. All 242 samples are retained. Both fixture fingerprints and index/config/HEAD metadata match before and after. Master PID 94647/start 77138186 received exit acknowledgement 0 and exited 255; its socket and host-only wrapper are absent, host 19227 was recorded free, and shared 19225 remained untouched. Viewports were 1280×800.

Canonical nearest-rank p50/p95/max in milliseconds. Action rows include one first-use and nineteen repeated samples. Open is one fresh-process observation per variant, not a distribution or OS-cold result.

| Action | A4 p50/p95/max | B4 p50/p95/max | A4 first use | B4 first use |
|---|---:|---:|---:|---:|
| open | 2275.0/2275.0/2275.0 | 716.0/716.0/716.0 | 2275.0 | 716.0 |
| branch_first | 442.0/482.0/852.0 | 438.0/465.0/467.0 | 852.0 | 408.0 |
| branch_final | 368.0/409.0/735.0 | 358.0/388.0/397.0 | 735.0 | 397.0 |
| working_tree | 460.0/578.0/1732.0 | 438.0/503.0/529.0 | 1732.0 | 503.0 |
| stack | 455.0/498.0/501.0 | 446.0/484.0/516.0 | 438.0 | 482.0 |
| comment_branch | 487.0/523.0/673.0 | 486.0/541.0/575.0 | 673.0 | 575.0 |
| comment_worktree | 471.0/523.0/527.0 | 490.0/529.0/591.0 | 523.0 | 480.0 |

The all-twenty guard fails WT-comment max 527→591ms (+12.14%); its p95 is523→529ms (+1.15%). All other all-twenty p95/max guards pass. These are measured guards, not an inference from the inactive Windows-specific status code.

Strictly repeated phase, nineteen samples per action:

| Action | A4 repeated p50/p95/max | B4 repeated p50/p95/max |
|---|---:|---:|
| branch_first | 442.0/482.0/482.0 | 445.0/467.0/467.0 |
| branch_final | 368.0/409.0/409.0 | 358.0/388.0/388.0 |
| working_tree | 460.0/578.0/578.0 | 438.0/529.0/529.0 |
| stack | 455.0/501.0/501.0 | 446.0/516.0/516.0 |
| comment_branch | 487.0/523.0/523.0 | 486.0/541.0/541.0 |
| comment_worktree | 471.0/527.0/527.0 | 492.0/591.0/591.0 |

For nineteen samples, nearest-rank p95 is the maximum. WT-comment strict repeated p95 and max both fail 527→591ms (+12.14%). Every other strict repeated p95/max guard passes. This change in p95 rank must not hide the maximum.

Exact relative intervals for the relevant rows:

| Row | Phase / repetition | Total | Native interval | Patch interval | FG union | Remainder |
|---|---|---:|---|---|---:|---:|
| comment_worktree A max | repeated / 18 | 527.0 | open 0.0–195.0 | 200.0–247.0 | 242.0 | 285.0 |
| comment_worktree A near_p50 | repeated / 1 | 471.0 | open 1.0–165.0 | 171.0–205.0 | 198.0 | 273.0 |
| comment_worktree B max | repeated / 10 | 591.0 | open 1.0–194.0 | 199.0–234.0 | 228.0 | 363.0 |
| branch_first A max | first_use / 0 | 852.0 | compare 3.0–399.0 | 443.0–507.0 | 460.0 | 392.0 |
| branch_first A strict_repeated_max | repeated / 6 | 482.0 | compare 1.0–157.0 | 164.0–213.0 | 205.0 | 277.0 |
| branch_first B max | repeated / 2 | 467.0 | compare 1.0–158.0 | 164.0–216.0 | 209.0 | 258.0 |

WT-comment B max (repeated rep10) exceeds A max (repeated rep18) by 64ms: recorded foreground union is 14ms lower, while remainder is 78ms higher. Neither row records background IPC. Post-last-foreground time is 357ms versus 280ms. The remainder includes UI handling, frames, scheduling and unrecorded work; its cause is unproved. A canonical p50 row is 471ms, while the arithmetic median is 475ms; both statistics remain explicitly labeled in JSON.

Original repeated branch-first B 544ms did not recur: new B maximum is 467ms (rep2, foreground 209/remainder 258). Compare like phases: new A repeated max is 482ms, with foreground 205/remainder 277. A’s 852ms is first use, so comparing it directly with B’s repeated maximum mixes phases. The original B 544 row had foreground 202/remainder 342 and remains a failed original-series observation. A nonrecurrence in this pair does not erase it or prove no-regression.

The new pair instead shows a different tail failure at WT-comment 591ms. This confirms that a blanket guard pass is not supported. The Windows-specific status change is inactive in this local Linux cell; that fact does not explain the timing variation or waive failures. The pair cannot establish source causality or an Open distribution, and first-use/order effects remain uncertain.

Full source/build identities, all-twenty and strict-phase statistics, native unions/remainders, cleanup and fixture records are in summary.json. Every sample with exact foreground intervals and background calls is in ipc-samples.json. Screenshot-write/scorer timestamps are context only; absolute action-start times were not recorded.

Decision: preserve this failed separate confirmation and the original failed branch maximum. No promotion, automatic retry or inferred cause. No VM access, tests or builds occurred during host analysis.
