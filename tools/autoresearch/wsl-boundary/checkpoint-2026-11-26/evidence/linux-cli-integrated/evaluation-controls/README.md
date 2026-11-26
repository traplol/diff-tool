# Integrated matrix controls

These adapters compare the exact integrated c200 source and all four source-bound
native artifacts against the preserved b2 controls. The older a4 primary series
remains separate pilot evidence. No old samples are pooled.

`protocol.json` freezes the four-cell expansion before measurement. Each cell
uses six serial fresh processes, with three, three and twenty repetitions per
variant. The complete matrix has24 processes and1272 samples. The existing two
comment profiles, canonical scorer, native marker/comment correctness, welcome
startup readiness, default renderer and two completion frames remain unchanged.

After the exact integrated native build and its copied evidence pass all gates,
run these commands serially, only with the root agent's explicit runtime release:

```sh
python3 -u build/experiments/linux-cli-integrated/evaluate-windows.py \
  --release 'VM INTEGRATED WINDOWS MATRIX RELEASED'
python3 -u build/experiments/linux-cli-integrated/evaluate-linux.py --case wsl_windows \
  --release 'VM INTEGRATED LINUX MATRIX RELEASED'
python3 -u build/experiments/linux-cli-integrated/evaluate-linux.py --case wsl_linux \
  --release 'VM INTEGRATED LINUX MATRIX RELEASED'
```

Without a release argument, the scripts only prepare plans and perform local
source/build/seed checks. They do not access the VM or ports. Until native build
evidence is present, they report pending and refuse execution. Windows uses the
proven two-cell private-mux caller. Linux reuses the existing private-mux wrapper,
canonical run/cleanup logic and profiles, changing only case labels and the
private forwarded host port. Shared forward19225 stays untouched.

`native_proof.py` is shared by the two adapters. It requires real ce75 Git/source
provenance, all49 app-file hashes, fresh root Cargo producers for both workers,
unit tests and both GUI bin/lib pairs, matching copied binaries, static GNU and
Windows CRT checks,25+1 Linux and23 Windows native test names, exact kernel branch
metadata proofs on both platforms, opposite-worker embeddings, packaged Tauri
dependency features and unchanged fixture guards. It accepts Cargo's reported
unit executable layout rather than assuming a `deps` directory. Root feature
lists may be empty; packaged mode is proved through the actual Tauri and macro
dependency features and production build-script cfgs.

The primary branch gain must exceed10%. Same-side median/p95 and cross-cell p95
regression guards remain10%; every maximum and first-use observation is retained
and outliers require investigation. This expansion does not invent a new hard
maximum gate or require unaffected controls to improve global worst latency.
Qualification is not completion: the full250ms target and representative cold
behavior remain unproven until the complete delivered-source evidence passes.
