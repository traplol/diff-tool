import base64,hashlib,importlib.util,json,os,pathlib,queue,signal,socket,subprocess,sys,threading,time,traceback
B=pathlib.Path('/home/max/benchmarks/branchline-boundary');L='native-helper-deployment-b2de070-03fecde11c0a';S=B/(L+'-input/source')
O=B/(L+'-linux-correctness-02');O.mkdir(exist_ok=False)
APP=B/'binaries'/L/'branchline';SHA='6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'
N=pathlib.Path('/mnt/c/Users/max/branchline-bench')/(L+'-first-linux-gate-01')/"native cache's réview &[]"
NW='C:\\Users\\max\\branchline-bench\\'+L+"-first-linux-gate-01\\native cache's réview &[]"
NAME='branchline-git-worker-'+SHA+'.exe';IMAGE=N/'Branchline/git-workers'/NAME;WINIMAGE=NW+'\\Branchline\\git-workers\\'+NAME
ROOT='/mnt/c/Users/max/branchline-bench/kernel-windows';CONTROL=str(B/'kernel-wsl');PORT=29351;MCP=28951
sys.path.insert(0,str(S/'tools/autoresearch/wsl-boundary'));from driver import WebKitDriver
spec=importlib.util.spec_from_file_location('gate_launcher',S/'tools/autoresearch/wsl-boundary/launch_linux.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
import workload
state={'pid':os.getpid(),'start_ticks':pathlib.Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19],'source_hash':'252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500','status':'running','cases':[],'not_a_score':True}
active=None;base_env=dict(os.environ)
def save(): (O/'result.json').write_text(json.dumps(state,indent=2)+'\n')
def event(name,data=None): print(json.dumps({'phase':name,'pid':state['pid'],'data':data}),flush=True)
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def ps(body):
    command="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"+body
    r=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(command.encode('utf-16-le')).decode()],stdin=subprocess.DEVNULL,capture_output=True,timeout=20)
    if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace'))
    return json.loads(r.stdout.decode('utf-8-sig'))
def native_workers(path):
    encoded=base64.b64encode(path.encode()).decode()
    return ps("$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));$a=@(Get-CimInstance Win32_Process -Filter \"Name = '"+NAME+"'\" | Where-Object {$_.ExecutablePath -eq $p} | ForEach-Object {$w=$_;$cpu=Get-Process -Id $w.ProcessId -ErrorAction SilentlyContinue;[pscustomobject]@{pid=[int]$w.ProcessId;parent=[int]$w.ParentProcessId;created=$w.CreationDate.ToUniversalTime().ToString('o');binary=$w.ExecutablePath;command=$w.CommandLine;cpu_seconds=$cpu.CPU;children=@(Get-CimInstance Win32_Process -Filter ('ParentProcessId='+$w.ProcessId)|ForEach-Object{[pscustomobject]@{pid=[int]$_.ProcessId;binary=$_.ExecutablePath;command=$_.CommandLine;created=$_.CreationDate.ToUniversalTime().ToString('o')}})}});ConvertTo-Json -InputObject $a -Compress -Depth 8")
def wait_native_gone(identities,path,deadline=10):
    began=time.monotonic()
    while True:
        live=native_workers(path); remaining=[w for w in live if any(w['pid']==i['pid'] and w['created']==i['created'] for i in identities)]
        if not remaining:return {'gone':True,'elapsed_seconds':time.monotonic()-began,'remaining':[]}
        if time.monotonic()-began>=deadline:return {'gone':False,'elapsed_seconds':time.monotonic()-began,'remaining':remaining}
        time.sleep(.05)
def env(cache,without_cmd=False):
    os.environ.clear();os.environ.update(base_env);os.environ['LOCALAPPDATA']=cache
    entries=[x for x in os.environ.get('WSLENV','').split(':') if x and x.split('/')[0].casefold()!='localappdata'];os.environ['WSLENV']=':'.join(entries+['LOCALAPPDATA/w'])
    if without_cmd:
        import shutil
        folder=str(pathlib.Path(shutil.which('cmd.exe')).parent).casefold();os.environ['PATH']=':'.join(x for x in os.environ['PATH'].split(':') if x.casefold()!=folder)
        assert shutil.which('cmd.exe') is None and shutil.which('powershell.exe')
