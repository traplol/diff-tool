import hashlib,importlib.util,json,os,pathlib,shutil,sys,threading,time,traceback
B=pathlib.Path('/home/max/benchmarks/branchline-boundary');L='native-helper-deployment-b2de070-03fecde11c0a';S=B/(L+'-input/source');O=B/'nhg-long-diag-04';O.mkdir(exist_ok=False)
P=B/(L+'-linux-correctness-02')/'blocked-native';shutil.copytree(P,O/'preserved-original-long-profile')
SHA='6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2';exe=P/'cache/branchline/git-workers'/('branchline-git-worker-'+SHA+'.exe')
import subprocess
unc=subprocess.check_output(['/usr/bin/wslpath','-w',str(exe)],text=True).rstrip('\r\n')
os.environ['LOCALAPPDATA']='C:\\Users\\max\\branchline-bench\\'+L+'-first-linux-gate-01\\blocked-native-cache'
entries=[x for x in os.environ.get('WSLENV','').split(':') if x and x.split('/')[0].casefold()!='localappdata'];os.environ['WSLENV']=':'.join(entries+['LOCALAPPDATA/w'])
sys.path.insert(0,str(S/'tools/autoresearch/wsl-boundary'));from driver import WebKitDriver
spec=importlib.util.spec_from_file_location('diag_launcher',S/'tools/autoresearch/wsl-boundary/launch_linux.py');launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
state={'pid':os.getpid(),'start_ticks':pathlib.Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19],'status':'running','fallback_unc':unc,'fallback_utf16_units':len(unc.encode('utf-16-le'))//2,'cache_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'cases':[],'no_production_change':True,'not_a_score':True}
def save():(O/'result.json').write_text(json.dumps(state,indent=2)+'\n')
save();print(json.dumps({'phase':'long-fallback-diag-start','pid':state['pid'],'start_ticks':state['start_ticks'],'record':str(O/'result.json')}),flush=True)
for name,binary,digest,source_hash in [
 ('current',B/'binaries'/L/'branchline','67815591856441398d6d026bb9f828a1d67a71f73b3c241b802715f033a0fcbf','252dec099fcf4ca2187615b852730458a47c1a13a5070fae6081574792a85500'),
 ('unchanged-b2de070',B/'binaries/checkpoint-b2de070/branchline','78106ff431e6433195867048f5fae946bb1e63cc0f04f23d668be32956c444c4','56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272')]:
    c={'name':name,'binary':str(binary),'source_hash':source_hash};state['cases'].append(c);save();record=None;t=None;errors=[]
    def supervise():
        try:launcher.supervise({'action':'start','binary':str(binary),'driver_binary':'/usr/bin/WebKitWebDriver','profile':str(P),'port':29361,'mcp_port':28961,'source_hash':source_hash})
        except BaseException:errors.append(traceback.format_exc())
    try:
        assert hashlib.sha256(binary.read_bytes()).hexdigest()==digest
        old=(P/'app.json').stat().st_mtime_ns if (P/'app.json').exists() else 0
        t=threading.Thread(target=supervise,daemon=True);t.start();until=time.monotonic()+25
        while (P/'app.json').stat().st_mtime_ns==old:
            if errors:raise RuntimeError(errors)
            if time.monotonic()>until:raise TimeoutError('Launch25s')
            time.sleep(.05)
        record=json.loads((P/'app.json').read_text());c['launch']=record
        d=WebKitDriver(29361,record['session'],timeout=25)
        d.wait("typeof window.__TAURI_INTERNALS__?.invoke === 'function' && document.querySelector('#welcome-open')?.getClientRects().length && !document.querySelector('#app')?.hasAttribute('aria-busy') && document.querySelector('#status')?.classList.contains('error')",timeout=20)
        probe=(S/'tools/autoresearch/wsl-boundary/probe.js').read_text().replace('call.error = "Native IPC returned an error";','{ call.error = "Native IPC returned an error"; call.native_error = result; }')
        d.evaluate(probe+'\nreturn true;');d.evaluate("window.boundaryProbe.chooseRoot('/mnt/c/Users/max/branchline-bench/kernel-windows');");d.click('#welcome-open')
        observed=d.wait("(() => {const calls=window.boundaryProbe.calls();const call=calls.findLast(c=>c.command==='workspace' && c.op==='open');const e=document.querySelector('#status');if(call?.end!==undefined && e?.classList.contains('error'))return {outcome:'native_error',text:e.textContent,nativeResponse:call.native_error,calls};if(window.boundaryProbe.state()?.repo?.root==='/mnt/c/Users/max/branchline-bench/kernel-windows' && !document.querySelector('#app')?.hasAttribute('aria-busy'))return {outcome:'success',calls};return false;})()",timeout=15)
        c['observed']=observed;d.screenshot(O/(name+'.png'));c['fallback_sha256_after']=hashlib.sha256(exe.read_bytes()).hexdigest()
        print(json.dumps({'phase':'long-fallback-observed','case':name,'outcome':observed['outcome'],'text':observed.get('text'),'nativeResponse':observed.get('nativeResponse'),'utf16_units':state['fallback_utf16_units']}),flush=True)
    except BaseException:c['error']=traceback.format_exc();print(json.dumps({'phase':'long-fallback-diag-error','case':name,'error':c['error']}),flush=True)
    finally:
        if record:
            c['stopped']=launcher.stop_record(record)
            c['gui_absent']=launcher.process_info(record['pid']) is None
        if t:t.join(timeout=12);c['thread_alive']=t.is_alive()
        c['errors']=errors;save()
        for f in ['app.json','webdriver.log']:
            if (P/f).exists():shutil.copy2(P/f,O/(name+'-'+f))
state['status']='complete';state['same_native_error']=len(state['cases'])==2 and all(c.get('observed',{}).get('outcome')=='native_error' for c in state['cases']) and state['cases'][0]['observed'].get('nativeResponse')==state['cases'][1]['observed'].get('nativeResponse');save();print(json.dumps({'phase':'long-fallback-diag-complete','result':state}),flush=True)
