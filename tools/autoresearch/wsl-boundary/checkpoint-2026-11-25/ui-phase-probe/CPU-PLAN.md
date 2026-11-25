# External CPU diagnostic

Prepared only. The original run, runner and proof are retained, including the
copy in `original-20261125T213031571855Z/`. No product, injector, canonical scorer
or original runner is changed.

The original trace bounds patch decoding, first editor construction and the
pre-construction size reads together to about 3–11 ms before the initial
CodeMirror measurement request. Measurement itself takes 3–8 ms. Position
saving takes 0 ms at this clock's precision. Two long callback-entry waits
remain. Existing getter hooks would not explain those bounds.

`run-cpu.py` reuses the original runner. It adds one external Python sampler
after timed Open and injector installation, before the first branch action.
The existing install evaluation additionally returns `performance.timeOrigin`
and one `Date.now()`/`performance.now()` pair. No other browser reads, frames,
timers, geometry, native requests or measurement requests are added.

The sampler validates the launch record's GUI PID, executable and start ticks.
It follows only `/proc/<pid>/task/<pid>/children`, revalidates parent identities
and child parentage, and reads each exact process's CPU ticks and state. For
WebKit processes it also reads the main thread's ticks and state. It never
scans all processes or reads environments. Unreadable records are explicit.
Records include guest wall and monotonic clocks and read duration. The target
period is 20 ms, duration is at most 60 seconds and the tree limit is 64
processes. The sampler stops when the exact GUI disappears during cleanup.

The measurable hypothesis is that the 100–170 ms gaps consume substantial CPU
inside WebKit, or instead occur while WebKit is mostly sleeping. Process and
main-thread tick deltas distinguish these cases. A runnable state with few CPU
ticks also suggests scheduling delay. Sleeping with few ticks supports a wait
outside observed CPU work; it does not prove a compositor or GPU cause.
Outside-tree processes and children that exit between samples remain outside
the evidence. Observer overhead stays in elapsed time and is reported, never
subtracted. No renderer-library or renderer-setting changes are included.

Host-only identity preparation:

```sh
python3 build/experiments/ui-phase-probe/run-cpu.py
```

Only after the coordinator sends the exact next release:

```sh
python3 -u build/experiments/ui-phase-probe/run-cpu.py --release 'VM UI CPU DIAGNOSTIC RELEASED'
```

The same b2/78106 GUI, fixture, seeded profile and two canonical repetitions
apply. The original exact cleanup runs first. The CPU observer then must exit
with `root_gone`; its host controller exit and final record are retained.
