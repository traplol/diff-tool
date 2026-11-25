# UI phase probe

Diagnostic injector for the existing packaged Branchline GUI. Product source,
canonical scorer, renderer, GPU settings and the required completion frames stay
unchanged. This directory is ignored by Git. Do not score or promote this probe.

No VM execution has occurred. Run only after the current VM owner releases it.

## Usage

1. Open a real text diff and let it settle. Install the existing canonical
   `boundaryProbe`, then evaluate the complete `inject.js` body in that same
   webview. Installation throws if it cannot identify a real view through
   `contentDOM.cmTile.root.view` or cannot replace the required descriptors.
2. Arm the diagnostic immediately before arming the canonical sample:

   ```js
   branchlineUiPhaseProbe.arm('#pair', 'change', 'branch_final');
   boundaryProbe.arm('#pair', expected, 'change');
   ```

   Send the normal input through the existing native driver. Both timers begin
   on the actual capture-phase event. Their start times differ by the small
   observer execution and listener ordering cost.
3. Collect both results in one browser evaluation after sending input:

   ```js
   const sample = await boundaryProbe.finish();
   const trace = branchlineUiPhaseProbe.stop();
   return { sample, trace };
   ```

   Preserve raw records. `trace.action_start_ms` and every event use the
   webview's `performance.now()` clock. Subtract the trace start when plotting
   source events. The canonical elapsed time remains authoritative.
4. Arm another action only after stopping the prior action. Use normal workload
   transitions, including first visits, revisits and the two comment jumps.
5. In a `finally` block, evaluate:

   ```js
   return branchlineUiPhaseProbe.restore();
   ```

   This removes the API and restores every original property descriptor. It
   leaves `cancelAnimationFrame` untouched. Already queued wrapped callbacks
   still execute their original callback normally after restoration.

## Reading the trace

- `cm.measure`, `cm.update`, and `cm.lineBlockAtHeight` record synchronous call
  duration, view ID, parent call ID and whether the original threw. A nested
  `cm.measure` inside `cm.lineBlockAtHeight` identifies a synchronous flush while
  saving a position. Shared prototype hooks also cover newly created views.
- `raf.request` retains the native request ID. `raf.callback` records request
  time, callback-entry lag, original callback timestamp, callback duration and
  the active parent call. No callback or frame is added. Cancel uses native IDs.
- Durations are inclusive. Do not sum nested calls or add frame lag to work
  already contained in that interval. Records are stored on completion, so sort
  by `start_ms` for a timeline. A callback requested in an earlier action carries
  the earlier `request_action`; do not pair it with an unrelated current request.
- `dropped_events > 0` means the 4096-record limit was reached. Retain this fact
  and shorten the observed action before drawing conclusions.

The probe makes no extra DOM geometry reads, mutation observations, polling,
native requests, animation-frame requests or CodeMirror measurement requests.
It collects only bounded memory records while an action is active. Labels are
limited to 160 characters; arbitrary arguments, exceptions and document text
are not retained. View identities use a WeakMap.

The constructor, application closures, patch decoding and widget creation
outside hooked methods are unmeasured. Gaps before a newly created view first
requests measurement can contain those phases. The probe cannot distinguish
browser layout, rasterization, compositor, GPU or presentation work inside a
callback delay. Opaque callbacks are not labeled as application restoration,
scorer readiness or required completion frames. Use existing native IPC records and the planned frame-cadence
trace to compare the unmeasured gaps with the recorded synchronous spans.

Do not remove, shorten, relabel or subtract the canonical two completion frames.
Diagnostic observer overhead is retained; these traces are mechanism evidence,
not optimization scores.

## Host verification

`node --check inject.js` and `node check.mjs` pass. The small mock verifies
arguments, receivers, returns, original thrown objects, nesting, shared hooks
for new views, native frame IDs, cancellation, timestamps, bounded storage,
descriptor restoration and failures before installation. `host-proof.json`
records the injector hash. Native GUI behavior and timings remain unverified.
