#!/usr/bin/env python3
"""Host-only preparation by default; reuse the status caller for one helper A/B."""
import base64, hashlib, importlib.util, json, os
from pathlib import Path, PureWindowsPath
import shlex, subprocess, sys, time, traceback
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DONOR = ROOT/'build/experiments/status-windows-controls/run.py'
spec = importlib.util.spec_from_file_location('helper_status_caller', DONOR)
donor = importlib.util.module_from_spec(spec);spec.loader.exec_module(donor)
BASE_PLAN = donor.prepare()
score, ab, launch, CdpDriver = donor.score, donor.ab, donor.launch, donor.CdpDriver
BASE, TOOLS, CONTRACT, HELPER = donor.BASE, donor.TOOLS, donor.CONTRACT, donor.HELPER
HOST_PORT, CDP_PORT, MCP_PORT = donor.HOST_PORT, donor.CDP_PORT, donor.MCP_PORT
REMOTE, STOP = donor.remote, donor.stop_exact
BUILD = HERE/'native-build-evidence/supervisor.json'
RELEASE = 'VM NATIVE HELPER GUI RUNTIME RELEASED'
CURRENT = None
LAST = None

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare():
    assert score.contract_identity()['sha256'] == CONTRACT
    assert sha(donor.BUILD_STATE) == BASE_PLAN['build_state_sha256']
    p = json.loads(json.dumps(BASE_PLAN));p['variants'].pop('B')
    a=p['variants']['A'];assert score.source_identity(a['source'])['source_hash']==a['source_hash']
    built=json.loads(BUILD.read_text());identity=score.source_identity(HERE/'source')
    assert identity==built['source'] and identity['source_hash']=='252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500'
    gui=built['windows_gui'];assert gui['embedded_helper_verified'] and gui['embedded_helper_sha256']==HELPER
    assert gui['sha256']=='684cbe8293d3c737c23aaa026da190b75117d9121668ca4c838672c1152675a9'
    assert json.loads((HERE/'malformed-client-gate/summary.json').read_text())['status']=='passed-both-native-malformed-response-cleanup-gates'
    p['variants']['B']={'label':'native-helper-deployment-b2de070-03fecde11c0a','source':str(HERE/'source'),
        'source_hash':identity['source_hash'],'binary':str(PureWindowsPath('C:/Users/max/branchline-bench/binaries/native-helper-deployment-b2de070-03fecde11c0a/branchline.exe')),
        'binary_sha256':gui['sha256'],'helper_sha256':HELPER,'build_record':str(BUILD),'build_record_sha256':sha(BUILD)}
    p['cases']={'windows_linux':p['cases']['windows_linux']};p['case_order']=['windows_linux']
    p.update(status='prepared-host-only-no-VM-or-scorer-access',runtime_release=RELEASE,performance_early_gate=True,
        order_per_case=['A1:3','B1:3 initial native-cache install','A2:3','B2:3 native-cache hit','pilot gate','A3:20','B3:20 native-cache hit'],
        runner_sha256=sha(__file__),reused_status_caller=str(DONOR),reused_status_caller_sha256=sha(DONOR),
        native_cache_template='/home/max/benchmarks/branchline-boundary/helper-gui-ab-cache/<unique run directory>',
        cache_policy='Same series-owned normal XDG_CACHE_HOME/WSLENV passed to A/B; seeded Windows profile/data/settings/comments unchanged. No cache directory or helper is created before timed Open. Metadata-only proof after welcome-ready, immediately before canonical scorer. Hash/worker/storage verification only after the complete score.',
        open_labels='B1 is one initial-install fresh Open; B2/B3 are fresh-process native-cache hits. No cold-install distribution or OS-cold claim. --repetitions repeats six later actions, not Open.',
        pilot_gate={'cache_hit_fresh_open_max_ratio':.9,'initial_install_open_max_ratio':1.1,'each_six_action_pooled_p95_max_ratio':1.1,'failure':'Stop before20, preserve valid pilots, await review; no retry or promotion.'},
        pending_matrix='Windows/NTFS same-side and both Linux GUI cells remain separate later assignments.',
        source_change='None; source/scorer/contract/two-frame settle unchanged.')
    return p

def vm(code):
    encoded=base64.b64encode(code.encode()).decode()
    command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','-d','Ubuntu-26.04','-u','max','--exec','/usr/bin/python3','-c',"import base64;exec(base64.b64decode('"+encoded+"'))"])
    r=subprocess.run([*donor.ssh_client(),command],capture_output=True,text=True,timeout=45)
    if r.returncode:raise RuntimeError(r.stderr or r.stdout)
    return json.loads(r.stdout)

