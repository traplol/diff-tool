#!/usr/bin/env python3
"""Prepare locally; run the fixed Windows status A/B only after runtime release."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import shlex
import socket
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'build/autoresearch/wsl-boundary'
TOOLS = ROOT / 'tools/autoresearch/wsl-boundary'
BUILD_STATE = BASE / 'windows-controls-b2de070-20261125T213427886542Z/remote-evidence/state.json'
sys.path.insert(0, str(TOOLS))
import launch
import score
from driver import CdpDriver

spec = importlib.util.spec_from_file_location('existing_status_ab', BASE / 'status-gui-ab.py')
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)
CONTRACT = '3db306b466166cb39b8c5a9dc27a9739b16df52fa9f83d32bd6656f226026b04'
HELPER = '328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa'
HOST_PORT, CDP_PORT, MCP_PORT = 19223, 29223, 28865
SSH = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
CASES = {
    'windows_windows': ('candidate-scoped-v2-windows-windows', 'seed-candidate-scoped-v2-windows-windows'),
    'windows_linux': ('baseline-windows-linux', 'seed-windows-linux-02'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def start_ticks(pid):
    return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]


def prepare():
    assert score.contract_identity()['sha256'] == CONTRACT, 'Canonical controls changed'
    manifest, manifest_hash = score.load_manifest(BASE / 'workload.json')
    builds = json.loads(BUILD_STATE.read_text())
    assert builds['status'] == 'complete-build-proof-passed-no-GUI-execution'
    assert builds['plan']['contract_sha256'] == CONTRACT
    assert builds['plan']['workload_manifest_sha256'] == manifest_hash
    assert builds['fixture_guards_before'] == builds['fixture_guards_after']
    assert builds['helper']['sha256'] == HELPER
    for values in [builds['fixture_fingerprints_before'], builds['fixture_fingerprints_after']]:
        assert {item['sha256'] for item in values.values()} == {manifest['git_state_sha256']}
    variants = {}
    for key, label, expected in [
        ('A', 'checkpoint-b2de070', '56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272'),
        ('B', 'candidate-stateless-status-b2de070', 'd5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb'),
    ]:
        built, = [item for item in builds['builds'] if item['label'] == label]
        identity = score.source_identity(BASE / (label + '-source'))
        assert identity == built['source'] == built['source_after']
        assert identity['source_hash'] == expected
        gui = built['windows_gui']
        assert built['exit'] == 0 and gui['embedded_helper_verified'] and gui['static_crt_import_check']
        assert gui['embedded_helper_sha256'] == HELPER
        variants[key] = {'label': label, 'source': str(BASE / (label + '-source')),
                         'source_hash': expected, 'binary': gui['windows_path'],
                         'binary_sha256': gui['sha256'], 'helper_sha256': HELPER}
    cases = {}
    for case, (profile_name, seed_name) in CASES.items():
        seed_path = BASE / seed_name / 'verdict.json'
        seed = json.loads(seed_path.read_text())
        profile = str(PureWindowsPath('C:/Users/max/branchline-bench/profiles') / profile_name)
        assert seed['valid'] and seed['setup_complete'] and seed['case'] == case
        assert len(seed['comments']) == 2
        assert {note['body'] for note in seed['comments']} == {score.BRANCH_BODY, score.WORKTREE_BODY}
        assert PureWindowsPath(seed['launch']['profile']) == PureWindowsPath(profile)
        assert profile.isascii()
        cases[case] = {'profile': profile, 'seed_verdict': str(seed_path), 'seed_sha256': sha(seed_path),
                       'comments': seed['comments'], 'repository': manifest['paths'][case]}
    return {'status': 'prepared-only-no-VM-or-port-access', 'contract_sha256': CONTRACT,
            'build_state': str(BUILD_STATE), 'build_state_sha256': sha(BUILD_STATE),
            'variants': variants, 'cases': cases, 'fixture_sha256': manifest['git_state_sha256'],
            'fixture_guards': builds['fixture_guards_after'], 'manifest_sha256': manifest_hash,
            'ports': {'host_loopback': HOST_PORT, 'windows_cdp': CDP_PORT, 'windows_mcp': MCP_PORT},
            'order_per_case': ['A1:3', 'B1:3', 'A2:3', 'B2:3', 'A3:20', 'B3:20'],
            'case_order': list(CASES), 'performance_early_gate': False,
            'measurement': 'Canonical Open and all six actions; completed welcome startup error; no warmup or cache flush.',
            'profiles': 'Reuse the existing two-comment profiles directly; no copies, seeding or helper preparation.',
            'runtime_release': 'VM WINDOWS STATUS RUNTIME RELEASED',
            'runner_sha256': sha(Path(__file__)),
            'summary_helper_sha256': sha(BASE / 'status-gui-ab.py')}


def host_port_free():
    with socket.socket() as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        connection.bind(('127.0.0.1', HOST_PORT))


def fixture_snapshot(output):
    script = "namespace={'__name__':'frozen_workload'}\nexec(" + repr((TOOLS / 'workload.py').read_text()) + ",namespace)\n"
    script += """
