import base64,hashlib,importlib.util,json,os,pathlib,shlex,signal,socket,subprocess,sys,time,traceback
R=pathlib.Path(__file__).resolve().parents[3];HERE=pathlib.Path(__file__).resolve().parent;O=HERE/'reverse-windows-gates-01';sys.path.insert(0,str(R/'tools/autoresearch/wsl-boundary'))
import launch
from driver import CdpDriver
B='/home/max/benchmarks/branchline-boundary';L='native-helper-deployment-b2de070-03fecde11c0a';SOURCE='252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500';SHA='328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa'
CACHE=B+"/nwg-252d-01/cache's réview &[]";IMAGE=CACHE+'/branchline/git-workers/branchline-git-worker-'+SHA
WINROOT=r'\\wsl.localhost\Ubuntu-26.04\home\max\benchmarks\branchline-boundary\kernel-wsl';CONTROL=r'C:\Users\max\branchline-bench\kernel-windows'
BINARY='C:\\Users\\max\\branchline-bench\\binaries\\'+L+'\\branchline.exe';BASE=r'C:\Users\max\branchline-bench\nwg-252d-01\réview space'
SSH=['ssh','-F',str(pathlib.Path.home()/'.ssh/config'),'-o','BatchMode=yes','-o','ConnectTimeout=10','windows-vm']
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
def remote(body,params):return launch.remote('windows-vm','[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);'+body,params)
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
def installed():
 before=workers();assert not before['file']['exists'] and not before['workers'];s=start('absent');data=workers();assert data['file']['sha256']==SHA and data['file']['filesystem_type']=='0xef53';assert len(data['workers'])==1,data;assert data['workers'][0]['cwd']==B+'/kernel-wsl';assert data['workers'][0]['environment']['XDG_CACHE_HOME']==CACHE
 assert 'BRANCHLINE_BOUNDARY_LAYER_2_' in active['driver'].evaluate("return [...document.querySelectorAll('#diff .cm-content')].filter(n=>n.getClientRects().length).map(n=>n.textContent).join('\\n');")
 active['driver'].screenshot(O/'native-open.png');return {'native_image':data,'public_root':s['root'],'refs':s['refs'],'files':len(s['files'])}
def hit_drop():
 before=workers()['file'];s=start('hit-drop');data=workers();assert data['file']['sha256']==SHA and data['file']['mtime_ns']==before['mtime_ns'];assert len(data['workers'])==1
 control=open_ui(CONTROL);gone=wait_gone(data['workers']);return {'hit_no_rewrite':True,'old_worker':data['workers'],'connection_drop':gone,'same_side_root':control['root'],'gui_pid':active['record']['pid']}
def corrupt():
 assert not workers()['workers'];wsl('import pathlib,json;p=pathlib.Path('+repr(IMAGE)+');p.write_bytes(b"owned corrupt cache fixture");print(json.dumps({"corrupted":str(p)}))');s=start('corrupt');data=workers();assert data['file']['sha256']==SHA and len(data['workers'])==1;return {'repaired_native_image':data,'root':s['root']}
def fallback():
 blocked=B+'/nwg-252d-01/blocked-cache';wsl('import pathlib,json;p=pathlib.Path('+repr(blocked)+');p.write_text("owned cache fallback fixture");print(json.dumps({"blocked":str(p)}))');s=start('blocked',blocked)
 image='/mnt/c/Users/max/branchline-bench/nwg-252d-01/réview space/blocked/data/Branchline/git-workers/branchline-git-worker-'+SHA;data=workers(image);assert data['file']['sha256']==SHA and len(data['workers'])==1;return {'fallback_source_image':data,'root':s['root']}
try:
 with socket.socket() as p:p.bind(('127.0.0.1',49371))
 forward=subprocess.Popen(SSH[:-2]+['-N','-o','ExitOnForwardFailure=yes','-L','127.0.0.1:49371:127.0.0.1:29371','windows-vm'],stdout=(O/'tunnel.stdout.log').open('w'),stderr=(O/'tunnel.stderr.log').open('w'))
 state['tunnel_pid']=forward.pid;save();event('reverse-primary-start',{'result':str(O/'primary-result.json'),'tunnel_pid':forward.pid})
 case('native-ext4-install-public-root-content',installed)
 case('native-cache-hit-normal-drop',hit_drop)
 case('native-cache-corrupt-repair',corrupt)
 case('native-cache-unavailable-source-fallback',fallback)
 state['status']='passed-primary-reverse-gates'
except BaseException:state['status']='failed';state['error']=traceback.format_exc()
finally:
 try:stop()
 except BaseException:state['cleanup_error']=traceback.format_exc()
 if forward:
  forward.terminate()
  try:forward.wait(timeout=5)
  except subprocess.TimeoutExpired:forward.kill();forward.wait()
 state['tunnel_stopped']=forward is None or forward.poll() is not None;save();event('reverse-primary-complete',{'status':state['status'],'error':state.get('error')})
if state['status']=='failed':raise SystemExit(1)
