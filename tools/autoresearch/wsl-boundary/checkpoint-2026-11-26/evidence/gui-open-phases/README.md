# GUI Open phase diagnostic

Exact helper252 is the base; only `service.rs` and `git/remote.rs` add fixed-tag `Instant` spans. Each stderr line contains PID, tag and elapsed microseconds. No paths, arguments, operation bodies or results are logged. Logging errors are ignored; original calls, order and returned errors remain in place.

The source is a real self-contained detached b2 Git repository with the helper252 patch and diagnostic overlay. `source.json` records all49 app source files; `diagnostic.patch` is relative to252 and `candidate.patch` includes the complete delta from b2. Host proof is syntax/source only: no builds or tests ran during live timing.

Build only after root explicitly sends `VM OPEN PHASE BUILD RELEASED`:

```
python3 build/experiments/gui-open-phases/run-build.py --release 'VM OPEN PHASE BUILD RELEASED'
```

This performs one Windows GUI build using the existing static GNU328 worker, then copies exact proof and GUI back locally. No worker rebuild, GUI launch or scoring is included.

Native phase capture needs a separate runtime release. Record the existing stderr file length after welcome-ready and capture only the appended lines around an actual canonical Open. Keep all required rendering frames unchanged. Outer spans include nested logging overhead, so do not sum overlapping spans or treat diagnostic timings as A/B results. Per-operation remote tags distinguish round trips used by compare and note tracking.
