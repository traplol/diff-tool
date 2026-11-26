# Delayed review progress experiment

Candidate source: `57b8d4671f5b477dc430d1bc719e6882d68a26aa7e5456fd007fbfd917329d4d`. Exact b2 baseline:
`56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272`. The real owned Git snapshot contains all tracked b2 files;
actual canonical source identity includes 49 application files. Only app.js differs.
Atomic87b and the backend candidates remain separate and unchanged.

Two production lines delay only "Reading Git changes…" until 200 ms and clear
the timer in changeWorkspace's finally block. Loading and aria-busy still change
immediately. Native requests, final rendering, completion and error propagation
retain the existing paths. There is no added wait, spinner or configuration.

The three passing focused cases execute the actual changeWorkspace function
with controlled native promises, a deterministic timer clock and minimal DOM
doubles. They cover fast success, feedback at 200 ms for pending work, and cleanup
on native rejection. Syntax checks, all five existing frontend test files and the Vite production
build pass. All checks ran serially after root released the host slot. Actual
canonical source identity remains unchanged; proof.json binds commands, exits,
logs and build outputs. A fresh KISS-only child reported "simple enough". No
native build, VM call or benchmark result exists for this candidate.
