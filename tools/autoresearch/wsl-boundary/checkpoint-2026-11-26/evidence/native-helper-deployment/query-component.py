#!/usr/bin/env python3
"""Exact read-only native cache-location query comparison; no builds or GUI."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

REMOTE = r'''
import base64, hashlib, json, os, pathlib, re, shutil, statistics, subprocess, time
configuration = json.loads(base64.b64decode('__CONFIG__'))
programs = {name: shutil.which(name) for name in ['powershell.exe', 'cmd.exe']}
assert all(programs.values()), programs
commands = {
    'powershell': ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', configuration['query']],
    'cmd': ['cmd.exe', '/d', '/u', '/c', 'set LOCALAPPDATA'],
}
rows = []
seen = set()
def decode(kind, output):
    if kind == 'powershell':
        value = output.decode('utf-8')
    else:
        text = output.decode('utf-16-le')
        values = [line.partition('=')[2] for line in text.splitlines()
                  if line.partition('=')[0].casefold() == 'localappdata']
        assert len(values) == 1, repr(text)
        value = values[0]
    assert re.match(r'^[A-Za-z]:[\\/]', value) and not any(c in value for c in '\r\n\0'), repr(value)
    return value
for cwd_kind, cwd in configuration['cwds'].items():
    assert pathlib.Path(cwd).is_dir(), cwd
    for pair in range(5):
        order = ['powershell', 'cmd'] if pair % 2 == 0 else ['cmd', 'powershell']
        pair_rows = []
        for kind in order:
            started_unix = time.time()
            started = time.perf_counter_ns()
            process = subprocess.Popen(commands[kind], cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            spawned = time.perf_counter_ns()
            identity = {'linux_interop_pid': process.pid, 'started_unix': started_unix}
            inspected = time.perf_counter_ns()
            try:
                proc = pathlib.Path('/proc') / str(process.pid)
                identity['linux_start_ticks'] = (proc/'stat').read_text().rsplit(') ', 1)[1].split()[19]
                identity['linux_exe'] = str((proc/'exe').resolve())
                identity['linux_cmdline_base64'] = base64.b64encode((proc/'cmdline').read_bytes()).decode()
            except (FileNotFoundError, ProcessLookupError):
                identity['proc_identity'] = 'process exited before inspection'
            identity_probe_ms = (time.perf_counter_ns() - inspected) / 1e6
            try:
                output, error = process.communicate(timeout=20)
            except BaseException:
                process.kill()
                process.communicate()
                raise
            finished = time.perf_counter_ns()
            value = decode(kind, output)
            assert process.returncode == 0, (kind, process.returncode, error)
            row = {'cwd_kind': cwd_kind, 'cwd': cwd, 'pair': pair, 'order': order,
                   'kind': kind, 'argv': commands[kind], 'identity': identity,
                   'spawn_ms': (spawned-started)/1e6, 'total_ms': (finished-started)/1e6,
                   'identity_probe_ms': identity_probe_ms, 'exit': process.returncode,
                   'stdout_base64': base64.b64encode(output).decode(),
                   'stderr_base64': base64.b64encode(error).decode(), 'decoded_path': value,
                   'first_for_command': kind not in seen, 'first_for_cwd': pair == 0}
            seen.add(kind)
            pair_rows.append(row)
            rows.append(row)
        assert pair_rows[0]['decoded_path'] == pair_rows[1]['decoded_path'], pair_rows
        for row in pair_rows:
            row['paired_output_equal'] = True
summary = {}
for cwd_kind in configuration['cwds']:
    selected = [row for row in rows if row['cwd_kind'] == cwd_kind]
    summary[cwd_kind] = {kind: {'first_ms': next(row['total_ms'] for row in selected if row['kind']==kind),
                               'median_ms': statistics.median(row['total_ms'] for row in selected if row['kind']==kind),
                               'samples_ms': [row['total_ms'] for row in selected if row['kind']==kind]}
                        for kind in commands}
    summary[cwd_kind]['paired_powershell_minus_cmd_ms'] = [
        next(row['total_ms'] for row in selected if row['pair']==pair and row['kind']=='powershell') -
        next(row['total_ms'] for row in selected if row['pair']==pair and row['kind']=='cmd')
        for pair in range(5)]
print(json.dumps({'valid': True, 'configuration': configuration, 'supervisor_pid': os.getpid(),
                  'supervisor_cwd': os.getcwd(),
                  'executables': {name: {'resolved': path, 'sha256_after_measurement': hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()}
                                  for name,path in programs.items()},
                  'timing_boundary': 'spawn through completed stdout/stderr and reaped exit; includes recorded Linux proc identity probe',
                  'caveat': 'Fresh native processes, first samples retained; not OS-cold. No environment overrides, Git commands, fixture writes, app launches or builds.',
                  'native_pid_limit': 'PID/start ticks identify WSL interop proxy; native executable path/hash and exact argv retained. No extra native process observer was run.',
                  'all_paths_equal': len({row['decoded_path'] for row in rows}) == 1,
                  'rows': rows, 'summary': summary}, indent=2), flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM COMPONENT RELEASED':
        parser.error('Only run after root grants VM COMPONENT RELEASED')
    base = Path(__file__).resolve().parent
    source = (base/'source/src-tauri/src/git/remote.rs').read_text()
    block = source[source.index('fn windows_worker_cache()'):source.index('fn windows_cache_path(')]
    query = re.search(r'"(\[Console\]::OutputEncoding[^\n]+)"', block).group(1)
    configuration = {'query': query, 'query_utf8_sha256': hashlib.sha256(query.encode()).hexdigest(),
        'remote_rs_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'app_source_hash': 'f2ffb3cc14a90caa261e53de4400177b13297f100d66f33549d41afb36c9a334',
        'cwds': {'ext4_welcome': '/home/max/benchmarks/branchline-boundary/profiles/candidate-worker-v1-wsl-windows/welcome',
                 'ntfs_kernel': '/mnt/c/Users/max/branchline-bench/kernel-windows'}}
    directory = base/'query-component-02'
    directory.mkdir(exist_ok=False)
    (directory/'configuration.json').write_text(json.dumps(configuration,indent=2)+'\n')
    script = REMOTE.replace('__CONFIG__', base64.b64encode(json.dumps(configuration).encode()).decode())
    (directory/'remote-script.py').write_text(script)
    command = 'MSYS_NO_PATHCONV=1 ' + shlex.join(['wsl.exe','--distribution','Ubuntu-26.04','--user','max',
                                               '--exec','/usr/bin/python3','-u','-'])
    result = subprocess.run(['ssh','-F',str(Path.home()/'.ssh/config'),'-o','BatchMode=yes',
                             '-o','ConnectTimeout=10','windows-vm',command], input=script,
                            capture_output=True,text=True,timeout=180)
    (directory/'stdout.log').write_text(result.stdout)
    (directory/'stderr.log').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f'Query component failed ({result.returncode}); inspect {directory}')
    data = json.loads(result.stdout)
    assert data['valid'] and data['all_paths_equal']
    (directory/'results.json').write_text(json.dumps(data,indent=2)+'\n')
    (directory/'summary.json').write_text(json.dumps({'valid':data['valid'], 'all_paths_equal':data['all_paths_equal'],
        'configuration':configuration,'summary':data['summary'],'caveat':data['caveat']},indent=2)+'\n')
    print(json.dumps(data['summary'],indent=2))


if __name__ == '__main__':
    main()