def probe(hash_files=False):
    c=CURRENT;data={'root':c['cache'],'images':[c['source_image'],c['native_image']],'hash':hash_files}
    code="import pathlib,os,json,hashlib,ctypes;c="+repr(data)+";files={};workers=[]\n"
    code+=r'''
for name in c['images']:
 p=pathlib.Path(name);v={'exists':p.exists()}
 if v['exists']:
  s=p.stat();v.update(bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,inode=s.st_ino,device=s.st_dev,mode=oct(s.st_mode&0o777))
  if c['hash']:
   buf=ctypes.create_string_buffer(512);assert ctypes.CDLL(None).statfs(os.fsencode(p),buf)==0
   v.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),filesystem_type=hex(ctypes.c_long.from_buffer(buf).value))
 files[name]=v
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  image=str((p/'exe').resolve())
  if image not in c['images']:continue
  f=(p/'stat').read_text().rsplit(') ',1)[1].split()
  workers.append({'pid':int(p.name),'start_ticks':f[19],'state':f[0],'exe':image,'cwd':str((p/'cwd').resolve()),'args':(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')})
 except (FileNotFoundError,ProcessLookupError,PermissionError):pass
root=pathlib.Path(c['root']);temporary=list((root/'branchline/git-workers').glob('.branchline-git-worker.*'))
print(json.dumps({'root_exists':root.exists(),'files':files,'workers':workers,'temporary':[str(p) for p in temporary]}))
'''
    return vm(code)

def remote(body,params):
    if body==launch.START:
        anchor='    $env:BRANCHLINE_MCP_PORT=[string]$p.mcp_port'
        body=body.replace(anchor,anchor+"\n    $env:XDG_CACHE_HOME=$p.native_cache\n    $entries=@($env:WSLENV -split ':' | Where-Object {$_ -and ($_.Split('/')[0] -ine 'XDG_CACHE_HOME')})\n    $env:WSLENV=(@($entries)+@('XDG_CACHE_HOME/u')) -join ':'")
        params=dict(params,native_cache=CURRENT['cache'])
    return REMOTE(body,params)

def cache_before_open(version,record,plan,state,output):
    value=probe(False);assert not value['workers'],value
    native=value['files'][CURRENT['native_image']]
    if CURRENT['variant']=='B' and CURRENT['number']==1:
        assert not native['exists'],'Initial native helper must be absent through timed Open'
        label='initial native-cache install; one fresh-process observation'
    elif CURRENT['variant']=='B':
        assert native['exists'] and state.get('native_cache_reference')
        previous=state['native_cache_reference']
        assert all(native[k]==previous[k] for k in ['inode','bytes','mtime_ns','ctime_ns','mode']), 'Native cache changed between processes'
        label='native-cache hit in a fresh process; no pre-Open hash/read/exec'
    else:label='b2 foreign-filesystem helper control; native cache unused'
    value['label']=label;value['metadata_only']=True
    score.atomic_json(output/'cache-before-open.json',value)
    return value

def remove_cache(state):
    if state.get('native_cache_removed'):return
    c=CURRENT;assert not probe(False)['workers'],'Stop owned workers before removing cache'
    code="import pathlib,json,hashlib;root=pathlib.Path("+repr(c['cache'])+");p=pathlib.Path("+repr(c['native_image'])+");removed=[]\nif p.exists():\n assert hashlib.sha256(p.read_bytes()).hexdigest()=="+repr(HELPER)+"\n p.unlink();removed.append(str(p))\nfor d in [p.parent,p.parent.parent,root]:\n if d.exists():d.rmdir()\nprint(json.dumps({'removed_owned_files':removed,'owned_cache_root_absent':not root.exists()}))"
    state['native_cache_cleanup']=vm(code);state['native_cache_removed']=True;CURRENT['save']()

