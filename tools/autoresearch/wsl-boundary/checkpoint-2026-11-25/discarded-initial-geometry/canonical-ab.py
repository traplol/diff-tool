"""Reuse the existing WSL/Linux status A/B adaptation, gated on native correctness."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT/'build/autoresearch/wsl-boundary'
RELEASE = 'VM GEOMETRY PILOT RELEASED'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shared_transport_identity():
    directory=Path('/proc/3963124')
    fields=(directory/'stat').read_text().rsplit(') ',1)[1].split()
    return {'pid':3963124,'start_ticks':fields[19],'binary':str((directory/'exe').resolve(strict=True)),
            'args':[part.decode() for part in (directory/'cmdline').read_bytes().split(b'\0') if part]}


# This is the existing status runner's WSL/Linux adaptation, with matching labels.
ab = load('existing_wsl_ab', BASE/'pane-reuse-gui-ab.py')
cleanup = load('existing_exact_cleanup', HERE.parent/'ui-phase-probe/run.py')
ab.stop_exact = cleanup.cleanup_exact
ab.BASE = HERE/'canonical-runs'


def prepare():
    versions = {}
    for key, label, source, proof in [
        ('A','geometry-baseline',BASE/'checkpoint-b2de070-source',BASE/'checkpoint-b2de070-build.json'),
        ('B','initial-editor-geometry',HERE/'source',HERE/'native-build-proof.json'),
    ]:
        build = json.loads(proof.read_text())
        identity = ab.score.source_identity(source)
        assert identity == build['source']
        assert build['embedded_helper']['sha256'] == '6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'
        assert build['linux_gui']['embedded_helper_verified']
        versions[key] = {'label':label,'source':str(source),'source_hash':identity['source_hash'],
                         'binary':build['linux_gui']['path'],'binary_sha256':build['linux_gui']['sha256'],
                         'build_record':str(proof),'build_record_sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}
    assert versions['A']['source_hash'] == '56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272'
    assert versions['B']['source_hash'] == '071ee12ca22b855f5cdfdd6e3c40951755369e1bd3d4834b551139f9964788ca'
    assert ab.score.contract_identity()['sha256'] == ab.CONTRACT
    ab.score.load_manifest(BASE/'workload.json')
    gates = [
        HERE/'aux-pointer-r2/20261125T222210699089Z-baseline/evidence/result.json',
        HERE/'aux-pointer-r2/20261125T222411302734Z-candidate-infraretry/evidence/result.json',
        HERE/'context-smoke-20261125T222502768424Z/evidence/result.json',
    ]
    native = []
    for index, path in enumerate(gates):
        report = json.loads(path.read_text()) if path.exists() else None
        if report:
            assert report['binary_sha256'] == versions['A' if index==0 else 'B']['binary_sha256']
        native.append({'path':str(path),'status':report.get('status') if report else 'pending',
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if report else None})
    shared=json.loads((HERE/'shared-transport.json').read_text())
    plan = {'status':'prepared-host-only','case':ab.CASE,'contract_sha256':ab.CONTRACT,'variants':versions,
            'profile':ab.PROFILE,'native_gate_reports':native,'execution_gate':RELEASE,
            'order':['A1:3','B1:3','A2:3','B2:3','pilot gate','A3:20','B3:20'],
            'pilot_gate':'All runs correct, WT pooled median ratio≤0.9, inherited worst pooled p95 ratio≤1.1',
            'shared_transport':shared,
            'tunnel':'Reuse verified pre-existing19225→29225 forward untouched; never terminate it',
            'work':'Unchanged canonical scorer, seeded profile, all seven actions, native helper6a, normal renderer/MCP and two completion frames',
            'files_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in [
                Path(__file__),HERE/'shared-transport.json',BASE/'status-gui-ab.py',BASE/'pane-reuse-gui-ab.py',HERE.parent/'ui-phase-probe/run.py']}}
    return versions, plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',choices=[RELEASE])
    args = parser.parse_args()
    versions, plan = prepare()
    ab.write_json(HERE/'canonical-ab-plan.json',plan)
    if not args.release:
        print(json.dumps(plan,indent=2)); return
    assert all(item['status']=='complete-correct-stopped' for item in plan['native_gate_reports']), 'Native gate incomplete or failed'
    ab.BASE.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    state_path = ab.BASE/('geometry-ab-'+stamp+'.json')
    state = {**plan,'status':'running','runs':[],'started_unix':time.time(),'orchestrator_pid':os.getpid()}
    tunnel = None
    try:
        expected={key:plan['shared_transport'][key] for key in ('pid','start_ticks','binary','args')}
        assert shared_transport_identity()==expected, 'Shared transport identity changed'
        ab.write_json(state_path,state)
        print(json.dumps({'state':str(state_path),'orchestrator_pid':os.getpid(),'shared_transport':expected}),flush=True)
        for key, number, reps in [('A',1,3),('B',1,3),('A',2,3),('B',2,3)]:
            assert shared_transport_identity()==expected, 'Shared transport identity changed'
            ab.run_one(key,number,reps,versions,stamp,state,state_path)
        state['pilot_result'] = ab.pilot_gate(state['runs'])
        ab.write_json(state_path,state)
        if not state['pilot_result']['pass']:
            state['status']='pilot-inconclusive-review-before-20-repetitions'
            return 3
        for key in ['A','B']:
            assert shared_transport_identity()==expected, 'Shared transport identity changed'
            ab.run_one(key,3,20,versions,stamp,state,state_path)
        state['final_20_repetition_actions']={run['variant']:run['action_and_ipc_summary'] for run in state['runs'] if run['number']==3}
        state['status']='complete-valid-awaiting-charter-review'
    except BaseException:
        state.update(status='stopped-on-error-no-restart',error=traceback.format_exc())
        raise
    finally:
        if tunnel:
            if tunnel.poll() is None: tunnel.terminate()
            state['owned_tunnel_exit']=tunnel.wait(timeout=10)
        state['shared_transport_unchanged']=shared_transport_identity()==expected
        state['finished_unix']=time.time()
        ab.write_json(state_path,state)
        print(json.dumps({'state':str(state_path),'status':state['status']}),flush=True)
    return 0


if __name__=='__main__': raise SystemExit(main())
