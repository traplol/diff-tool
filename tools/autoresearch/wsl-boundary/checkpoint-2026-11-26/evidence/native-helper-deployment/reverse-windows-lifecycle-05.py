import base64,hashlib,importlib.util,json,os,pathlib,shlex,signal,socket,subprocess,sys,time,traceback
R=pathlib.Path(__file__).resolve().parents[3];HERE=pathlib.Path(__file__).resolve().parent;O=HERE/'reverse-windows-lifecycle-05';O.mkdir(exist_ok=False);sys.path.insert(0,str(R/'tools/autoresearch/wsl-boundary'))
import launch
from driver import CdpDriver
B='/home/max/benchmarks/branchline-boundary';L='native-helper-deployment-b2de070-03fecde11c0a';SOURCE='252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500';SHA='328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa'
CACHE=B+"/nwg-252d-02/cache's réview &[]";IMAGE=CACHE+'/branchline/git-workers/branchline-git-worker-'+SHA
WINROOT=r'\\wsl.localhost\Ubuntu-26.04\home\max\benchmarks\branchline-boundary\kernel-wsl';CONTROL=r'C:\Users\max\branchline-bench\kernel-windows'
BINARY='C:\\Users\\max\\branchline-bench\\binaries\\'+L+'\\branchline.exe';BASE=r'C:\Users\max\branchline-bench\nwg-252d-02\réview space'
CONTROL_SOCKET='/tmp/nh-lc05-'+str(os.getpid())+'.sock'
SSH=['ssh','-F',str(pathlib.Path.home()/'.ssh/config'),'-o','BatchMode=yes','-o','ConnectTimeout=10','-S',CONTROL_SOCKET,'windows-vm']
state={'host_pid':os.getpid(),'source_hash':SOURCE,'binary_sha256':'684cbe8293d3c737c23aaa026da190b75117d9121668ca4c838672c1152675a9','status':'running','cases':[],'not_a_score':True};active=None;forward=None

def save():(O/'primary-result.json').write_text(json.dumps(state,indent=2)+'\n')
def event(name,data=None):print(json.dumps({'phase':name,'host_pid':os.getpid(),'data':data}),flush=True)
def wsl(code):
 cmd='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','--distribution','Ubuntu-26.04','--user','max','--exec','/usr/bin/python3','-u','-'])
 r=subprocess.run(SSH+[cmd],input=code,capture_output=True,text=True,timeout=30)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def workers(image=IMAGE):
 payload=base64.b64encode(json.dumps({'image':image}).encode()).decode()
 return wsl("import base64,json,pathlib,os,hashlib,ctypes\np=json.loads(base64.b64decode('"+payload+"')); image=p['image']; rows=[]\nfor d in pathlib.Path('/proc').iterdir():\n if not d.name.isdigit():continue\n try:\n  if str((d/'exe').resolve())!=image:continue\n  f=(d/'stat').read_text().rsplit(') ',1)[1].split(); e=dict(x.split('=',1) for x in (d/'environ').read_bytes().decode(errors='replace').split('\\0') if '=' in x)\n  rows.append({'pid':int(d.name),'start_ticks':f[19],'state':f[0],'exe':image,'cwd':str((d/'cwd').resolve()),'args':(d/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace'),'environment':{k:e.get(k) for k in ['XDG_CACHE_HOME','HOME','USER','GIT_OPTIONAL_LOCKS','GIT_TERMINAL_PROMPT','GIT_NO_LAZY_FETCH','LC_ALL']}})\n except (FileNotFoundError,ProcessLookupError,PermissionError):pass\nf=pathlib.Path(image); meta={'exists':f.is_file()}\nif f.is_file():\n s=f.stat(); buf=ctypes.create_string_buffer(512); libc=ctypes.CDLL(None); assert libc.statfs(os.fsencode(image),buf)==0; meta.update(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),mtime_ns=s.st_mtime_ns,mode=oct(s.st_mode&0o777),filesystem_type=hex(ctypes.c_long.from_buffer(buf).value))\nprint(json.dumps({'workers':rows,'file':meta}))")
