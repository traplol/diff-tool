#!/usr/bin/env python3
"""Prepare one Linux cell; reuse the existing private-mux canonical caller."""
import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import native_proof as gate

HERE=Path(__file__).resolve().parent;RUNNER=gate.ROOT/'build/experiments/status-wsl-control/run.py'
EXPECTED='4a253a7a50595aeabd755be55c16c024634882567c48235b6cb07e7714ed1d42'
AB_RUNNER=gate.BASE/'status-gui-ab.py';AB_SHA='2caebee7d2aef52e4d6ef90b89f410acf7966ee8d083f69e6dcae3fe3c103527'
RELEASE='VM INTEGRATED LINUX MATRIX RELEASED'
CASES={'wsl_linux':('baseline-compat-wsl-linux','seed-baseline-compat-wsl-linux'),
       'wsl_windows':('candidate-worker-v1-wsl-windows','seed-candidate-worker-v1-wsl-windows')}


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--case',choices=list(CASES),required=True);parser.add_argument('--release');args=parser.parse_args()
    assert gate.sha(RUNNER)==EXPECTED and gate.sha(AB_RUNNER)==AB_SHA
    control=load('integrated_linux_transport',RUNNER);ab=load('integrated_linux_ab',AB_RUNNER)
    case=args.case;profile_name,seed_name=CASES[case];profile='/home/max/benchmarks/branchline-boundary/profiles/'+profile_name
    out=HERE/'evaluation-controls'/case;out.mkdir(parents=True,exist_ok=True)
    control.HERE,control.CASE,control.PROFILE=out,case,profile
    control.ab=ab;ab.CASE,ab.PROFILE=case,profile
    # Preserve the proven interaction/cleanup logic. Only labels and the private forwarded port change.
    body=inspect.getsource(ab.run_one);assert body.count('-wsl-windows-{stamp}-')==1 and body.count('"19225"')==1
    exec(body.replace('-wsl-windows-{stamp}-','-'+case.replace('_','-')+'-{stamp}-').replace('"19225"',repr(str(control.HOST_PORT))),ab.__dict__)
    ab.stop_exact=control.stop_exact

    def prepare():
        assert gate.sha(RUNNER)==EXPECTED and gate.sha(AB_RUNNER)==AB_SHA
        current=gate.validate();protocol=json.loads((HERE/'evaluation-controls/protocol.json').read_text())
        manifest,manifest_sha=ab.score.load_manifest(gate.BASE/'workload.json')
        baseline_path=gate.BASE/'checkpoint-b2de070-build.json';baseline=json.loads(baseline_path.read_text())
        source=gate.BASE/'checkpoint-b2de070-source';assert ab.score.source_identity(source)==baseline['source']
        assert baseline['source']['source_hash']=='56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272'
        a=baseline['linux_gui'];helper=baseline['embedded_helper']
        assert a['sha256']=='78106ff431e6433195867048f5fae946bb1e63cc0f04f23d668be32956c444c4' and a['embedded_helper_verified'] and a['renderer']=='production default'
        assert helper['sha256']=='6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'
        variants={'A':{'label':'checkpoint-b2de070','source':str(source),'source_hash':baseline['source']['source_hash'],
                       'binary':a['path'],'binary_sha256':a['sha256'],'build_record':str(baseline_path),'build_record_sha256':gate.sha(baseline_path),'embedded_helper':helper}}
        seed_path=gate.BASE/seed_name/'verdict.json';seed=json.loads(seed_path.read_text())
        assert seed['valid'] and seed['setup_complete'] and seed['case']==case and seed['launch']['profile']==profile
        assert len(seed['comments'])==2 and {n['body'] for n in seed['comments']}=={ab.score.BRANCH_BODY,ab.score.WORKTREE_BODY}
        result={'status':'prepared-awaiting-complete-integrated-native-build','case':case,'profile':profile,'contract_sha256':gate.CONTRACT,
                'variants':variants,'seed_verdict':str(seed_path),'seed_sha256':gate.sha(seed_path),'comments':seed['comments'],
                'manifest_sha256':manifest_sha,'fixture_sha256':manifest['git_state_sha256'],'order':['A1:3','B1:3','A2:3','B2:3','A3:20','B3:20'],
                'performance_early_gate':False,'ports':{'host':control.HOST_PORT,'driver':29225,'mcp':28867},
                'measurement':protocol['measurement'],'renderer_and_mcp':'Unchanged canonical Linux launcher; no app environment or renderer overrides.',
                'transport':'Existing task-owned private master/forward and host-only wrapper; no new TCP fallback and no wrapper PATH in VM.',
                'runtime_release':RELEASE,'runner_sha256':gate.sha(Path(__file__)),'native_proof_sha256':gate.sha(Path(gate.__file__)),'existing_runner_sha256':AB_SHA,
                'transport_helper_sha256':gate.sha(RUNNER),'native_build_ready':current['ready'],'native_build_record':current['record'],
                'native_build_plan_sha256':current['build_plan_sha256'],'candidate_source':current['source'],'acceptance':protocol,
                'baseline_identity_note':protocol['baseline_identity'],'old_samples_pooled':False}
        if current['ready']:
            native=current['native'];plan=current['plan'];gui=native['linux_gui']
            variants['B']={'label':plan['label'],'source':str(HERE/'source'),'source_hash':gate.SOURCE,'binary':gui['path'],
                           'binary_sha256':gui['sha256'],'build_record':current['record'],'build_record_sha256':current['native_record_sha256'],
                           'embedded_helper':native['workers']['windows'],'protocol':1}
            result.update(native_build_record_sha256=current['native_record_sha256'],native_workers=native['workers'],native_gui_embeddings={p:native[p+'_gui'] for p in ('linux','windows')})
        return result

    control.prepare=prepare
    current=prepare();ab.write_json(out/'plan.json',current)
    if not current['native_build_ready']:
        if args.release:raise SystemExit('Completed source-bound integrated native build is required')
        print(json.dumps(current,indent=2));return 0
    sys.argv=[sys.argv[0]]+(['--release',args.release] if args.release else [])
    return control.main()

if __name__=='__main__':raise SystemExit(main())
