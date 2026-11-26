
import base64, hashlib, json, os, pathlib, re, shutil, statistics, subprocess, time
configuration = json.loads(base64.b64decode('eyJxdWVyeSI6ICJbQ29uc29sZV06Ok91dHB1dEVuY29kaW5nID0gW1RleHQuVVRGOEVuY29kaW5nXTo6bmV3KCRmYWxzZSk7ICRkaXJlY3RvcnkgPSAkZW52OkxPQ0FMQVBQREFUQTsgaWYgKFtzdHJpbmddOjpJc051bGxPckVtcHR5KCRkaXJlY3RvcnkpKSB7ICRkaXJlY3RvcnkgPSBbRW52aXJvbm1lbnRdOjpHZXRGb2xkZXJQYXRoKFtFbnZpcm9ubWVudCtTcGVjaWFsRm9sZGVyXTo6TG9jYWxBcHBsaWNhdGlvbkRhdGEpIH07IFtDb25zb2xlXTo6V3JpdGUoJGRpcmVjdG9yeSkiLCAicXVlcnlfdXRmOF9zaGEyNTYiOiAiMGI0OTY1ZDRjZGI4NDgxZDMzOTcxMjhkOTAwYzEyYWVmOWFiYWQyZmIxYjA5MTVlZjVmZTllMTQyNjI0ZjllOSIsICJyZW1vdGVfcnNfc2hhMjU2IjogIjZjYWQ3ZGUxZmY5OWVhMDcxNGNlMDMyYzI4ZmFlMTk0NjNjZmZjODBlNDJhMjExMGNmZGM2MDJiYmZjYWExYzUiLCAiYXBwX3NvdXJjZV9oYXNoIjogImYyZmZiM2NjMTRhOTBjYWEyNjFlNTNkZTQ0MDAxNzdiMTMyOTdmMTAwZDY2ZjMzNTQ5ZDQxYWZiMzZjOWEzMzQiLCAiY3dkcyI6IHsiZXh0NF93ZWxjb21lIjogIi9ob21lL21heC9iZW5jaG1hcmtzL2JyYW5jaGxpbmUtYm91bmRhcnkvcHJvZmlsZXMvY2FuZGlkYXRlLXdvcmtlci12MS13c2wtd2luZG93cy93ZWxjb21lIiwgIm50ZnNfa2VybmVsIjogIi9tbnQvYy9Vc2Vycy9tYXgvYnJhbmNobGluZS1iZW5jaC9rZXJuZWwtd2luZG93cyJ9fQ=='))
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