def start(name,cache=NW,without_cmd=False):
    global active
    env(cache,without_cmd);profile=O/name;errors=[]
    params={'action':'start','binary':str(APP),'driver_binary':'/usr/bin/WebKitWebDriver','profile':str(profile),'port':PORT,'mcp_port':MCP,'source_hash':state['source_hash']}
    def supervise():
        try:launcher.supervise(params)
        except BaseException:errors.append(traceback.format_exc())
    t=threading.Thread(target=supervise,daemon=True);t.start();until=time.monotonic()+25
    while not (profile/'app.json').exists():
        if errors:raise RuntimeError(errors)
        if time.monotonic()>until:raise TimeoutError('App launch25s')
        time.sleep(.05)
    record=json.loads((profile/'app.json').read_text());d=WebKitDriver(PORT,record['session'],timeout=35)
    active={'record':record,'thread':t,'errors':errors,'driver':d,'profile':profile}
    d.wait("typeof window.__TAURI_INTERNALS__?.invoke === 'function' && document.querySelector('#welcome-open')?.getClientRects().length && !document.querySelector('#app')?.hasAttribute('aria-busy') && document.querySelector('#status')?.classList.contains('error')",timeout=25)
    d.evaluate((S/'tools/autoresearch/wsl-boundary/probe.js').read_text()+'\nreturn true;');open_ui(ROOT,True)
    return active
def open_ui(root,first=False):
    d=active['driver'];d.evaluate('window.boundaryProbe.chooseRoot(arguments[0]);',root);d.click('#welcome-open' if first else '#choose')
    d.wait("window.boundaryProbe.state()?.repo?.root===arguments[0] && !document.querySelector('#app')?.hasAttribute('aria-busy') && [...document.querySelectorAll('#diff .cm-content')].some(n=>n.getClientRects().length)",root,timeout=30)
    d.evaluate('await window.boundaryProbe.settle();');s=d.evaluate('return window.boundaryProbe.state();')
    assert not s.get('mcp_warning') and not s.get('config_warning'),s.get('mcp_warning') or s.get('config_warning')
    assert s['repo']['refs']['refs/heads/main']==workload.BASE
    return {'root':s['repo']['root'],'checkout':s['repo']['checkout'],'snapshot':s['snapshot'],'pair':s['pair'],'files':len(s['comparison']['files'])}
def stop():
    global active
    if not active:return {}
    a=active;active=None;stopped=launcher.stop_record(a['record']);a['thread'].join(timeout=12)
    assert not a['thread'].is_alive(), 'Launcher thread did not finish'
    assert not a['errors'],a['errors']
    assert launcher.process_info(a['record']['pid']) is None
    assert launcher.process_info(a['record']['driver_process']['pid']) is None
    return {'stopped':stopped,'gui_absent':True,'driver_absent':True}
def terminate_gui():
    identity=active['record']['app_process'];assert launcher.process_info(identity['pid'])=={k:identity[k] for k in ['pid','start_ticks','binary']}
    os.kill(identity['pid'],signal.SIGKILL)
def case(name,body):
    c={'name':name,'started':time.time()};state['cases'].append(c);state['current_case']=name;save();event(name)
    try:c['proof']=body();c['passed']=True
    except BaseException:c['passed']=False;c['error']=traceback.format_exc();raise
    finally:
        try:c['cleanup']=stop()
        except BaseException:c['cleanup_error']=traceback.format_exc();c['passed']=False;raise
        c['finished']=time.time();save()
    event(name+'-passed',c['proof'])
def hit_drop():
    before=IMAGE.stat().st_mtime_ns;a=start('hit-drop');workers=native_workers(WINIMAGE);assert len(workers)==1,workers
    assert sha(IMAGE)==SHA and IMAGE.stat().st_mtime_ns==before
    original=workers[0];control=open_ui(CONTROL);gone=wait_native_gone([original],WINIMAGE);assert gone['gone'],gone
    assert launcher.process_info(a['record']['pid']) is not None
    return {'native_cache_hit_no_rewrite':True,'worker':original,'normal_connection_drop':gone,'gui_stayed_alive':True,'control_root':control}
def repaired():
    assert sha(IMAGE)==SHA;IMAGE.write_bytes(b'owned gate corrupted cache');a=start('corrupt-repair');assert sha(IMAGE)==SHA
    workers=native_workers(WINIMAGE);assert len(workers)==1,workers
    return {'repaired_sha256':SHA,'worker':workers[0]}