def wait_gone(ids,image=IMAGE):
 until=time.monotonic()+10
 while True:
  data=workers(image);left=[w for w in data['workers'] if any(w['pid']==i['pid'] and w['start_ticks']==i['start_ticks'] for i in ids)]
  if not left:return {'gone':True}
  if time.monotonic()>until:raise RuntimeError('Owned Linux workers remained: '+repr(left))
  time.sleep(.05)
def remote(body,params):
 encoded=base64.b64encode(json.dumps(params).encode()).decode()
 script=launch.COMMON.replace('__PARAMS__',encoded)+'[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);'+body.replace('Get-Content ','Get-Content -Encoding UTF8 ')
 command=("control=$(mktemp --suffix=.ps1); trap 'rm -f \"$control\"' EXIT; "
          'cat > "$control"; powershell.exe -NoProfile -NonInteractive '
          '-ExecutionPolicy Bypass -File "$(cygpath -w "$control")"')
 result=subprocess.run(SSH+[command],input=script,capture_output=True,text=True,timeout=90)
 if result.returncode:raise RuntimeError(result.stderr.strip() or result.stdout.strip())
 return json.loads(result.stdout.lstrip('\ufeff').strip())
START=launch.START.replace("    $env:BRANCHLINE_MCP_PORT=[string]$p.mcp_port", "    $env:BRANCHLINE_MCP_PORT=[string]$p.mcp_port\n    $env:XDG_CACHE_HOME=$p.native_cache\n    $entries=@($env:WSLENV -split ':' | Where-Object {$_ -and ($_.Split('/')[0] -ine 'XDG_CACHE_HOME')})\n    $env:WSLENV=(@($entries)+@('XDG_CACHE_HOME/u')) -join ':'")

def start(name,cache=CACHE):
 global active
 profile=BASE+'\\'+name;params={'profile':profile,'binary':BINARY,'repo':profile+'\\welcome','cdp_port':29371,'mcp_port':28971,'source_hash':SOURCE,'native_cache':cache}
 record=remote(START,params);assert record['binary_sha256']==state['binary_sha256'];active={'record':record,'params':params,'driver':None};event('native-windows-gui-started',record)
 until=time.monotonic()+20
 while True:
  try:d=CdpDriver('http://127.0.0.1:49371',timeout=25);break
  except Exception:
   if time.monotonic()>until:raise
   time.sleep(.1)
 active['driver']=d;d.wait("typeof window.__TAURI_INTERNALS__?.invoke==='function' && document.querySelector('#welcome-open')?.getClientRects().length && !document.querySelector('#app')?.hasAttribute('aria-busy') && document.querySelector('#status')?.classList.contains('error')",timeout=25)
 probe=(R/'tools/autoresearch/wsl-boundary/probe.js').read_text().replace('call.error = "Native IPC returned an error";','{call.error="Native IPC returned an error";call.native_error=result;}')
 d.evaluate(probe+'\nreturn true;');return open_ui(WINROOT,True)
def key(p):return p.replace('\\','/').removeprefix('//?/UNC/').rstrip('/')
def open_ui(root,first=False):
 d=active['driver'];d.evaluate('window.boundaryProbe.chooseRoot(arguments[0]);',root);d.click('#welcome-open' if first else '#choose')
 result=d.wait("(() => {const s=window.boundaryProbe.state(),e=document.querySelector('#status');const c=window.boundaryProbe.calls().findLast(c=>c.command==='workspace'&&c.op==='open');if(c?.end!==undefined&&e?.classList.contains('error'))return {error:e.textContent,native:c.native_error};if(s?.repo&&s.repo.root.replaceAll('\\\\','/').replace(/\\/+$/,'')===arguments[0]&&!document.querySelector('#app')?.hasAttribute('aria-busy')&&[...document.querySelectorAll('#diff .cm-content')].some(n=>n.getClientRects().length))return {ok:true};return false;})()",key(root),timeout=30)
 if result.get('error'):raise RuntimeError(result)
 d.evaluate('await window.boundaryProbe.settle();');s=d.evaluate('return window.boundaryProbe.state();');assert not s.get('mcp_warning') and not s.get('config_warning'),s.get('mcp_warning') or s.get('config_warning')
 assert s['repo']['refs']['refs/heads/main']=='adc218676eef25575469234709c2d87185ca223a'
 assert s['repo']['refs']['refs/heads/feature/boundary-first']=='856700f06bf917bd363dd835fe6f6bd3923254da'
 assert s['repo']['refs']['refs/heads/feature/boundary-final']=='997032e932bfa5fcefdab0c986c8d01fe56c8229'
 assert len(s['comparison']['files'])==30
 return {'root':s['repo']['root'],'refs':s['repo']['refs'],'pair':s['pair'],'files':s['comparison']['files'],'snapshot':s['snapshot']}
