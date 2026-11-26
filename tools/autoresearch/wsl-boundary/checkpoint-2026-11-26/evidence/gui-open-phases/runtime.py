#!/usr/bin/env python3
"""One released diagnostic GUI process; canonical seven-action score unchanged."""
import base64,hashlib,importlib.util,json
from pathlib import Path, PureWindowsPath
import subprocess,sys,time,traceback
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
DONOR=ROOT/'build/experiments/status-windows-controls/run.py'
spec=importlib.util.spec_from_file_location('open_phase_status_caller',DONOR);donor=importlib.util.module_from_spec(spec);spec.loader.exec_module(donor)
BASE_PLAN=donor.prepare();score,ab,launch,CdpDriver=donor.score,donor.ab,donor.launch,donor.CdpDriver
BASE,TOOLS,CONTRACT=donor.BASE,donor.TOOLS,donor.CONTRACT
HOST_PORT,CDP_PORT,MCP_PORT=donor.HOST_PORT,donor.CDP_PORT,donor.MCP_PORT
RELEASE='VM OPEN PHASE RUNTIME RELEASED';PROOF=HERE/'r2/native-build-proof.json';EXPECTED='29898a628ed57d5a4688800e87966729bc6e9391d5ece489cadb424702f588cc'
STOP=donor.stop_exact;remote=donor.remote;CURRENT=None;LAST=None

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare():
    assert score.contract_identity()['sha256']==CONTRACT
    identity=score.source_identity(HERE/'source');assert identity['source_hash']==EXPECTED
    plan=json.loads((HERE/'r2/build-plan.json').read_text());built=json.loads(PROOF.read_text()) if PROOF.exists() else None
    ready=bool(built and built.get('windows_gui') and built.get('fixture_checks_passed') and built['status'].startswith('built;'))
    if ready:
        gui=built['windows_gui'];assert built['source']==identity
        assert gui['embedded_helper_verified'] and gui['static_crt_import_check'] and gui['embedded_helper_sha256']==plan['helper']['sha256']
    else:gui={'windows_path':plan['windows_artifact'],'sha256':None}
    if '--release' in sys.argv and not ready:raise RuntimeError('The exact r2 Windows GUI build must pass before runtime release')
    p=json.loads(json.dumps(BASE_PLAN));p['variants']={'A':{'label':plan['label'],'source':str(HERE/'source'),'source_hash':EXPECTED,
        'binary':gui['windows_path'],'binary_sha256':gui['sha256'],'helper_sha256':plan['helper']['sha256']}}
    p['cases']={'windows_linux':p['cases']['windows_linux']};p['case_order']=['windows_linux']
    p.update(status='prepared-host-only-build-pending' if not ready else 'prepared-host-only-one-diagnostic-process',
        runtime_release=RELEASE,order_per_case=['diagnostic A1:1 only; all other inherited loop entries are skipped'],
        diagnostic_only=True,speedup_or_acceptance_claim=False,logging_overhead_measured=False,
        production_cache='Default production native cache/environment; no helper preparation, probes before Open or shared/default file deletion.',
        measurement='One actual Windows GUI/WSL process, unchanged canonical scorer repetitions1: Open plus six actions/two comment-jump Opens, required two-frame settle unchanged.',
        stderr='Record current owned stderr.log length after welcome-ready; capture exact appended bytes before exact STOP; parse only fixed tags with actual GUI PID.',
        source_build_proof=str(PROOF),source_build_proof_sha256=sha(PROOF) if ready else None,
        runner_sha256=sha(__file__),reused_status_caller_sha256=sha(DONOR))
    return p

OWNERSHIP=r'''
$expected=$params.expected
$actual=Get-Content $record -Raw | ConvertFrom-Json
foreach($key in @('pid','created','binary','binary_sha256','source_hash','profile')) {
 if($actual.$key -ne $expected.$key){throw ('Profile ownership changed: '+$key)}
}
$process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$expected.pid)
if(-not $process -or $process.ExecutablePath -ne $expected.binary -or $process.CreationDate.ToString('o') -ne $expected.created){throw 'Exact diagnostic GUI is not live'}
$path=Join-Path $params.profile 'stderr.log'
'''