def blocked():
    blocker=N.parent/'blocked-native-cache';blocker.write_text('owned cache failure fixture')
    win=NW.rsplit('\\',1)[0]+'\\blocked-native-cache';a=start('blocked-native',win)
    fallback=a['profile']/'cache/branchline/git-workers'/NAME;assert sha(fallback)==SHA
    translated=subprocess.check_output(['/usr/bin/wslpath','-w',str(fallback)],text=True).rstrip('\r\n')
    workers=native_workers(translated);assert len(workers)==1,workers
    assert blocker.is_file()
    return {'native_cache_blocked':str(blocker),'gui_cache_fallback':str(fallback),'sha256':SHA,'worker':workers[0]}
def no_cmd():
    a=start('cmd-unavailable',without_cmd=True);assert sha(IMAGE)==SHA;workers=native_workers(WINIMAGE);assert len(workers)==1,workers
    return {'cmd_unavailable':True,'powershell_fallback_native_cache':True,'worker':workers[0]}
def gui_idle():
    a=start('gui-idle-death');workers=native_workers(WINIMAGE);assert len(workers)==1,workers
    terminate_gui();gone=wait_native_gone(workers,WINIMAGE);assert gone['gone'],gone
    return {'abrupt_gui':a['record']['app_process'],'worker':workers[0],'cleanup':gone}
def gui_busy():
    a=start('gui-busy-death');d=a['driver'];workers=native_workers(WINIMAGE);assert len(workers)==1,workers;proof=None
    for attempt in range(3):
        d.click('#local-review' if attempt%2==0 else '#stack-review')
        observed=native_workers(WINIMAGE)
        pending=d.evaluate("return window.boundaryProbe.calls().some(c=>c.command==='workspace' && c.end===undefined);")
        if pending and any(w.get('children') for w in observed):proof={'attempt':attempt,'pending_real_ipc':pending,'worker_observation':observed};break
        d.wait("!document.querySelector('#app')?.hasAttribute('aria-busy')",timeout=30)
    assert proof,'Could not establish pending IPC plus active native Git child in3 attempts'
    terminate_gui();gone=wait_native_gone(workers,WINIMAGE);assert gone['gone'],gone
    return {'busy_proof':proof,'abrupt_gui':a['record']['app_process'],'cleanup':gone}