def stop():
 global active
 if not active:return None
 a=active;active=None
 if a['driver']:
  try:a['driver'].close()
  except Exception:pass
 stopped=remote(launch.STOP,a['params']);return stopped
def case(name,body):
 c={'name':name,'started':time.time()};state['cases'].append(c);save();event(name)
 try:c['proof']=body();c['passed']=True
 except BaseException:
  c['passed']=False;c['error']=traceback.format_exc()
  if active and active['driver']:
   try:c['failure_ui']=active['driver'].info();active['driver'].screenshot(O/(name+'-failure.png'))
   except BaseException:pass
  raise
 finally:
  c['cleanup']=stop();c['finished']=time.time();save()
 event(name+'-passed',c['proof'])

# Each pause is a fault-injection barrier on one real owned read-only Git child.
# No product flags, replacement workers, altered requests, or timing scores.
def arm_git_pause(exclude):
 cfg=base64.b64encode(json.dumps({'image':IMAGE,'exclude':exclude}).encode()).decode()
 code=r'''import base64,json,pathlib,os,signal,time
c=json.loads(base64.b64decode('__CFG__'));until=time.monotonic()+8
print(json.dumps({'armed':True}),flush=True)
while time.monotonic()<until:
 for d in pathlib.Path('/proc').iterdir():
  if not d.name.isdigit() or int(d.name) in c['exclude']:continue
  try:
   if str((d/'exe').resolve())!=c['image']:continue
   wf=(d/'stat').read_text().rsplit(') ',1)[1].split()
   for task in (d/'task').iterdir():
    for child in (task/'children').read_text().split():
     p=pathlib.Path('/proc')/child;handle=None
     try:
      exe=str((p/'exe').resolve());f=(p/'stat').read_text().rsplit(') ',1)[1].split()
      if pathlib.Path(exe).name!='git' or f[0]=='Z':continue
      args=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode();env=dict(x.split('=',1) for x in (p/'environ').read_bytes().decode(errors='replace').split('\0') if '=' in x)
      if env.get('GIT_OPTIONAL_LOCKS')!='0':continue
      handle=os.pidfd_open(int(child));signal.pidfd_send_signal(handle,signal.SIGSTOP)
      deadline=time.monotonic()+.2
      while time.monotonic()<deadline:
       after=(p/'stat').read_text().rsplit(') ',1)[1].split()
       if after[0] in ['T','t']:break
       time.sleep(.001)
      if after[19]!=f[19] or after[0] not in ['T','t']:continue
      print(json.dumps({'worker':{'pid':int(d.name),'start_ticks':wf[19],'exe':c['image']},'git':{'pid':int(child),'start_ticks':f[19],'exe':exe,'args':args,'cwd':str((p/'cwd').resolve()),'state':after[0],'environment':{k:env.get(k) for k in ['GIT_OPTIONAL_LOCKS','GIT_TERMINAL_PROMPT','GIT_NO_LAZY_FETCH','LC_ALL']}},'real_read_paused':True}),flush=True)
      # The signal barrier self-resumes if its controller disappears.
      deadline=time.monotonic()+10
      while time.monotonic()<deadline:
       after=(p/'stat').read_text().rsplit(') ',1)[1].split()
       if after[19]!=f[19] or after[0] not in ['T','t']:break
       time.sleep(.02)
      raise SystemExit(0)
     except (FileNotFoundError,ProcessLookupError,PermissionError):pass
     finally:
      if handle is not None:
       try:signal.pidfd_send_signal(handle,signal.SIGCONT)
       except ProcessLookupError:pass
       os.close(handle)
  except (FileNotFoundError,ProcessLookupError,PermissionError):pass
 time.sleep(.005)
print(json.dumps({'not_observed':True}),flush=True)
'''.replace('__CFG__',cfg)
 cmd='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','--distribution','Ubuntu-26.04','--user','max','--exec','/usr/bin/python3','-u','-'])
 p=subprocess.Popen(SSH+[cmd],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);p.stdin.write(code);p.stdin.close()
 first=json.loads(p.stdout.readline());assert first.get('armed'),first;return p

