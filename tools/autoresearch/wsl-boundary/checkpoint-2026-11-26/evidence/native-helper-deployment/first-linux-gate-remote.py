import base64,hashlib,importlib.util,json,os,pathlib,signal,subprocess,sys,threading,time,traceback
B=pathlib.Path('/home/max/benchmarks/branchline-boundary')
LABEL='native-helper-deployment-b2de070-03fecde11c0a'
S=B/(LABEL+'-input/source'); O=B/(LABEL+'-first-linux-gate-01'); O.mkdir(exist_ok=False)
P=O/'profile'; binary=B/'binaries'/LABEL/'branchline'
native_base=pathlib.Path('/mnt/c/Users/max/branchline-bench')/(LABEL+'-first-linux-gate-01')/"native cache's réview &[]"
native_windows="C:\\Users\\max\\branchline-bench\\"+LABEL+"-first-linux-gate-01\\native cache's réview &[]"
digest='6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'
cache=native_base/'Branchline/git-workers'/('branchline-git-worker-'+digest+'.exe')
state={'supervisor_pid':os.getpid(),'supervisor_start_ticks':pathlib.Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19],
       'status':'starting','profile':str(P),'source_hash':'252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500',
       'binary':str(binary),'native_cache':str(cache),'native_cache_existed':cache.exists(),'diagnostic_only':True}
def save(): (O/'result.json').write_text(json.dumps(state,indent=2)+'\n')
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
launcher=load('native_gate_launcher',S/'tools/autoresearch/wsl-boundary/launch_linux.py')
sys.path.insert(0,str(S/'tools/autoresearch/wsl-boundary'));from driver import WebKitDriver
os.environ['LOCALAPPDATA']=native_windows
entries=[x for x in os.environ.get('WSLENV','').split(':') if x and x.split('/')[0].casefold()!='localappdata']
os.environ['WSLENV']=':'.join(entries+['LOCALAPPDATA/w'])
state['normal_cache_environment']={'LOCALAPPDATA':native_windows,'WSLENV':os.environ['WSLENV']}
assert not cache.exists(), 'Gate cache must begin absent'
# Confirm standard environment transfer before allowing a product cache write.
query=subprocess.run(['cmd.exe','/d','/u','/c','set LOCALAPPDATA'],env=os.environ,capture_output=True,check=True,timeout=10)
value=[line.partition('=')[2] for line in query.stdout.decode('utf-16-le').splitlines() if line.partition('=')[0].casefold()=='localappdata']
assert value==[native_windows],value
state['cmd_portable_cache_query']={'argv':['cmd.exe','/d','/u','/c','set LOCALAPPDATA'],'value':value[0],'stdout_base64':base64.b64encode(query.stdout).decode()}
params={'action':'start','binary':str(binary),'driver_binary':'/usr/bin/WebKitWebDriver','profile':str(P),'port':29341,'mcp_port':28941,'source_hash':state['source_hash']}
errors=[]
def supervise():
    try: launcher.supervise(params)
    except BaseException: errors.append(traceback.format_exc())
t=threading.Thread(target=supervise,daemon=True); record=None; d=None
save();print(json.dumps({'phase':'starting-linux-gui','pid':state['supervisor_pid'],'start_ticks':state['supervisor_start_ticks'],'record':str(O/'result.json')}),flush=True)
try:
    assert hashlib.sha256(binary.read_bytes()).hexdigest()=='67815591856441398d6d026bb9f828a1d67a71f73b3c241b802715f033a0fcbf'
    t.start(); deadline=time.monotonic()+25
    while not (P/'app.json').exists():
        if errors: raise RuntimeError(errors)
        if time.monotonic()>deadline: raise TimeoutError('No GUI launch record in25s')
        time.sleep(.05)
    record=json.loads((P/'app.json').read_text());state['launch']=record;save()
    d=WebKitDriver(record['port'],record['session'],timeout=35)
    ready="typeof window.__TAURI_INTERNALS__?.invoke === 'function' && document.querySelector('#welcome-open')?.getClientRects().length && !document.querySelector('#app')?.hasAttribute('aria-busy') && document.querySelector('#status')?.classList.contains('error')"
    d.wait(ready,timeout=25)
    d.evaluate((S/'tools/autoresearch/wsl-boundary/probe.js').read_text()+'\nreturn true;')
    root='/mnt/c/Users/max/branchline-bench/kernel-windows'
    d.evaluate('window.boundaryProbe.chooseRoot(arguments[0]);',root)
    d.click('#welcome-open')
    d.wait("window.boundaryProbe.state()?.repo?.root === arguments[0] && !document.querySelector('#app')?.hasAttribute('aria-busy') && [...document.querySelectorAll('#diff .cm-content')].some(n=>n.getClientRects().length)",root,timeout=30)
    # Preserve the canonical two-frame completion settle unchanged.
    d.evaluate('await window.boundaryProbe.settle();')
    actual=d.evaluate('return window.boundaryProbe.state();')
    assert not actual.get('mcp_warning') and not actual.get('config_warning'), actual.get('mcp_warning') or actual.get('config_warning')
    state['opened']={'root':actual['repo']['root'],'checkout':actual['repo']['checkout'],'refs':actual['repo']['refs'],'stack':actual['stack'],'pair':actual['pair'],
                     'comparison':{k:actual['comparison'].get(k) for k in ['left','right','base','head']},'file_count':len(actual['comparison']['files'])}
    assert cache.is_file(), 'Product did not materialize the isolated native Windows cache'
    assert hashlib.sha256(cache.read_bytes()).hexdigest()==digest
    state['native_cache_installed']={'sha256':digest,'bytes':cache.stat().st_size,'mtime_ns':cache.stat().st_mtime_ns}
    state['frames']=d.evaluate('''
        const before={visibilityState:document.visibilityState,hasFocus:document.hasFocus(),viewport:[innerWidth,innerHeight],
          activeElement:{tag:document.activeElement?.tagName,id:document.activeElement?.id,className:String(document.activeElement?.className??'')}};
        const times=[];
        for(let i=0;i<13;i++){await new Promise(requestAnimationFrame);times.push(performance.now());}
        return {diagnosticOnly:true,completionSettleFramesUnchanged:2,before,times_ms:times,
          deltas_ms:times.slice(1).map((t,i)=>t-times[i]),
          after:{visibilityState:document.visibilityState,hasFocus:document.hasFocus(),viewport:[innerWidth,innerHeight],
            activeElement:{tag:document.activeElement?.tagName,id:document.activeElement?.id,className:String(document.activeElement?.className??'')}}};
    ''')
    d.screenshot(O/'opened.png')
    state['status']='open-cache-and-frame-diagnostic-passed';save()
    print(json.dumps({'phase':'linux-open-and-raf-complete','pid':state['supervisor_pid'],'result':state}),flush=True)
except BaseException:
    state['status']='failed';state['error']=traceback.format_exc();save();print(json.dumps({'phase':'failed','error':state['error']}),flush=True)
finally:
    if record:
        try: state['stopped_owned_pids']=launcher.stop_record(record)
        except BaseException: state['cleanup_error']=traceback.format_exc()
    t.join(timeout=12)
    state['supervisor_thread_alive']=t.is_alive();state['supervisor_errors']=errors
    if record:
        state['gui_absent']=launcher.process_info(record['pid']) is None
        state['driver_absent']=launcher.process_info(record['driver_process']['pid']) is None
    save();print(json.dumps({'phase':'linux-first-gate-cleanup','result':state}),flush=True)
if state['status']=='failed' or state.get('cleanup_error') or state.get('supervisor_thread_alive'): raise SystemExit(1)
