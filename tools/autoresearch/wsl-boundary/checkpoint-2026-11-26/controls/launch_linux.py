"""Supervise an isolated native WSLg Branchline/WebKitWebDriver session over SSH.

`start` keeps its SSH connection in the foreground until `stop` deletes the
owned WebDriver session and stops the recorded processes. Do not background it
with nohup inside a short SSH command. The app first opens an owned non-Git
welcome directory, so choosing the measured repository also includes its real
native open and MCP startup. No backend is mocked.

Forward host loopback to Windows localhost:<port> with SSH -L. WSL localhost
forwarding makes the actual Linux WebKitWebDriver available there. The profile
owns config/, data/, cache/, welcome/, logs and app.json. Rendering defaults and
MCP autostart remain enabled. Only owned process identities are stopped.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib import request


def process_info(pid):
    """Identity includes kernel start ticks, so a reused PID is never enough."""
    directory = Path('/proc') / str(pid)
    try:
        fields = (directory / 'stat').read_text().rsplit(') ', 1)[1].split()
        return {
            'pid': int(pid), 'start_ticks': fields[19],
            'binary': str((directory / 'exe').resolve(strict=True)),
        }
    except (OSError, ValueError, IndexError):
        return None


def profile_processes(binary, profile):
    expected = ('XDG_CONFIG_HOME=' + str(profile / 'config')).encode()
    result = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        identity = process_info(directory.name)
        if not identity or identity['binary'] != str(binary):
            continue
        try:
            if expected not in (directory / 'environ').read_bytes().split(b'\0'):
                continue
            identity['args'] = [part.decode() for part in
                                (directory / 'cmdline').read_bytes().split(b'\0') if part]
            result.append(identity)
        except (OSError, UnicodeDecodeError):
            continue
    return result


def terminate(identity):
    current = process_info(identity['pid'])
    if not current:
        return False
    if current != {key: identity[key] for key in ('pid', 'start_ticks', 'binary')}:
        raise RuntimeError('Refusing to stop a reused or changed benchmark process')
    try:
        os.kill(identity['pid'], signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True


def webdriver(port, method, path, data=None, *, timeout=180):
    body = json.dumps(data).encode() if data is not None else None
    message = request.Request(f'http://127.0.0.1:{port}' + path, method=method,
                              data=body, headers={'Content-Type': 'application/json'})
    with request.urlopen(message, timeout=timeout) as response:
        return json.load(response)['value']


def stop_record(record):
    stopped = []
    # Session deletion closes the actual GTK app through its WebDriver lifecycle.
    try:
        webdriver(record['port'], 'DELETE', '/session/' + record['session'], timeout=10)
    except Exception:
        pass
    for identity in [record.get('app_process'), record.get('driver_process')]:
        if identity and terminate(identity):
            stopped.append(identity['pid'])
    # MCP deliberately has a separate process group. Identify its unique profile
    # and port, rather than killing all Branchline processes or all descendants.
    for identity in profile_processes(Path(record['binary']), Path(record['profile'])):
        args = identity['args']
        if '--mcp' in args and '--port' in args:
            index = args.index('--port') + 1
            if index < len(args) and args[index] == str(record['mcp_port']):
                if terminate(identity):
                    stopped.append(identity['pid'])
    return stopped


def supervise(params):
    profile = Path(params['profile']).resolve()
    binary = Path(params['binary']).resolve(strict=True)
    driver_binary = Path(params['driver_binary']).resolve(strict=True)
    for port in (params['port'], params['mcp_port']):
        with socket.socket() as check:
            check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            check.bind(('127.0.0.1', port))
    profile.mkdir(parents=True, exist_ok=True)
    record_path = profile / 'app.json'
    if record_path.exists():
        old = json.loads(record_path.read_text())
        if old.get('driver_process') and process_info(old['driver_process']['pid']):
            raise RuntimeError('This profile still has a live recorded driver')
    for name in ('config/branchline', 'data', 'cache', 'welcome'):
        (profile / name).mkdir(parents=True, exist_ok=True)
    config_path = profile / 'config/branchline/config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    config.update(mcp_auto_start=True, hardware_acceleration=True, mcp_port=params['mcp_port'])
    config_path.write_text(json.dumps(config, indent=2))
    env = dict(os.environ, DISPLAY=':0', GDK_BACKEND='x11',
               TAURI_WEBVIEW_AUTOMATION='true',
               XDG_CONFIG_HOME=str(profile / 'config'),
               XDG_DATA_HOME=str(profile / 'data'),
               XDG_CACHE_HOME=str(profile / 'cache'),
               BRANCHLINE_MCP_PORT=str(params['mcp_port']))
    record = None
    with (profile / 'webdriver.log').open('w') as log:
        process = subprocess.Popen([str(driver_binary), f"--port={params['port']}"],
                                   env=env, cwd=profile / 'welcome', stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError('WebKitWebDriver exited: ' + (profile / 'webdriver.log').read_text()[-4000:])
                try:
                    webdriver(params['port'], 'GET', '/status', timeout=1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('WebKitWebDriver did not expose its status endpoint')
                    time.sleep(.05)
            info = webdriver(params['port'], 'POST', '/session', {
                'capabilities': {'alwaysMatch': {'webkitgtk:browserOptions': {
                    'binary': str(binary), 'args': [str(profile / 'welcome')],
                }}},
            })
            apps = [item for item in profile_processes(binary, profile) if '--mcp' not in item['args']]
            if len(apps) != 1:
                raise RuntimeError(f'Expected one owned native app process, found {len(apps)}')
            with binary.open('rb') as source:
                binary_hash = hashlib.file_digest(source, 'sha256').hexdigest()
            record = {
                'binary': str(binary), 'binary_sha256': binary_hash,
                'source_hash': params.get('source_hash'), 'profile': str(profile),
                'port': params['port'], 'mcp_port': params['mcp_port'], 'session': info['sessionId'],
                'pid': apps[0]['pid'], 'app_process': apps[0],
                'driver_process': process_info(process.pid), 'supervisor_pid': os.getpid(),
                'display': env['DISPLAY'], 'gdk_backend': env['GDK_BACKEND'],
            }
            record_path.write_text(json.dumps(record, indent=2))
            print(json.dumps(record), flush=True)
            process.wait()
        finally:
            if record:
                stop_record(record)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def remote_main(params):
    if params['action'] == 'start':
        def interrupted(signum, frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        supervise(params)
    else:
        profile = Path(params['profile']).resolve()
        record = json.loads((profile / 'app.json').read_text())
        if record['profile'] != str(profile):
            raise RuntimeError('Profile ownership record does not match')
        print(json.dumps({'profile': str(profile), 'stopped_pids': stop_record(record)}), flush=True)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--remote':
        remote_main(json.loads(base64.b64decode(sys.argv[2])))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('--host', default='windows-vm')
    parser.add_argument('--distribution', default='Ubuntu-26.04')
    parser.add_argument('--user', default='max')
    parser.add_argument('--binary')
    parser.add_argument('--driver-binary', default='/usr/bin/WebKitWebDriver')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--port', type=int, default=29225)
    parser.add_argument('--mcp-port', type=int, default=28867)
    parser.add_argument('--source-hash', help='SHA-256 source manifest identity of the packaged build')
    parser.add_argument('--record', type=Path, help='Also write the launch record to this host-local path')
    args = parser.parse_args()
    if not args.profile.startswith('/'):
        parser.error('--profile must be an absolute WSL path')
    if args.action == 'start' and not args.binary:
        parser.error('start requires --binary')
    if args.source_hash and not re.fullmatch('[0-9a-f]{64}', args.source_hash):
        parser.error('--source-hash must be a lowercase SHA-256 identity')
    if not all(1024 <= port <= 65535 for port in (args.port, args.mcp_port)) or args.port == args.mcp_port:
        parser.error('Use different valid unprivileged driver and MCP ports')
    params = {key: value for key, value in vars(args).items()
              if key not in {'host', 'distribution', 'user', 'record'}}
    payload = base64.b64encode(json.dumps(params).encode()).decode()
    # POSIX quoting protects parameters in the existing Git Bash SSH shell;
    # MSYS_NO_PATHCONV prevents rewriting the Linux Python executable path.
    import shlex
    command = 'MSYS_NO_PATHCONV=1 ' + shlex.join([
        'wsl.exe', '--distribution', args.distribution, '--user', args.user,
        '--exec', '/usr/bin/python3', '-u', '-', '--remote', payload,
    ])
    process = subprocess.Popen([
        'ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10', args.host, command,
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        process.stdin.write(Path(__file__).read_text())
        process.stdin.close()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f'WSL launcher exited without a launch record ({process.wait()})')
        record = json.loads(line)
        if args.record:
            args.record.parent.mkdir(parents=True, exist_ok=True)
            args.record.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)
        for line in process.stdout:
            print(line, end='', flush=True)
        code = process.wait()
        if code:
            raise SystemExit(code)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    main()