def resume_git(proof):
 if not proof or not proof.get('git'):return
 i=proof['git'];payload=base64.b64encode(json.dumps(i).encode()).decode()
 return wsl("import base64,json,pathlib,os,signal;i=json.loads(base64.b64decode('"+payload+"'));p=pathlib.Path('/proc')/str(i['pid']);r={'already_gone':True}\ntry:\n f=(p/'stat').read_text().rsplit(') ',1)[1].split()\n if f[19]==i['start_ticks'] and str((p/'exe').resolve())==i['exe']:\n  h=os.pidfd_open(i['pid']);signal.pidfd_send_signal(h,signal.SIGCONT);os.close(h);r={'resumed_exact_git':i}\nexcept (FileNotFoundError,ProcessLookupError):pass\nprint(json.dumps(r))")

def kill_windows(identity):
 return remote(r'''$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$params.target.pid);if($p){if($p.ExecutablePath -ne $params.target.binary -or $p.CreationDate.ToString('o') -ne $params.target.created){throw 'Owned PID identity changed'};$h=Get-Process -Id $p.ProcessId;$null=$h.Handle;$again=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ProcessId);if($again.CreationDate.ToString('o') -ne $params.target.created){throw 'Owned creation time changed'};$h.Kill();$null=$h.WaitForExit(10000)};@{killed_pid=$params.target.pid}|ConvertTo-Json -Compress''',dict(active['params'],target=identity))

def mcp_identity():
 result=remote(r'''$a=@(Get-CimInstance Win32_Process -Filter ('ParentProcessId='+$params.owner) | Where-Object {$_.ExecutablePath -eq $params.binary -and $_.CommandLine -match ('(?:^|\s)--mcp(?:\s|$)') -and $_.CommandLine -match ('(?:^|\s)--port\s+'+$params.mcp_port+'(?:\s|$)')} | ForEach-Object {@{pid=[int]$_.ProcessId;binary=$_.ExecutablePath;created=$_.CreationDate.ToString('o');args=$_.CommandLine}});ConvertTo-Json -InputObject $a -Compress''',dict(active['params'],owner=active['record']['pid']))
 assert len(result)==1,result;return result[0]

