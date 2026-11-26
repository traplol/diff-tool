#!/usr/bin/env python3
"""Prepare the two Windows cells; execution requires the serial VM release."""
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys
import native_proof as gate

HERE=Path(__file__).resolve().parent;OUT=HERE/'evaluation-controls/windows';OUT.mkdir(parents=True,exist_ok=True)
RUNNER=gate.ROOT/'build/experiments/status-windows-controls/run.py'
EXPECTED='a9587333c5dd330c6fc2f830d6d9d0ae74042c45edc6a47e3ad173b210d49052'
assert gate.sha(RUNNER)==EXPECTED
spec=importlib.util.spec_from_file_location('integrated_windows',RUNNER);control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
baseline=control.prepare();control.HERE=OUT
control.CASES={case:control.CASES[case] for case in ['windows_linux','windows_windows']}
RELEASE='VM INTEGRATED WINDOWS MATRIX RELEASED'


def prepare():
    assert gate.sha(RUNNER)==EXPECTED
    current=gate.validate();plan=current['plan'];protocol=json.loads((HERE/'evaluation-controls/protocol.json').read_text())
    result={**baseline,'status':'prepared-awaiting-complete-integrated-native-build','variants':{'A':baseline['variants']['A']},
            'case_order':['windows_linux','windows_windows'],'cases':{case:baseline['cases'][case] for case in control.CASES},
            'runtime_release':RELEASE,'runner_sha256':gate.sha(Path(__file__)),'native_proof_sha256':gate.sha(Path(gate.__file__)),'reused_caller_sha256':EXPECTED,
            'native_build_record':current['record'],'native_build_plan_sha256':current['build_plan_sha256'],
            'native_build_ready':current['ready'],'candidate_source':current['source'],'acceptance':protocol,
            'baseline_identity_note':protocol['baseline_identity'],'old_samples_pooled':False}
    if current['ready']:
        native=current['native'];gui=native['windows_gui']
        for platform,old_name in [('linux','wsl'),('windows','windows')]:
            for name,value in native['fixture_after'][platform]['files'].items():
                before=baseline['fixture_guards'][old_name][Path(name).name]
                assert value=={'sha256':before['sha256'],'size':before['bytes'],'mtime_ns':before['mtime_ns'],'inode':before['inode'],'mode':before['mode']}
        result['variants']['B']={'label':plan['label'],'source':str(HERE/'source'),'source_hash':gate.SOURCE,
                                'binary':str(PureWindowsPath(plan['windows_binary'])),'binary_sha256':gui['sha256'],
                                'helper_sha256':native['workers']['linux']['sha256'],'protocol':1}
        result.update(native_build_record_sha256=current['native_record_sha256'],native_workers=native['workers'],native_gui_embeddings={p:native[p+'_gui'] for p in ('linux','windows')})
    return result


control.prepare=prepare
if __name__=='__main__':
    current=prepare();control.score.atomic_json(OUT/'plan.json',current)
    if not current['native_build_ready']:
        if '--release' in sys.argv:raise SystemExit('Completed source-bound integrated native build is required')
        print(json.dumps(current,indent=2))
    else:raise SystemExit(control.main())
