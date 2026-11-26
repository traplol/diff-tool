#!/usr/bin/env python3
"""Prepare a separate A4/B4 pair using the frozen WSL control caller."""
import hashlib
import importlib.util
import inspect
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / 'run.py'
EXPECTED = '4a253a7a50595aeabd755be55c16c024634882567c48235b6cb07e7714ed1d42'
assert hashlib.sha256(RUNNER.read_bytes()).hexdigest() == EXPECTED, 'Frozen control caller changed'
spec = importlib.util.spec_from_file_location('frozen_wsl_confirmation', RUNNER)
frozen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen)
original_prepare = frozen.prepare
frozen.HERE = HERE / 'confirmation'
frozen.HERE.mkdir(exist_ok=True)


def prepare_pair():
    plan = original_prepare()
    plan.update(runtime_release='VM WSL STATUS CONFIRMATION RELEASED', order=['A4:20', 'B4:20'],
                confirmation_of=str(HERE / 'run-20261125T223739227075Z/state.json'),
                pooling='Separate confirmation pair; retain the original six runs without pooling.',
                confirmation_caller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return plan


frozen.prepare = prepare_pair
body = inspect.getsource(frozen.main)
old = "[('A',1,3),('B',1,3),('A',2,3),('B',2,3),('A',3,20),('B',3,20)]"
assert body.count(old) == 1 and body.count("if item['number']==3") == 1
body = body.replace(old, "[('A',4,20),('B',4,20)]").replace("if item['number']==3", "if item['number']==4")
exec(body, frozen.__dict__)

if __name__ == '__main__':
    raise SystemExit(frozen.main())
