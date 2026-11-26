The measured series is valid, but the frozen staged-metadata pilot acceptance fails. Do not promote it. No old runs were pooled.

All six serial fresh processes and 318 samples passed native content/comment checks, welcome async-error readiness, source/executable identities and exact app/child cleanup. Fixture fingerprints and complete index/config/HEAD guards match before and after on both volumes. The private master PID 89383/start 77081349 received exit acknowledgement 0 and exited 255 as expected; its socket is absent and host port 19223 was recorded free. Shared port 19225 was untouched.

Worst p95, dominated by three fresh Opens, improved 1261.6→1198.6 ms (4.99%), below the 10% gate. Open median regressed 862.4→897.1 ms (+4.02%); the maximum p95 among branch-first, branch-final, stack and branch-comment changed 228.3→228.6 ms (+0.13%), so corroboration also fails. The 250 ms Open target remains unmet.

The following figures are canonical nearest-rank p50/p95/max in milliseconds. Open uses all three fresh processes. Actions use the final twenty samples, including their first-use sample; nineteen strictly repeated-phase samples remain separately recorded in summary.json.

| Action | A p50/p95/max | B p50/p95/max | p95 change | max change |
|---|---:|---:|---:|---:|
| open | 862.4/1261.6/1261.6 | 897.1/1198.6/1198.6 | -4.99% | -4.99% |
| branch_first | 196.1/216.5/230.3 | 208.0/226.6/280.5 | +4.67% | +21.80% |
| branch_final | 134.1/148.9/169.0 | 147.2/164.1/164.3 | +10.21% | -2.78% |
| working_tree | 203.1/249.8/261.3 | 205.2/234.8/237.1 | -6.00% | -9.26% |
| stack | 133.4/140.4/140.6 | 146.9/154.8/164.8 | +10.26% | +17.21% |
| comment_branch | 212.1/228.3/259.6 | 214.1/228.6/230.3 | +0.13% | -11.29% |
| comment_worktree | 228.2/260.5/291.5 | 214.0/243.0/243.8 | -6.72% | -16.36% |

Failed 10% guards: branch-first max +21.80%; branch-final p95 +10.21%; stack p95 +10.26% and max +17.21%. Branch-first B3 max is its first-use sample (280.5 ms), and remains part of the frozen final-twenty guard. The stack regression also remains in the strictly repeated subset. No outlier is removed.

Fresh-process Open and every first-use action below are ordered process 1/2/3. These are not OS-cold observations.

| Action | A first-use ms | B first-use ms |
|---|---:|---:|
| open | 1261.6 / 862.4 / 821.7 | 1198.6 / 897.1 / 757.6 |
| branch_first | 332.3 / 167.9 / 146.7 | 217.5 / 152.6 / 280.5 |
| branch_final | 182.5 / 139.9 / 146.0 | 147.5 / 153.3 / 164.0 |
| working_tree | 266.7 / 233.8 / 261.3 | 396.9 / 259.2 / 237.1 |
| stack | 121.9 / 191.0 / 136.5 | 165.5 / 136.7 / 140.9 |
| comment_branch | 1307.0 / 227.1 / 211.6 | 239.4 / 228.9 / 227.5 |
| comment_worktree | 245.0 / 237.9 / 244.4 | 256.9 / 232.0 / 243.0 |

Foreground IPC coverage is the union of its completed intervals, avoiding double counting overlap. The remainder is elapsed time outside that union; it includes UI handling, rendering, frames, scheduling and unrecorded work. It is not a paint-only metric. Figures below are p50/p95/max milliseconds using the same sample scope as the first table.

| Action | A foreground union | B foreground union | A remainder | B remainder |
|---|---:|---:|---:|---:|
| open | 764.2/1195.5/1195.5 | 837.2/1123.0/1123.0 | 75.4/98.2/98.2 | 73.1/75.6/75.6 |
| branch_first | 148.8/171.2/184.7 | 160.5/178.6/234.0 | 42.0/48.7/50.7 | 44.5/49.0/49.8 |
| branch_final | 89.4/100.9/119.9 | 102.8/119.9/121.9 | 46.2/49.1/50.5 | 41.6/48.6/49.5 |
| working_tree | 164.0/206.9/215.0 | 167.9/194.4/197.8 | 40.8/45.8/46.3 | 40.2/46.3/49.5 |
| stack | 89.5/98.0/102.4 | 104.6/114.7/118.2 | 39.3/47.3/48.0 | 40.3/48.5/49.2 |
| comment_branch | 166.5/186.1/217.9 | 177.3/189.0/189.7 | 41.6/48.2/48.3 | 39.4/47.9/50.7 |
| comment_worktree | 182.9/217.5/245.6 | 178.2/198.0/201.8 | 42.1/46.4/46.4 | 38.6/46.2/47.0 |

Each original sample with exact foreground intervals, background calls/pending calls, union and remainder is retained in ipc-samples.json. A1 branch-comment 1307.0 ms, B1 first WT 396.9 ms and B3 first branch-first 280.5 ms remain present. First-use and process maxima are retained separately from the final-twenty distribution.

The seed path was taken directly from this run plan: seed-windows-linux-02/verdict.json (SHA 5da3f824…). It selected note 2 on Staged kernel/fork.c, new line 3438. Source and native proof evidence support eligibility, but saved exports omit its actual old_path/file_version/left_tip and location.head. Host data therefore does not prove saved tuple equality or actual shortcut use. A later released, read-only export after Open on the default branch comparison can record the full note and location; head starting staged: proves the typed path. Details are in anchor-eligibility.json.

Identities remain distinct: A b2de070/source 56a8fe49/GUI b1fe0280/helper 328c0680 (protocol 1); B 1135a59/source aba80d92/GUI 86c90415/helper d729e0ea (protocol 2). The candidate PE worker is 8a72de49d410742c2fc7ad4010c9b4c96be94dac3dd83ec733485a1d88b3788d. Both new protocol 2 workers and both GUI embeddings passed the native record. The b2→1135 base differences affect tests only.

Decision: retain this failed measured series and candidate source/proofs as evidence. No promotion, no causal claim from first-process ordering, and no VM work was performed during this host analysis.

Later read-only proof: mode=ro note 2 export and the pinned protocol 2 worker verify the exact saved tuple and all lookup preconditions, with unchanged database/index/config/HEAD guards and graceful worker exit. See ../../eligibility-proof/summary.json. Saved-tuple eligibility is now proved; actual typed-branch use during the earlier GUI measurements remains unobserved. This adds no performance claim or acceptance waiver.
