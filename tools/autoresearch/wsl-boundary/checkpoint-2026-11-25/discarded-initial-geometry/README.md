# Initial editor geometry experiment

Hypothesis: resolving the first mounted CodeMirror viewport before presentation
can merge provisional and measured viewport work into one visual update. The
original b2 native traces show only3–11ms initial construction and3–8ms measure
work, separated by two roughly130ms native-CPU-heavy frame waits. The expected
benefit is one less expensive presentation cycle; that is unproved.

This candidate calls the public lineBlockAtHeight API after selection/restore
requests for newly created layouts only. Existing cached unified/split layout
switches, renderer, GPU policy, DOM contents and required scorer frames stay
unchanged. No private CodeMirror API is used. Geometry reading can add synchronous
layout work, so it must be measured and discarded if slower.

Only frontend/editor.js changes from exact b2 source56a8fe49. Syntax check passes.
Host tests, native correctness and canonical A/B have not run. Validate initial
unified/split layouts, restored nonzero scroll/selection, comment wrapping and
jumps, context expanders, rapid switching and compact/resized windows before
accepting a performance claim. This is an isolated experiment, not promoted.