def stderr_marker(record):
    return remote(OWNERSHIP+r'''$f=Get-Item -LiteralPath $path;@{gui_pid=$expected.pid;created=$expected.created;byte_offset=$f.Length;last_write=$f.LastWriteTimeUtc.ToString('o')}|ConvertTo-Json -Compress''',{'profile':record['profile'],'expected':record})

def capture_stderr(record):
    c=CURRENT;item=c['state']['runs'][-1];marker=item['stderr_before_open']
    script=OWNERSHIP+r'''
$f=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
try {
 $start=[int64]$params.offset;$end=$f.Length
 if($start -lt 0 -or $end -lt $start -or ($end-$start) -gt 8388608){throw 'Unexpected diagnostic stderr range'}
 $null=$f.Seek($start,[IO.SeekOrigin]::Begin);$bytes=[byte[]]::new([int]($end-$start));$read=0
 while($read -lt $bytes.Length){$n=$f.Read($bytes,$read,$bytes.Length-$read);if($n -eq 0){throw 'Diagnostic stderr shortened during capture'};$read+=$n}
 $digest=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-','').ToLowerInvariant()
 @{gui_pid=$expected.pid;created=$expected.created;offset=$start;end=$end;bytes=$bytes.Length;sha256=$digest;base64=[Convert]::ToBase64String($bytes)}|ConvertTo-Json -Compress
} finally {$f.Dispose()}
'''
    captured=remote(script,{'profile':record['profile'],'expected':record,'offset':marker['byte_offset']})
    data=base64.b64decode(captured.pop('base64'));assert hashlib.sha256(data).hexdigest()==captured['sha256']
    (c['output']/'stderr.current-launch.raw.log').write_bytes(data)
    import re
    pattern=re.compile(rb'^gui_open_phase pid=(\d+) tag=([a-z_.]+) elapsed_us=(\d+)\r?\n$')
    rows=[];selected=[];position=marker['byte_offset']
    for line in data.splitlines(keepends=True):
        match=pattern.fullmatch(line)
        if match and int(match[1])==record['pid']:
            rows.append({'pid':int(match[1]),'tag':match[2].decode(),'elapsed_us':int(match[3]),'stderr_byte_offset':position});selected.append(line)
        position+=len(line)
    assert rows,'No fixed-tag lines from actual owned GUI PID'
    chosen=b''.join(selected);(c['output']/'stderr.gui-phase-lines.log').write_bytes(chosen)
    (c['output']/'stderr.gui-phases.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    from collections import Counter
    captured.update(phase_count=len(rows),tag_counts=dict(Counter(row['tag'] for row in rows)),gui_phase_bytes_sha256=hashlib.sha256(chosen).hexdigest(),logging_overhead_measured=False,diagnostic_only=True)
    score.atomic_json(c['output']/'stderr.capture.json',captured);item['stderr_capture']=captured;c['save']()
    return captured

def stop_exact(record):
    captured=None;error=None
    try:captured=capture_stderr(record)
    except BaseException as e:error=e
    result=STOP(record)
    if error:raise error
    return dict(result,diagnostic_stderr_captured=True,gui_phase_count=captured['phase_count'])

def _run_one(case, variant, number, repetitions, plan, directory, state, save):
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
        record = remote(launch.START, params)
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
        item['stderr_before_open']=stderr_marker(record)
        score.atomic_json(output/'stderr-before-open.json',item['stderr_before_open'])
        save()
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


def run_one(case,variant,number,repetitions,plan,directory,state,save):
    global CURRENT,LAST
    if variant!='A' or number!=1:return
    CURRENT={'output':directory/f'{case}-{variant}{number}','state':state,'save':save};LAST=(state,directory/'state.json')
    _run_one(case,variant,number,1,plan,directory,state,save)

donor.HERE=HERE/'runtime-r2';donor.HERE.mkdir(exist_ok=True);donor.CASES={'windows_linux':donor.CASES['windows_linux']}
donor.prepare=prepare;donor.run_one=run_one;donor.stop_exact=stop_exact

def main():
    code=donor.main()
    if LAST:
        state,path=LAST;assert len(state['runs'])==1 and state['runs'][0]['repetitions']==1
        state.update(status='diagnostic-complete-one-process-no-speedup-claim',logging_overhead_measured=False)
        state.pop('final_20_repetitions',None);score.atomic_json(path,state)
    return code

if __name__=='__main__':raise SystemExit(main())
