#!/usr/bin/env python3
"""Prepare the remaining WSL/ext4 control; VM work requires explicit release."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'build/autoresearch/wsl-boundary'
PROFILE = '/home/max/benchmarks/branchline-boundary/profiles/baseline-compat-wsl-linux'
CASE = 'wsl_linux'
HOST_PORT = 19227


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ab = load('existing_status_ab', BASE / 'status-gui-ab.py')
transport = load('proven_status_mux', ROOT / 'build/experiments/status-windows-controls/run.py')
ab.CASE, ab.PROFILE = CASE, PROFILE
transport.HOST_PORT = HOST_PORT
# Reuse run_one unchanged except for its output-label spelling.
body = inspect.getsource(ab.run_one)
assert body.count('-wsl-windows-{stamp}-') == 1
assert body.count('"19225"') == 1
exec(body.replace('-wsl-windows-{stamp}-', '-wsl-linux-{stamp}-').replace('"19225"', repr(str(HOST_PORT))), ab.__dict__)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare():
    versions = ab.variants()
    for key, expected_gui, expected_helper in [
        ('A', '78106ff431e6433195867048f5fae946bb1e63cc0f04f23d668be32956c444c4',
         '6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'),
        ('B', 'dc75494705df50590e744c62699dbb5ad849553c6ff4c7f7a0c7b659462b603a',
         '8fafdb059c64cf88d7ab5815f3ca20af8b80e16aa7eed52be691813dcc8f16c3'),
    ]:
        item = versions[key]
        built = json.loads(Path(item['build_record']).read_text())
        helper = built['embedded_helper'] if key == 'A' else built['windows_worker']
        assert item['binary_sha256'] == expected_gui and built['linux_gui']['embedded_helper_verified']
        assert helper['sha256'] == expected_helper
        item['embedded_helper'] = helper
    seed_path = BASE / 'seed-baseline-compat-wsl-linux/verdict.json'
    seed = json.loads(seed_path.read_text())
    assert seed['valid'] and seed['setup_complete'] and seed['case'] == CASE
    assert seed['launch']['profile'] == PROFILE and len(seed['comments']) == 2
    assert {note['body'] for note in seed['comments']} == {ab.score.BRANCH_BODY, ab.score.WORKTREE_BODY}
    manifest, manifest_hash = ab.score.load_manifest(BASE / 'workload.json')
    return {'status': 'prepared-only-no-VM-or-port-access', 'case': CASE, 'profile': PROFILE,
            'contract_sha256': ab.CONTRACT, 'variants': versions, 'seed_verdict': str(seed_path),
            'seed_sha256': sha(seed_path), 'comments': seed['comments'],
            'manifest_sha256': manifest_hash, 'fixture_sha256': manifest['git_state_sha256'],
            'order': ['A1:3', 'B1:3', 'A2:3', 'B2:3', 'A3:20', 'B3:20'],
            'performance_early_gate': False, 'ports': {'host': HOST_PORT, 'driver': 29225, 'mcp': 28867},
            'measurement': 'Canonical welcome async-error readiness, measured Open, all six actions, strict native content and two frames.',
            'renderer_and_mcp': 'Unchanged canonical Linux launcher; no app environment or renderer overrides.',
            'transport': 'One private master/forward; task-local host ssh wrapper selects it, forbids fresh TCP fallback and never exports host PATH.',
            'control': 'Measure the 10% regression guard; inactive opposite-OS helpers do not establish no-regression.',
            'runtime_release': 'VM WSL STATUS CONTROL RELEASED', 'runner_sha256': sha(Path(__file__)),
            'existing_runner_sha256': sha(BASE / 'status-gui-ab.py'),
            'transport_helper_sha256': sha(ROOT / 'build/experiments/status-windows-controls/run.py')}


def stop_exact(record, log):
    script = "import json,time,socket,os\nnamespace={'__name__':'frozen_campaign_launcher'}\n"
    script += 'exec(' + repr(ab.LAUNCHER.read_text()) + ',namespace)\n'
    script += 'expected=' + repr(record) + '\nwrapper=' + repr(str(wrapper_directory)) + '\n'
    script += r'''
actual=json.loads((namespace['Path'](expected['profile'])/'app.json').read_text())
keys=('binary','binary_sha256','source_hash','profile','port','mcp_port','session','app_process','driver_process','supervisor_pid')
assert all(actual.get(key)==expected.get(key) for key in keys),'Profile ownership changed; refusing cleanup'
ids=[expected['app_process'],expected['driver_process']]
ids+=namespace['profile_processes'](namespace['Path'](expected['binary']),namespace['Path'](expected['profile']))
supervisor=namespace['process_info'](expected['supervisor_pid'])
if supervisor:ids.append(supervisor)
leaked=[]
for item in ids:
 path=namespace['Path']('/proc')/str(item['pid'])/'environ'
 if path.exists() and wrapper.encode() in path.read_bytes():leaked.append(item)
stopped=namespace['stop_record'](expected)
deadline=time.monotonic()+15
while True:
 live=[item for item in ids if namespace['process_info'](item['pid'])=={key:item[key] for key in ('pid','start_ticks','binary')}]
 ports=[]
 for port in (expected['port'],expected['mcp_port']):
  try:
   with socket.socket() as check:check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);check.bind(('127.0.0.1',port))
  except OSError:ports.append(port)
 if not live and not ports:break
 if time.monotonic()>=deadline:raise RuntimeError('Owned actors or ports remain: '+repr((live,ports)))
 time.sleep(.05)
print(json.dumps(dict(exact_launch_cleanup=stopped,observed_identities=ids,exact_owned_processes_absent=True,ports_free=True,host_wrapper_absent_from_vm_environment=not leaked)),flush=True)
assert not leaked,'Host wrapper PATH leaked into VM environment'
'''
    command = 'MSYS_NO_PATHCONV=1 ' + shlex.join([
        'wsl.exe', '-d', 'Ubuntu-26.04', '-u', 'max', '--exec', '/usr/bin/python3', '-'])
    with log.open('w') as stream:
        subprocess.run([*transport.ssh_client(), command], input=script, text=True,
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=45)


ab.stop_exact = stop_exact
wrapper_directory = None


def main():
    global wrapper_directory
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release')
    args = parser.parse_args()
    plan = prepare()
    ab.write_json(HERE / 'plan.json', plan)
    if args.release != plan['runtime_release']:
        if args.release:
            parser.error('Wait for root: ' + plan['runtime_release'])
        print(json.dumps(plan, indent=2))
        return 0
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = HERE / ('run-' + stamp)
    output.mkdir()
    state_path = output / 'state.json'
    state = {**plan, 'status': 'running', 'pid': os.getpid(), 'start_ticks': transport.start_ticks(os.getpid()),
             'started_unix': time.time(), 'runs': []}
    save = lambda: ab.write_json(state_path, state)
    save()
    print(json.dumps({'state': str(state_path), 'pid': os.getpid()}), flush=True)
    master = None
    temporary = None
    original_path = os.environ['PATH']
    failure = None
    try:
        transport.host_port_free()
        temporary = Path(tempfile.mkdtemp(prefix='status-wsl-', dir='/tmp'))
        transport.CONTROL_SOCKET = temporary / 'ssh.sock'
        command = [*transport.SSH, '-M', '-S', str(transport.CONTROL_SOCKET), '-o', 'ControlPersist=no',
                   '-N', '-o', 'ExitOnForwardFailure=yes', '-L', f'127.0.0.1:{HOST_PORT}:127.0.0.1:29225', 'windows-vm']
        with (output / 'master.stdout').open('w') as stdout, (output / 'master.stderr').open('w') as stderr:
            master = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        state['master'] = {'pid': master.pid, 'start_ticks': transport.start_ticks(master.pid),
                           'argv': command, 'socket': str(transport.CONTROL_SOCKET)}
        save()
        deadline = time.monotonic()+15
        while not transport.CONTROL_SOCKET.is_socket():
            assert master.poll() is None, 'Private master exited during authentication'
            if time.monotonic()>=deadline:raise TimeoutError('Private master socket was not ready')
            time.sleep(.05)
        checked = subprocess.run([*transport.ssh_client()[:-1], '-O', 'check', 'windows-vm'],
                                 capture_output=True, text=True, timeout=5)
        state['master_check'] = {'exit': checked.returncode, 'stdout': checked.stdout, 'stderr': checked.stderr}
        assert checked.returncode==0, checked.stderr
        wrapper_directory = temporary / 'bin'
        wrapper_directory.mkdir()
        wrapper = wrapper_directory / 'ssh'
        code = '#!' + sys.executable + '\nimport os,pathlib,sys\na=sys.argv[1:]\n'
        code += 'socket=' + repr(str(transport.CONTROL_SOCKET)) + '\n'
        code += "if len(a)>=7 and a[0]=='-F' and a[2]=='-o' and a[4]=='-o' and a[6]=='windows-vm':\n"
        code += " if not pathlib.Path(socket).is_socket():raise SystemExit('Owned master missing; refusing TCP fallback')\n"
        code += " a=['-S',socket,'-o','ControlMaster=no','-o','ProxyCommand=/usr/bin/false',*a]\n"
        code += "elif 'windows-vm' in a:raise SystemExit('Unexpected canonical SSH argument layout')\n"
        code += "os.execv('/usr/bin/ssh',['/usr/bin/ssh',*a])\n"
        wrapper.write_text(code)
        wrapper.chmod(0o700)
        state['host_wrapper'] = {'path': str(wrapper), 'sha256': sha(wrapper)}
        os.environ['PATH'] = str(wrapper_directory)+os.pathsep+original_path
        state['fixture_before'] = transport.fixture_snapshot(output / 'fixture-before.json')
        assert {value['sha256'] for value in state['fixture_before'].values()}=={plan['fixture_sha256']}
        save()
        for key, number, reps in [('A',1,3),('B',1,3),('A',2,3),('B',2,3),('A',3,20),('B',3,20)]:
            assert master.poll() is None, 'Private master exited'
            assert prepare()==plan, 'Source, build, seed or controller identity changed'
            ab.run_one(key, number, reps, plan['variants'], stamp, state, state_path)
        state['final20']={item['variant']:item['action_and_ipc_summary'] for item in state['runs'] if item['number']==3}
    except BaseException as error:
        failure=error
        state.update(error=str(error),traceback=traceback.format_exc())
    finally:
        if 'fixture_before' in state and all(item.get('cleanup_complete') for item in state['runs']):
            try:
                state['fixture_after']=transport.fixture_snapshot(output / 'fixture-after.json')
                assert state['fixture_after']==state['fixture_before'],'Fixture changed'
            except BaseException as error:
                state['fixture_after_error']=str(error);failure=failure or error
        elif state['runs']:state['fixture_after_deferred']='Recover exact pending actors before further VM action'
        os.environ['PATH']=original_path
        if master is not None:
            try:
                if master.poll() is None and transport.CONTROL_SOCKET.is_socket():
                    exited=subprocess.run([*transport.ssh_client()[:-1],'-O','exit','windows-vm'],capture_output=True,text=True,timeout=5)
                    state['master_exit_request']={'exit':exited.returncode,'stdout':exited.stdout,'stderr':exited.stderr}
            except Exception as error:state['master_exit_request_error']=str(error)
            try:
                try:state['master_exit']=master.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    master.terminate()
                    try:state['master_exit']=master.wait(timeout=5)
                    except subprocess.TimeoutExpired:master.kill();state['master_exit']=master.wait(timeout=5)
                transport.host_port_free()
                assert not transport.CONTROL_SOCKET.exists(),'Control socket remains'
                state.update(host_port_free=True,control_socket_absent=True)
                if wrapper_directory is not None:
                    (wrapper_directory/'ssh').unlink();wrapper_directory.rmdir()
                temporary.rmdir()
            except BaseException as error:state['master_cleanup_error']=str(error);failure=failure or error
        elif temporary is not None:
            try:temporary.rmdir()
            except BaseException as error:state['master_cleanup_error']=str(error);failure=failure or error
        state.update(status='stopped-on-error-no-retry' if failure else 'complete-valid-awaiting-10percent-review',finished_unix=time.time())
        save()
    if failure:raise failure
    return 0


if __name__=='__main__':raise SystemExit(main())
