# WebKit thread attribution

Prepared only. Both prior diagnostic runs and their original sources, proofs,
raw data and the CPU runner's failed teardown postcondition remain intact.

The second run measured about two CPU cores inside WebKit during 21 fully
sampled frame-wait interiors of at least 50 ms. The median main-thread use was
0.125 core. This supports native worker work rather than an idle process, but
does not identify rasterization, compositing, JavaScript workers or layout.

The final small diagnostic records one repeated branch-final action. Before
sampling, the normal UI opens the fixture, visits branch-first and branch-final,
and returns to branch-first. The unchanged canonical completion gate and
original UI injector observe the one repeated branch-final input.

The external sampler discovers one exact WebKitWebProcess under the recorded
GUI once, then reads only that process's `/proc/<pid>/task/*/stat` records. It
records each thread's name, identity, state and CPU ticks at a target 20 ms
period, with limits of 256 threads and 60 seconds. It reads graphics library
paths from that exact process's maps once before measurement. Library presence
does not establish active renderer use. The existing install evaluation returns
the same clock pair; no other browser reads, frames or timers are added.

The result should identify which named threads consume the CPU in the gaps.
Raster/llvmpipe/compositor threads would support testing smaller DOM invalidation
in a later isolated product candidate. Layout or JavaScript threads would point
to a different source target. No renderer policy is changed, and OnDemand is
not described as the default. No product change follows without evidence.

Host-only preparation:

```sh
python3 build/experiments/ui-phase-probe/run-thread.py
```

Only after the next explicit release:

```sh
python3 -u build/experiments/ui-phase-probe/run-thread.py --release 'VM UI THREAD DIAGNOSTIC RELEASED'
```

`prepared-thread.json` records exact source, GUI, contract, runner and sampler
hashes. The original runner handles hook restoration and exact GUI cleanup.
The thread observer must exit, and its recorded terminal identity state is
retained. Runtime CPU coverage of the measured interval must be checked before
using the observations.
