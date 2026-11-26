#!/usr/bin/env python3
"""Prepare the Linux CLI branch A/B; wait for the serial VM runtime release."""
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
SOURCE = 'a4a08d4123b2c72cfc2c12aa56cefeb06c57316ac647c7d59d7ee58d0b4ba9d5'
BUILD_PLAN = HERE / 'native-build/build-plan.json'
NATIVE = HERE / 'native-build/native-evidence/supervisor.json'
RELEASE = 'VM LINUX CLI BRANCH RUNTIME RELEASED'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


assert sha(RUNNER) == EXPECTED_RUNNER, 'Proven Windows caller changed'
spec = importlib.util.spec_from_file_location('linux_cli_windows_control', RUNNER)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
# Original caller validates both existing controls and seed records locally.
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
    source = json.loads((HERE / 'source.json').read_text())
    assert source['source_hash'] == SOURCE
    assert source['git_head'] == built_a['source']['git_head']
    assert control.score.source_identity(HERE / 'source') == source
    proof = json.loads((HERE / 'proof.json').read_text())
    assert proof['source_hash'] == SOURCE and proof['source_unchanged_after_tests']
    assert proof['host_worker']['unit_passed'] == 25 and proof['host_worker']['real_stdio_passed'] == 1
    assert proof['host_gui_rust']['passed'] == 70 and proof['host_gui_rust']['ignored'] == 1
    for name in ('host_worker', 'host_gui_rust'):
        assert proof[name]['failed'] == 0
        assert sha(HERE / proof[name]['log']) == proof[name]['log_sha256']
    evidence = json.loads((OUT / 'acceptance.json').read_text())
    result = {**baseline, 'status': 'prepared-only-no-VM-or-port-access',
              'variants': {'A': a}, 'cases': {'windows_linux': case},
              'case_order': ['windows_linux'], 'runtime_release': RELEASE,
              'native_build_record': str(NATIVE), 'acceptance': evidence,
              'runner_sha256': sha(Path(__file__)), 'reused_caller_sha256': EXPECTED_RUNNER,
              'baseline_identity_note': 'Both sources are pinned to b2. Candidate changes only the Linux execution branch-summary path; Windows native policy and helper placement are unchanged.',
              'retained_previous_attempt': 'Historical status, staged-metadata and helper results remain separate; no old samples are pooled.'}
    if not BUILD_PLAN.exists():
        result.update(status='prepared-awaiting-native-build-plan', native_build_ready=False,
                      candidate_source=source)
        return result
    plan = json.loads(BUILD_PLAN.read_text())
    assert plan['source'] == source and plan['protocol'] == 1
    for name, expected in plan['host_proof_files'].items():
        assert sha(HERE / name) == expected, 'Host proof changed: ' + name
    result['native_build_plan_sha256'] = sha(BUILD_PLAN)
    if not NATIVE.exists():
        result.update(status='prepared-awaiting-completed-native-build-record',
                      native_build_ready=False, candidate_source=source)
        return result
    native = json.loads(NATIVE.read_text())
    assert native['status'] == 'built; canonical GUI evaluation pending', 'Native build is incomplete'
    assert native['source'] == source
    provenance = native['source_git_provenance']
    assert provenance['head'] == source['git_head'] and provenance['tree'] == plan['bundle']['git_tree']
    assert provenance['bundle_sha256'] == plan['bundle']['sha256']
    assert not provenance['external_alternates'] and provenance['working_files_preserved']
    assert native['fixture_before'] == native['fixture_after']
    assert {item['git_state_sha256'] for item in native['fixture_after'].values()} == {baseline['fixture_sha256']}
    phases = {phase['name']: phase for phase in native['phases']}
    for name in ('linux-worker-root-clean', 'linux-worker-build', 'linux-worker-tests',
                 'linux-kernel-proof', 'windows-gui-root-clean', 'windows-gui-build'):
        assert phases[name]['exit'] == 0, 'Native phase did not pass: ' + name
    producers = native['producer_artifacts']
    worker_manifest = str(Path(plan['source_input_directory']) / 'source/src-tauri/git-worker/Cargo.toml')
    gui_manifest = str(Path(plan['source_input_directory']) / 'source/src-tauri/Cargo.toml')
    for key, manifest, name, kind, test in [
        ('linux_worker', worker_manifest, 'branchline-git-worker', 'bin', False),
        ('linux_worker_tests', worker_manifest, 'branchline-git-worker', 'bin', True),
        ('linux_worker_stdio', worker_manifest, 'stdio', 'test', True),
        ('windows_gui', gui_manifest, 'branchline', 'bin', False),
    ]:
        producer = producers[key]
        assert producer['reason'] == 'compiler-artifact' and producer['manifest_path'] == manifest
        assert producer['target']['name'] == name and producer['target']['kind'] == [kind]
        assert producer['profile']['test'] is test and producer['profile']['opt_level'] == '3'
        assert producer['fresh'] is False and producer['executable']
    worker_release = Path(plan['worker_target_cache']) / 'x86_64-unknown-linux-gnu/release'
    assert producers['linux_worker']['executable'] == str(worker_release / 'branchline-git-worker')
    for key, stem in [('linux_worker_tests', 'branchline_git_worker-'), ('linux_worker_stdio', 'stdio-')]:
        executable = Path(producers[key]['executable'])
        assert executable.parent == worker_release / 'deps' and executable.name.startswith(stem)
    gui_release = Path(plan['gui_target_cache']) / 'x86_64-pc-windows-msvc/release'
    assert producers['windows_gui']['executable'] == str(gui_release / 'branchline.exe')
    assert 'custom-protocol' in producers['windows_gui']['features']
    assert len(plan['expected_unit_tests']) == 25 and len(plan['expected_stdio_tests']) == 1
    assert native['native_test_names'] == sorted(plan['expected_unit_tests'] + plan['expected_stdio_tests'])
    worker = native['workers']['linux']
    assert worker['producer_fresh'] is False
    assert worker['producer_executable'] == producers['linux_worker']['executable']
    assert worker['sha256'] != control.HELPER, 'Candidate reused the unchanged baseline helper'
    kernel, = [item for item in native['kernel_proofs'] if item['platform'] == 'linux']
    assert kernel['sha256'] == worker['sha256'] and kernel['exit'] == 0
    assert kernel['hello']['protocol'] == 1 and kernel['hello']['os'] == 'linux'
    assert kernel['exact_actor_absent']
    assert len(kernel['expected']) == 30 and kernel['result']['metadata'] == kernel['expected']
    refs = json.loads((control.BASE / 'workload.json').read_text())['refs']
    comparisons = kernel['result']['comparisons']
    assert [(item['left'], item['right']) for item in comparisons] == [(refs[0], refs[1]), (refs[1], refs[2]), (refs[0], refs[2])]
    assert all(len(item['metadata']) == 30 and item['metadata'] == item['expected'] for item in comparisons)
    gui = native['windows_gui']
    assert gui['embedded_helper_verified'] and gui['renderer'] == 'production default'
    assert gui['static_crt_import_check'] and gui['producer_fresh'] is False
    assert gui['producer_executable'] == producers['windows_gui']['executable']
    assert gui['embedded_helper_sha256'] == worker['sha256']
    for platform, old_name in [('linux', 'wsl'), ('windows', 'windows')]:
        for name, values in native['fixture_after'][platform]['files'].items():
            prior = baseline['fixture_guards'][old_name][Path(name).name]
            assert values == {'sha256': prior['sha256'], 'size': prior['bytes'],
                              'mtime_ns': prior['mtime_ns'], 'inode': prior['inode'], 'mode': prior['mode']}
    assert gui['path'] == '/mnt/c/' + plan['windows_binary'][3:]
    b = {'label': plan['label'], 'source': str(HERE / 'source'), 'source_hash': SOURCE,
         'binary': str(PureWindowsPath(plan['windows_binary'])), 'binary_sha256': gui['sha256'],
         'helper_sha256': worker['sha256'], 'protocol': 1}
    result.update(native_build_ready=True, native_build_record_sha256=sha(NATIVE),
                  native_workers={'linux': worker}, native_gui_embeddings={'windows_gui': gui},
                  variants={'A': a, 'B': b})
    return result


control.prepare = prepare

if __name__ == '__main__':
    current = prepare()
    control.score.atomic_json(OUT / 'plan.json', current)
    if not current.get('native_build_ready'):
        if '--release' in sys.argv:
            raise SystemExit('Completed matching protocol-1 GNU worker/Windows GUI build is required before runtime')
        print(json.dumps(current, indent=2))
    else:
        raise SystemExit(control.main())