def rpc_work():
 import urllib.request
 data={'jsonrpc':'2.0','id':91,'method':'tools/call','params':{'name':'list_changes','arguments':{'pair':['refs/heads/feature/boundary-final',':worktree:']}}}
 req=urllib.request.Request('http://127.0.0.1:48971/mcp',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','Host':'127.0.0.1:28971'})
 with urllib.request.urlopen(req,timeout=20) as r: result=json.load(r)
 assert result['id']==91 and not result['result'].get('isError'),result
 return result

def death(gui,busy):
 import threading
 start(('final-gui-' if gui else 'final-mcp-')+('busy' if busy else 'idle'));before=workers()['workers'];assert len(before)==1,before
 identity=active['record'] if gui else mcp_identity();paused=None;watch=None;thread=None;request_errors=[]
 proof={'owner':identity,'before':before,'busy':busy};mcp_workers=[]
 try:
  if not gui and not busy:
   proof['completed_mcp_read']=rpc_work();mcp_workers=[w for w in workers()['workers'] if w['pid']!=before[0]['pid']];assert not mcp_workers,mcp_workers;proof['no_idle_mcp_worker_expected_after_request_drop']=True
  state['cases'][-1]['inflight_proof']=proof;save()
  if busy:
   watch=arm_git_pause([] if gui else [before[0]['pid']])
   if gui:active['driver'].click('#local-review')
   else:
    def call():
     try:rpc_work()
     except BaseException:request_errors.append(traceback.format_exc())
    thread=threading.Thread(target=call,daemon=True);thread.start()
   paused=json.loads(watch.stdout.readline());assert paused.get('real_read_paused'),paused
   if gui:assert active['driver'].evaluate("return window.boundaryProbe.calls().some(c=>c.command==='workspace'&&c.end===undefined);")
   else:assert thread.is_alive()
   proof['busy_observation']=paused
   state['cases'][-1]['inflight_proof']=proof;save();event('owned-read-paused',paused)
  killed=kill_windows(identity);proof['killed']=killed
  if paused:proof['resumed']=resume_git(paused)
  targets=before if gui else ([paused['worker']] if paused else mcp_workers)
  proof['workers_gone']=wait_gone(targets)
  remaining=workers()['workers']
  if gui:assert not remaining,remaining
  else:assert {w['pid'] for w in remaining}=={before[0]['pid']},remaining
  if thread:thread.join(timeout=5);assert not thread.is_alive();proof['request_errors']=request_errors
  return proof
 finally:
  if watch and paused is None:
   try:
    line=watch.stdout.readline()
    if line:paused=json.loads(line)
   except BaseException:pass
  if paused:resume_git(paused)
  if watch:
   try:watch.wait(timeout=12)
   except subprocess.TimeoutExpired:watch.terminate();watch.wait(timeout=3)

RAW=r'''import pathlib,json,subprocess,threading,queue,base64,hashlib
image=__IMAGE__;root='/home/max/benchmarks/branchline-boundary/kernel-wsl';assert hashlib.sha256(pathlib.Path(image).read_bytes()).hexdigest()==__SHA__;proof=[]
for busy in [False,True]:
 p=subprocess.Popen([image,'--stdio'],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE);q=queue.Queue();frames=[]
 def reader():
  for line in p.stdout:q.put(line)
  q.put(None)
 t=threading.Thread(target=reader,daemon=True);t.start()
 def send(i,op,**args):p.stdin.write(json.dumps({'id':i,'op':op,**args}).encode()+b'\n');p.stdin.flush()
 def receive(i):
  raw=q.get(timeout=12);assert raw and raw.endswith(b'\n');r=json.loads(raw);assert r['id']==i;frames.append({'id':i,'raw_base64':base64.b64encode(raw).decode()});return r
 try:
  send(1,'hello');hello=receive(1)['result'];assert hello['os']=='linux' and hello['protocol']==1
  send(2,'open',path=root);repo=receive(2)['result']['repo']
  if busy:send(3,'working_tree',view=repo,checkout=repo['checkout'],untracked_paths=None);p.stdin.close();assert len(receive(3)['result']['files'])==15
  else:send(3,'invalid_owned_protocol_fixture');assert 'error' in receive(3);send(4,'hello');assert receive(4)['result']['pid']==hello['pid'];p.stdin.close()
  assert q.get(timeout=12) is None;p.wait(timeout=10);assert p.returncode==0
  proof.append({'busy_eof':busy,'hello':hello,'frames':frames,'exit':p.returncode,'stderr':p.stderr.read().decode(errors='replace')})
 finally:
  if p.poll() is None:p.kill();p.wait(timeout=5)
print(json.dumps(proof))'''

def raw_eof():return wsl(RAW.replace('__IMAGE__',repr(IMAGE)).replace('__SHA__',repr(SHA)))

def fingerprints():
 return wsl("import sys,pathlib,json;sys.path.insert(0,"+repr(B+'/'+L+'-input/source/tools/autoresearch/wsl-boundary')+");import workload;r={n:workload.fingerprint(p) for n,p in [('linux',workload.LINUX_ROOT),('windows',workload.WINDOWS_ROOT)]};assert set(r.values())=={'db66016f41a604c102cc81121c4e81f9c93db3b3f4430ef51dab5ba1c9da97c2'};print(json.dumps(r))")

try:
 with socket.socket() as p:p.bind(('127.0.0.1',49371))
 with socket.socket() as p:p.bind(('127.0.0.1',48971))
 forward=subprocess.Popen(SSH[:-1]+['-M','-o','ControlPersist=no','-N','-o','ExitOnForwardFailure=yes','-L','127.0.0.1:49371:127.0.0.1:29371','-L','127.0.0.1:48971:127.0.0.1:28971','windows-vm'],stdout=(O/'tunnel.stdout.log').open('w'),stderr=(O/'tunnel.stderr.log').open('w'))
 state['tunnel_pid']=forward.pid;state['control_socket']=CONTROL_SOCKET;save();event('reverse-lifecycle-start',{'result':str(O/'primary-result.json'),'tunnel_pid':forward.pid})
 deadline=time.monotonic()+8
 while not pathlib.Path(CONTROL_SOCKET).exists():
  assert forward.poll() is None,'ControlMaster exited'
  if time.monotonic()>deadline:raise RuntimeError('ControlMaster socket was not ready')
  time.sleep(.05)
 check=subprocess.run(SSH[:-1]+['-O','check','windows-vm'],capture_output=True,text=True,timeout=5);assert check.returncode==0,check.stderr
 state['control_verified']=check.stderr.strip();state['fingerprint_before']=fingerprints();data=workers();assert not data['workers'] and data['file']['sha256']==SHA;save();event('multiplexed-control-verified',state['control_verified'])
 case('abrupt-windows-mcp-idle',lambda:death(False,False))
 case('abrupt-windows-mcp-busy-real-read',lambda:death(False,True))
 state['status']='passed-reverse-lifecycle-gates'
except BaseException:state['status']='failed';state['error']=traceback.format_exc()
finally:
 try:stop()
 except BaseException:state['cleanup_error']=traceback.format_exc()
 try:
  ids=[c['inflight_proof']['busy_observation']['git'] for c in state['cases'] if c.get('inflight_proof',{}).get('busy_observation')];payload=base64.b64encode(json.dumps(ids).encode()).decode()
  state['paused_git_release']=wsl("import base64,json,pathlib;ids=json.loads(base64.b64decode('"+payload+"'));rows=[]\nfor i in ids:\n p=pathlib.Path('/proc')/str(i['pid'])\n try:\n  f=(p/'stat').read_text().rsplit(') ',1)[1].split()\n  if f[19]==i['start_ticks']:rows.append({'pid':i['pid'],'state':f[0]})\n except FileNotFoundError:pass\nprint(json.dumps(rows))");assert not state['paused_git_release'],state['paused_git_release']
  state['remaining_workers']=workers()['workers']
  state['windows_release']=remote(r'''$a=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $params.binary} | ForEach-Object {@{pid=$_.ProcessId;created=$_.CreationDate.ToString('o');args=$_.CommandLine}});$ports=@(Get-NetTCPConnection -State Listen -LocalPort 29371,28971 -ErrorAction SilentlyContinue | ForEach-Object {@{port=$_.LocalPort;pid=$_.OwningProcess}});@{actors=$a;ports=$ports}|ConvertTo-Json -Compress -Depth 5''',{'profile':BASE,'binary':BINARY})
  assert not state['remaining_workers'] and not state['windows_release']['actors'] and not state['windows_release']['ports']
 except BaseException:state['release_error']=traceback.format_exc()
 try:state['fingerprint_after']=fingerprints()
 except BaseException:state['fingerprint_error']=traceback.format_exc()
 if forward:
  forward.terminate()
  try:forward.wait(timeout=5)
  except subprocess.TimeoutExpired:forward.kill();forward.wait()
 state['tunnel_stopped']=forward is None or forward.poll() is not None
 state['control_socket_absent']=not pathlib.Path(CONTROL_SOCKET).exists()
 state['actual_client_malformed_response_injection']='unproved; real server-invalid-request recovery is a separate gate; no broad fault fixture added';save();event('reverse-lifecycle-complete',{'status':state['status'],'error':state.get('error')})
if state['status']=='failed' or state.get('cleanup_error') or state.get('fingerprint_error') or state.get('release_error'):raise SystemExit(1)
