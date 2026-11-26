Prepared host only. No native evaluation has run.

After the bundle-r2 native build finishes, copy its complete VM
`supervisor.json` to `../bundle-r2/native-evidence/supervisor.json`. The caller
requires its successful native tests and real stdio proofs, both fresh protocol
2 workers, both verified GUI embeddings, the pinned source/bundle identities and
unchanged native fixture guards. A missing or incomplete record blocks runtime.

Prepare without VM access:

```sh
python3 build/experiments/staged-anchor-metadata/evaluate-windows-wsl.py
```

Only after root grants the exact runtime slot:

```sh
python3 -u build/experiments/staged-anchor-metadata/evaluate-windows-wsl.py --release 'VM STAGED METADATA RUNTIME RELEASED'
```

This reuses the proven Windows caller, its private authenticated mux and the
unchanged canonical launcher/scorer. The Windows/WSL cell runs A1/B1 and A2/B2
with three repetitions, then A3/B3 with twenty. Host 19223, guest CDP 29223 and
MCP 28865 are task owned. Shared host 19225 is untouched. The existing ASCII
two-comment profile is opened directly. Welcome startup must finish with its
expected async error before measured Open. All Open, first-use and six-action
samples, foreground/background IPC, failures and exact cleanup remain recorded.

Measured A is source b2de070 / canonical identity 56a8fe49, Windows GUI b1fe0280,
with its matching protocol 1 Linux helper 328c0680. Candidate B is source
aba80d92 based on 1135a59, with newly built matching protocol 2 workers. The
committed b2-to-1135 differences affect test code and the smoke harness only;
`b2-to-1135-tests.patch` retains that evidence. The baseline is labeled b2
throughout, and neither source nor helper identity is substituted.

`acceptance.json` freezes the hypothesis, historical context and gates. The new
interleaved series supplies the comparison samples. The pilot requires at least
10% improvement in worst end-to-end p95 and corroborating Open-median or anchor
interaction improvement, with every action p95/max and Open guard within 10%.
An A1-only warmup/order difference is insufficient. Fresh process does not mean
OS-cold. All four cells on the delivered source remain required for promotion.

The independent status WSL/ext4 confirmation stays in
`../../status-wsl-control/confirm.py`. Its A4/B4 twenty-repetition pair requires
the separate `VM WSL STATUS CONFIRMATION RELEASED` slot and never pools the
original six-run series. Its recorded 480→544 ms branch-first max guard failure
remains unresolved until evidence supports a conclusion.