def rpc(name,args={}):
    from urllib import request
    payload={'jsonrpc':'2.0','id':71,'method':'tools/call','params':{'name':name,'arguments':args}}
    req=request.Request('http://127.0.0.1:'+str(MCP)+'/mcp',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
    with request.urlopen(req,timeout=30) as r:data=json.load(r)
    assert data['id']==71 and not data['result'].get('isError'),data
    return data['result']['structuredContent']
def mcp_death(busy):
    a=start('mcp-busy-death' if busy else 'mcp-idle-death');gui=native_workers(WINIMAGE);assert len(gui)==1,gui
    mcps=[p for p in launcher.profile_processes(APP,a['profile']) if '--mcp' in p['args']];assert len(mcps)==1,mcps;mcp=mcps[0]
    proof={'mcp':mcp,'gui_worker':gui[0]};targets=[];errors=[];t=None
    if busy:
        def work():
            try:rpc('list_changes',{'pair':['refs/heads/feature/boundary-final',':worktree:']})
            except BaseException:errors.append(traceback.format_exc())
        for attempt in range(3):
            t=threading.Thread(target=work,daemon=True);t.start();observed=native_workers(WINIMAGE)
            targets=[w for w in observed if w['pid']!=gui[0]['pid'] and w.get('children')]
            if t.is_alive() and targets:break
            t.join(timeout=30);assert not t.is_alive();targets=[]
        assert t.is_alive() and targets,'No active MCP native Git child in3 attempts'
        proof['busy_workers']=targets;proof['request_pending']=True
    else:
        repo=rpc('get_repository')['repository'];assert repo['root']==ROOT
        assert {w['pid'] for w in native_workers(WINIMAGE)}=={gui[0]['pid']}
        proof['no_idle_mcp_worker_expected']=True
    assert launcher.process_info(mcp['pid'])=={k:mcp[k] for k in ['pid','start_ticks','binary']};os.kill(mcp['pid'],signal.SIGKILL)
    if targets:
        gone=wait_native_gone(targets,WINIMAGE);assert gone['gone'],gone;proof['cleanup']=gone;t.join(timeout=5);proof['request_errors']=errors
    live=native_workers(WINIMAGE);assert {w['pid'] for w in live}=={gui[0]['pid']},live
    proof['gui_worker_preserved']=True;return proof
def raw_eof(busy):
    env(NW);e=dict(os.environ);keys={'GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0','LC_ALL':'C'}
    e.update(keys);entries=[x for x in e.get('WSLENV','').split(':') if x and x.split('/')[0].casefold() not in {k.casefold() for k in keys}];e['WSLENV']=':'.join(entries+[k+'/w' for k in keys])
    p=subprocess.Popen([str(IMAGE),'--stdio'],cwd=ROOT,env=e,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE);q=queue.Queue()
    def reader():
        for line in p.stdout:q.put(line)
        q.put(None)
    t=threading.Thread(target=reader,daemon=True);t.start();frames=[]
    def send(i,op,**args):p.stdin.write(json.dumps({'id':i,'op':op,**args},ensure_ascii=False).encode()+b'\n');p.stdin.flush()
    def receive(i):
        line=q.get(timeout=15);assert line and line.endswith(b'\n');r=json.loads(line);assert r['id']==i;rbytes=base64.b64encode(line).decode();frames.append({'id':i,'raw_base64':rbytes});return r
    try:
        send(1,'hello');hello=receive(1)['result'];assert hello['os']=='windows'
        send(2,'open',path='C:/Users/max/branchline-bench/kernel-windows');opened=receive(2)['result'];assert opened['repo']['refs']['refs/heads/main']==workload.BASE
        if busy:
            send(3,'working_tree',view=opened['repo'],checkout=opened['repo']['checkout'],untracked_paths=None);p.stdin.close();response=receive(3);assert len(response['result']['files'])==15
        else:
            send(3,'invalid_owned_protocol_fixture');assert 'error' in receive(3);send(4,'hello');assert receive(4)['result']['pid']==hello['pid'];p.stdin.close()
        assert q.get(timeout=15) is None;p.wait(timeout=10);assert p.returncode==0
        return {'interop_pid':p.pid,'hello':hello,'frames':frames,'busy_input_eof':busy,'exit':p.returncode,'stderr_base64':base64.b64encode(p.stderr.read()).decode(),'server_invalid_request_recovered':not busy}
    finally:
        if p.poll() is None:p.kill();p.wait(timeout=10)

save();event('linux-correctness-start',{'record':str(O/'result.json'),'start_ticks':state['start_ticks']})
try:
    assert sha(APP)=='67815591856441398d6d026bb9f828a1d67a71f73b3c241b802715f033a0fcbf';assert sha(IMAGE)==SHA
    state['fingerprint_before']={n:workload.fingerprint(p) for n,p in [('linux',workload.LINUX_ROOT),('windows',workload.WINDOWS_ROOT)]};assert set(state['fingerprint_before'].values())=={'db66016f41a604c102cc81121c4e81f9c93db3b3f4430ef51dab5ba1c9da97c2'};save()
    case('cache-hit-and-normal-connection-drop',hit_drop)
    case('corrupt-native-cache-repair',repaired)
    case('blocked-native-cache-fallback',blocked)
    case('cmd-unavailable-powershell-fallback',no_cmd)
    case('raw-worker-invalid-frame-recovery-and-idle-eof',lambda:raw_eof(False))
    case('raw-worker-busy-eof',lambda:raw_eof(True))
    case('abrupt-gui-idle-death',gui_idle)
    case('abrupt-gui-busy-death',gui_busy)
    case('abrupt-mcp-idle-death',lambda:mcp_death(False))
    case('abrupt-mcp-busy-death',lambda:mcp_death(True))
    state['status']='passed-linux-correctness-gates'
except BaseException:state['status']='failed';state['error']=traceback.format_exc()
finally:
    try:stop()
    except BaseException:state['final_cleanup_error']=traceback.format_exc()
    state['fingerprint_after']={n:workload.fingerprint(p) for n,p in [('linux',workload.LINUX_ROOT),('windows',workload.WINDOWS_ROOT)]}
    if state.get('fingerprint_before')!=state['fingerprint_after']:state['status']='failed';state['fingerprint_changed']=True
    state['finished']=time.time();save();event('linux-correctness-complete',{'status':state['status'],'record':str(O/'result.json'),'error':state.get('error')})
if state['status']=='failed':raise SystemExit(1)