def stop_exact(record):
    c=CURRENT;item=c['state']['runs'][-1];snapshot=None;observation_error=None
    try:snapshot=probe(True);score.atomic_json(c['output']/'cache-after-score.json',snapshot)
    except BaseException as error:observation_error=str(error)
    try:result=STOP(record)
    finally:
        deadline=time.monotonic()+10
        while True:
            left=probe(False)['workers']
            if not left:break
            if time.monotonic()>=deadline:
                item['remaining_native_workers']=left;c['save']()
                code="import pathlib,os,signal,json;rows="+repr(left)+";killed=[]\nfor row in rows:\n p=pathlib.Path('/proc')/str(row['pid'])\n try:\n  f=(p/'stat').read_text().rsplit(') ',1)[1].split()\n  if f[19]==row['start_ticks'] and str((p/'exe').resolve())==row['exe']:\n   h=os.pidfd_open(row['pid']);signal.pidfd_send_signal(h,signal.SIGKILL);os.close(h);killed.append(row)\n except (FileNotFoundError,ProcessLookupError):pass\nprint(json.dumps({'forced_exact_cleanup':killed}))"
                item['forced_native_cleanup']=vm(code);c['save']();raise RuntimeError('Owned native helper required forced cleanup; preserve run and stop')
            time.sleep(.1)
        item['native_workers_gone']=True;c['save']()
    if observation_error:raise RuntimeError('Post-score helper proof failed: '+observation_error)
    if item['status']=='valid':
        expected=c['native_image'] if c['variant']=='B' else c['source_image']
        assert snapshot['workers'] and all(w['exe']==expected and w['cwd']=='/home/max/benchmarks/branchline-boundary/kernel-wsl' for w in snapshot['workers']),snapshot
        assert snapshot['files'][expected]['sha256']==HELPER and not snapshot['temporary']
        assert snapshot['files'][c['source_image']]['sha256']==HELPER
        assert snapshot['files'][expected]['filesystem_type']==('0xef53' if c['variant']=='B' else '0x1021997')
        if c['variant']=='B':
            before=item['cache_before_open']['files'][expected];after=snapshot['files'][expected]
            if c['number']>1:assert all(before[k]==after[k] for k in ['inode','bytes','mtime_ns']), 'Cache hit rewrote helper'
            c['state']['native_cache_reference']=after
        item['helper_placement_verified']=True;c['save']()
    return dict(result,native_workers_gone=True)

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
        item['cache_before_open']=cache_before_open(version,record,plan,state,output)
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


def pilot(state):
    runs=state['runs'];summaries={k:ab.action_summary([s for r in runs if r['variant']==k for s in ab.samples_for(r)]) for k in ['A','B']}
    opened={(r['variant'],r['number']):next(s['elapsed_ms'] for s in ab.samples_for(r) if s['action']=='open') for r in runs}
    ratios={a:summaries['B'][a]['p95_ms']/summaries['A'][a]['p95_ms'] for a in score.ACTIONS}
    hit=opened['B',2]/opened['A',2];install=opened['B',1]/opened['A',1]
    return {'pass':hit<=.9 and install<=1.1 and all(r<=1.1 for r in ratios.values()),'cache_hit_fresh_open_ratio':hit,
        'one_initial_install_fresh_open_ratio':install,'six_action_pooled_p95_ratios':ratios,'pooled_actions':summaries,
        'interpretation':'Continuation gate only; no cold distribution, OS-cold, full matrix or source promotion claim.'}

def run_one(case,variant,number,repetitions,plan,directory,state,save):
    global CURRENT,LAST
    cache='/home/max/benchmarks/branchline-boundary/helper-gui-ab-cache/'+directory.name
    CURRENT={'variant':variant,'number':number,'cache':cache,'state':state,'save':save,
        'native_image':cache+'/branchline/git-workers/branchline-git-worker-'+HELPER,
        'source_image':'/mnt/c/Users/max/branchline-bench/profiles/baseline-windows-linux/data/Branchline/git-workers/branchline-git-worker-'+HELPER,
        'output':directory/f'{case}-{variant}{number}'}
    LAST=(state,directory/'state.json')
    state['native_cache']=dict(root=cache,helper=CURRENT['native_image'],normal_os_environment='XDG_CACHE_HOME transferred through WSLENV/u equally for A/B')
    save()
    if number==3:
        if 'pilot_result' not in state:state['pilot_result']=pilot(state);save()
        if not state['pilot_result']['pass']:
            state['twenty_repetitions_skipped']=True;remove_cache(state);return
    if not state['runs']:assert not probe(False)['root_exists'],'Refuse an existing cache namespace'
    try:_run_one(case,variant,number,repetitions,plan,directory,state,save)
    except BaseException:
        try:remove_cache(state)
        except BaseException as e:state['native_cache_cleanup_error']=str(e);save()
        raise
    if variant=='B' and number==3:remove_cache(state)

# Reuse the existing serial runner, master ownership, fixture guards and shutdown.
donor.HERE=HERE/'gui-ab';donor.HERE.mkdir(exist_ok=True)
donor.CASES={'windows_linux':donor.CASES['windows_linux']}
donor.prepare=prepare;donor.remote=remote;donor.stop_exact=stop_exact;donor.run_one=run_one

def main():
    result=donor.main()
    if LAST and LAST[0].get('twenty_repetitions_skipped'):
        state,path=LAST;state['status']='pilot-inconclusive-review-before-20-repetitions';score.atomic_json(path,state)
    return result

if __name__=='__main__':raise SystemExit(main())