import hashlib,json
original=namespace['git']
namespace['git']=lambda root,*args,**kw:original(root,'-c','diff.autoRefreshIndex=false',*args,**kw)
def guards(root):
 result={}
 for name in ('index','config','HEAD'):
  path=root/'.git'/name
  a=path.stat();value=hashlib.sha256(path.read_bytes()).hexdigest();b=path.stat()
  fields=lambda st:dict(bytes=st.st_size,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns,inode=st.st_ino,device=st.st_dev,mode=st.st_mode)
  assert fields(a)==fields(b),'Fixture changed during read'
  result[name]=dict(sha256=value,**fields(b))
 return result
result={}
for platform,key in [('wsl','LINUX_ROOT'),('windows','WINDOWS_ROOT')]:
 root=namespace[key];before=guards(root);fingerprint=namespace['fingerprint'](root);after=guards(root)
 assert before==after,'Fixture read changed index/config/HEAD'
 result[platform]=dict(sha256=fingerprint,guards=after)
print(json.dumps(result))
"""
    command = [*SSH, 'windows-vm', 'MSYS_NO_PATHCONV=1 ' + shlex.join([
        'wsl.exe', '-d', 'Ubuntu-26.04', '-u', 'max', '--exec', '/usr/bin/python3', '-'])]
    result = subprocess.run(command, input=script, text=True, capture_output=True, timeout=900)
    output.with_suffix('.stdout').write_text(result.stdout)
    output.with_suffix('.stderr').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError('Fixture check failed; inspect ' + str(output))
    value = json.loads(result.stdout)
    score.atomic_json(output, value)
    return value


def stop_exact(record):
    guard = r'''
$expected=$params.expected
$actual=Get-Content $record -Raw | ConvertFrom-Json
foreach($key in @('pid','created','binary','binary_sha256','source_hash','profile','cdp_port','mcp_port')) {
    if($actual.$key -ne $expected.$key){throw "Profile ownership changed: $key"}
}
$owned=@(Get-CimInstance Win32_Process | Where-Object {
    $_.ParentProcessId -eq $expected.pid -and $_.CreationDate -ge [DateTime]::Parse($expected.created)
} | ForEach-Object {@{pid=$_.ProcessId;binary=$_.ExecutablePath;created=$_.CreationDate.ToString('o')}})
$stopResult=& {
'''
    verify = r'''
}
$deadline=[DateTime]::UtcNow.AddSeconds(30)
do {
    $live=@()
    foreach($item in (@(@{pid=$expected.pid;binary=$expected.binary;created=$expected.created})+$owned)) {
        $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$item.pid)
        if($process -and $process.ExecutablePath -eq $item.binary -and $process.CreationDate.ToString('o') -eq $item.created){$live+=$item}
    }
    $ports=@(Get-NetTCPConnection -State Listen -LocalPort @($expected.cdp_port,$expected.mcp_port) -ErrorAction SilentlyContinue)
    if(-not $live -and -not $ports){break}
    Start-Sleep -Milliseconds 100
} while([DateTime]::UtcNow -lt $deadline)
if($live -or $ports){throw 'Exact owned app/children or CDP/MCP ports remain live; inspect without relaunching'}
@{canonical_stop=($stopResult|ConvertFrom-Json);observed_children=$owned;exact_owned_processes_absent=$true;ports_free=$true}|ConvertTo-Json -Depth 8 -Compress
'''
    return launch.remote('windows-vm', guard + launch.STOP + verify,
                         {'profile': record['profile'], 'expected': record})


def run_one(case, variant, number, repetitions, plan, directory, state, save):
    version, profile = plan['variants'][variant], plan['cases'][case]['profile']
    label = f'{case}-{variant}{number}'
    output = directory / label
    output.mkdir()
    item = {'case': case, 'variant': variant, 'number': number, 'repetitions': repetitions,
            'status': 'launching', 'directory': str(output), 'started_unix': time.time()}
    state['runs'].append(item)
    save()
    params = {'profile': profile, 'binary': version['binary'],
              'repo': str(PureWindowsPath('C:/Users/max/branchline-bench/profiles/baseline-windows-linux/welcome')),
              'cdp_port': CDP_PORT, 'mcp_port': MCP_PORT, 'source_hash': version['source_hash']}
    item['launch_parameters'] = params
    assert all(str(value).isascii() for value in params.values()), 'Canonical launcher parameters must remain ASCII'
    record = None
    try:
        record = launch.remote('windows-vm', launch.START, params)
        item['launch'] = record
        score.atomic_json(output / 'launch.json', record)
        save()
        assert record['binary_sha256'] == version['binary_sha256'] and record['source_hash'] == version['source_hash']
        assert PureWindowsPath(record['profile']) == PureWindowsPath(profile)
        driver = None
        deadline = time.monotonic() + 90
        while driver is None:
            try:
                driver = CdpDriver(f'http://127.0.0.1:{HOST_PORT}', timeout=10)
            except Exception as error:
                item.setdefault('transport_startup', []).append(str(error))
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.25)
        try:
            driver.timeout = 190
            driver.wait(score.WELCOME_READY, timeout=180)
            info = driver.info()
            assert info['visible'] == 'visible'
            score.atomic_json(output / 'welcome-ready.json', info)
        except BaseException:
            try:
                driver.screenshot(output / 'startup-failure.png')
                score.atomic_json(output / 'startup-failure.json', driver.info())
            except Exception as error:
                item['startup_capture_error'] = str(error)
            raise
        finally:
            driver.close()
        item.update(status='scoring', welcome_startup_error_observed=True)
        command = [sys.executable, str(TOOLS / 'score.py'), '--source', version['source'],
                   '--run-dir', str(output / 'score'), '--label', version['label'], '--manifest',
                   str(BASE / 'workload.json'), '--case', case, '--launch-record', str(output / 'launch.json'),
                   '--cdp', f'http://127.0.0.1:{HOST_PORT}', '--repetitions', str(repetitions)]
        item['score_command'] = command
        save()
        with (output / 'score.stdout').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        verdict = json.loads((output / 'score/verdict.json').read_text())
        item.update(score_exit=result.returncode, verdict=str(output / 'score/verdict.json'),
                    samples=str(output / 'score/samples.jsonl'))
        assert result.returncode == 0 and verdict['valid'], verdict.get('error')
        assert verdict['contract']['sha256'] == CONTRACT and verdict['case'] == case
        assert verdict['repetitions'] == repetitions
        assert verdict['source_hash'] == version['source_hash'] and verdict['binary_sha256'] == version['binary_sha256']
        samples = ab.samples_for(item)
        score.validate_samples(samples, repetitions)
        item.update(actions=verdict['actions'], action_and_ipc_summary=ab.action_summary(samples), status='valid')
    except BaseException as error:
        item.update(status='failed-no-retry', error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        save()
        if record is not None:
            try:
                cleanup = stop_exact(record)
                score.atomic_json(output / 'cleanup.json', cleanup)
                item.update(cleanup_complete=True, cleanup=cleanup)
                if item['status'] == 'valid':
                    item['status'] = 'complete-valid-stopped'
            except BaseException as error:
                item.update(cleanup_complete=False, cleanup_error=str(error))
                save()
                raise
        else:
            item.update(cleanup_complete=False, ownership_observation='Launch record unavailable; inspect profile before any retry')
        item['finished_unix'] = time.time()
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release')
    args = parser.parse_args()
    plan = prepare()
    score.atomic_json(HERE / 'plan.json', plan)
    if args.release != plan['runtime_release']:
        if args.release:
            parser.error('Wait for root: ' + plan['runtime_release'])
        print(json.dumps(plan, indent=2))
        return 0
    directory = HERE / dt.datetime.now(dt.timezone.utc).strftime('run-%Y%m%dT%H%M%S%fZ')
    directory.mkdir()
    state = {**plan, 'status': 'running', 'pid': os.getpid(), 'started_unix': time.time(), 'runs': []}
    state['start_ticks'] = start_ticks(os.getpid())
    save = lambda: score.atomic_json(directory / 'state.json', state)
    save()
    print(json.dumps({'state': str(directory / 'state.json'), 'pid': os.getpid()}), flush=True)
    forward = None
    failure = None
    try:
        state['fixture_before'] = fixture_snapshot(directory / 'fixture-before.json')
        for platform, fixture in state['fixture_before'].items():
            assert fixture['sha256'] == plan['fixture_sha256']
            assert fixture['guards'] == plan['fixture_guards'][platform], 'Fixture differs from completed control build'
        host_port_free()
        command = [*SSH, '-N', '-o', 'ExitOnForwardFailure=yes', '-L',
                   f'127.0.0.1:{HOST_PORT}:127.0.0.1:{CDP_PORT}', 'windows-vm']
        with (directory / 'tunnel.stdout').open('w') as stdout, (directory / 'tunnel.stderr').open('w') as stderr:
            forward = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        state['tunnel'] = {'pid': forward.pid, 'start_ticks': start_ticks(forward.pid), 'argv': command}
        save()
        for case in plan['case_order']:
            for variant, number, repetitions in [('A', 1, 3), ('B', 1, 3), ('A', 2, 3), ('B', 2, 3), ('A', 3, 20), ('B', 3, 20)]:
                assert forward.poll() is None, 'Owned CDP tunnel exited'
                assert score.contract_identity()['sha256'] == CONTRACT
                assert prepare() == plan, 'Source/build/seed identity changed'
                run_one(case, variant, number, repetitions, plan, directory, state, save)
        state['final_20_repetitions'] = {case: {run['variant']: run['action_and_ipc_summary']
            for run in state['runs'] if run['case'] == case and run['number'] == 3} for case in CASES}
        state['fresh_process_open_ms'] = {case: {key: [run['actions']['open']['first_use_ms'] for run in state['runs']
            if run['case'] == case and run['variant'] == key] for key in ['A', 'B']} for case in CASES}
    except BaseException as error:
        failure = error
        state.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if forward is not None:
            try:
                if forward.poll() is None:
                    forward.terminate()
                try:
                    state['tunnel_exit'] = forward.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    forward.kill()
                    state['tunnel_exit'] = forward.wait(timeout=5)
                host_port_free()
                state['host_loopback_port_free'] = True
            except BaseException as error:
                state['tunnel_cleanup_error'] = str(error)
                failure = failure or error
        if 'fixture_before' in state:
            try:
                state['fixture_after'] = fixture_snapshot(directory / 'fixture-after.json')
                assert state['fixture_after'] == state['fixture_before'], 'Kernel fixture changed'
            except BaseException as error:
                state['fixture_after_error'] = str(error)
                failure = failure or error
        state.update(status='stopped-on-error-no-retry' if failure else 'complete-valid-awaiting-charter-review',
                     finished_unix=time.time())
        save()
    if failure:
        raise failure
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
