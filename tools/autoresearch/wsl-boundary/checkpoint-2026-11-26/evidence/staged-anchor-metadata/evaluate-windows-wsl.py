#!/usr/bin/env python3
"""Prepare the canonical staged-metadata A/B; wait for the runtime release."""
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'evaluation-windows-wsl'
OUT.mkdir(exist_ok=True)
RUNNER = ROOT / 'build/experiments/status-windows-controls/run.py'
EXPECTED_RUNNER = 'a9587333c5dd330c6fc2f830d6d9d0ae74042c45edc6a47e3ad173b210d49052'
SOURCE = 'aba80d9202698734d4915c9b652d58406e3602c1dc277983e97a7f6b59e80404'
NATIVE = HERE / 'bundle-r2/native-evidence/supervisor.json'
RELEASE = 'VM STAGED METADATA RUNTIME RELEASED'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


assert sha(RUNNER) == EXPECTED_RUNNER, 'Proven Windows caller changed'
spec = importlib.util.spec_from_file_location('staged_windows_control', RUNNER)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
# Validate the existing builds, sources, profiles and retained failure record
# with the original caller before selecting just its Windows/WSL cell.
baseline = control.prepare()
control.HERE = OUT
control.CASES = {'windows_linux': control.CASES['windows_linux']}


def prepare():
    assert control.score.contract_identity()['sha256'] == control.CONTRACT
    assert sha(RUNNER) == EXPECTED_RUNNER
    assert sha(control.BUILD_STATE) == baseline['build_state_sha256']
    a = baseline['variants']['A']
    builds = json.loads(control.BUILD_STATE.read_text())
    built_a, = [item for item in builds['builds'] if item['label'] == a['label']]
    assert control.score.source_identity(Path(a['source'])) == built_a['source']
    case = baseline['cases']['windows_linux']
    assert sha(case['seed_verdict']) == case['seed_sha256']
    plan = json.loads((HERE / 'bundle-r2/build-plan.json').read_text())
    assert plan['source']['source_hash'] == SOURCE and plan['protocol'] == 2
    assert control.score.source_identity(HERE / 'source') == plan['source']
    for name, expected in plan['host_proof_files'].items():
        assert sha(HERE / name) == expected, 'Host proof changed: ' + name
    evidence = json.loads((OUT / 'acceptance.json').read_text())
    result = {**baseline, 'status': 'prepared-only-no-VM-or-port-access',
              'variants': {'A': a}, 'cases': {'windows_linux': case},
              'case_order': ['windows_linux'], 'runtime_release': RELEASE,
              'native_build_record': str(NATIVE), 'acceptance': evidence,
              'runner_sha256': sha(Path(__file__)), 'reused_caller_sha256': EXPECTED_RUNNER,
              'baseline_identity_note': 'Measured A is b2/56a8; candidate base is 1135. Their committed differences affect tests only. Exact identities remain distinct.',
              'retained_previous_attempt': 'Status runs and original A1 remain separate historical context; no old samples are pooled.'}
    if not NATIVE.exists():
        result.update(status='prepared-awaiting-completed-native-build-record',
                      native_build_ready=False, candidate_source=plan['source'])
        return result
    native = json.loads(NATIVE.read_text())
    assert native['status'] == 'built; canonical GUI evaluation pending', 'Native build is incomplete'
    assert native['source'] == plan['source']
    assert native['source_git_provenance']['head'] == plan['source']['git_head']
    assert native['source_git_provenance']['tree'] == plan['bundle']['git_tree']
    assert native['source_git_provenance']['bundle_sha256'] == plan['bundle']['sha256']
    assert not native['source_git_provenance']['external_alternates']
    assert native['source_git_provenance']['working_files_preserved']
    assert native['fixture_before'] == native['fixture_after']
    assert {item['git_state_sha256'] for item in native['fixture_after'].values()} == {baseline['fixture_sha256']}
    phases = {phase['name']: phase for phase in native['phases']}
    for name in ('linux-worker-build', 'windows-worker-build', 'linux-worker-tests',
                 'windows-worker-unit-tests', 'linux-gui-build', 'windows-gui-build'):
        assert phases[name]['exit'] == 0, 'Native phase did not pass: ' + name
    for platform in ('linux', 'windows'):
        worker = native['workers'][platform]
        assert worker['sha256'] not in {control.HELPER, '6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'}
        proof, = [item for item in native['kernel_proofs'] if item['platform'] == platform]
        assert proof['sha256'] == worker['sha256'] and proof['exit'] == 0
        assert proof['hello']['protocol'] == 2 and proof['hello']['os'] == platform
        assert sorted(proof['result']['versions'], key=lambda item: item['path']) == proof['expected']
        assert proof['result']['location_head'].startswith('staged:')
        gui = native[platform + '_gui']
        opposite = 'windows' if platform == 'linux' else 'linux'
        assert gui['embedded_helper_verified'] and gui['renderer'] == 'production default'
        assert gui['embedded_helper_sha256'] == native['workers'][opposite]['sha256']
    # The canonical caller checks the complete older guard, including ctime.
    # Require the native build's common stat fields to describe that same fixture.
    for platform, old_name in [('linux', 'wsl'), ('windows', 'windows')]:
        for name, values in native['fixture_after'][platform]['files'].items():
            prior = baseline['fixture_guards'][old_name][Path(name).name]
            assert values == {'sha256': prior['sha256'], 'size': prior['bytes'],
                              'mtime_ns': prior['mtime_ns'], 'inode': prior['inode'], 'mode': prior['mode']}
    gui = native['windows_gui']
    expected_path = '/mnt/c/' + plan['windows_binary'][3:]
    assert gui['path'] == expected_path
    b = {'label': plan['label'], 'source': str(HERE / 'source'), 'source_hash': SOURCE,
         'binary': str(PureWindowsPath(plan['windows_binary'])), 'binary_sha256': gui['sha256'],
         'helper_sha256': native['workers']['linux']['sha256'], 'protocol': 2}
    result.update(native_build_ready=True, native_build_record_sha256=sha(NATIVE),
                  native_workers=native['workers'], native_gui_embeddings={name: native[name] for name in ['linux_gui', 'windows_gui']},
                  variants={'A': a, 'B': b})
    return result


control.prepare = prepare

if __name__ == '__main__':
    current = prepare()
    control.score.atomic_json(OUT / 'plan.json', current)
    if not current.get('native_build_ready'):
        if '--release' in sys.argv:
            raise SystemExit('Completed matching protocol-2 build record is required before runtime')
        print(json.dumps(current, indent=2))
    else:
        raise SystemExit(control.main())
