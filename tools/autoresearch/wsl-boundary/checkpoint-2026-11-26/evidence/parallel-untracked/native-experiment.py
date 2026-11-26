#!/usr/bin/env python3
"""Serial backend-only parallel-untracked experiment; run only in the owned WSL VM."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import traceback


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def ps(script):
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    data = subprocess.check_output([
        '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
        '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], timeout=30)
    return json.loads(data.decode('utf-8-sig').strip())


def native_identity(pid):
    return ps("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
              f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}';"
              "if($null -eq $p){'null'}else{[ordered]@{pid=$p.ProcessId;"
              "created=$p.CreationDate.ToString('o');exe=$p.ExecutablePath}|ConvertTo-Json -Compress}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.release != 'VM PARALLEL UNTRACKED NATIVE RELEASED':
        parser.error('Wait for the root agent to release the serial VM slot')
    inputs = args.input.resolve()
    plan = json.loads((inputs/'plan.json').read_text())
    output = Path(plan['output']); output.mkdir(exist_ok=False)
    native = Path(plan['native_output']); native.mkdir(parents=True, exist_ok=False)
    state = {'pid':os.getpid(), 'start_ticks':Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19],
             'started':time.time(), 'status':'running', 'plan':plan, 'phases':[], 'runs':[]}
    def save():
        p=output/'state.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(state,indent=2)+'\n');t.replace(p)
    def source_check():
        for name,digest in plan['source']['files'].items():
            assert sha(inputs/'source'/name)==digest, name
    def guard():
        return {name: {'sha256':sha(Path(plan['root'])/'.git'/name),
                       **{key:getattr((Path(plan['root'])/'.git'/name).stat(),key)
                          for key in ['st_size','st_mtime_ns','st_ctime_ns','st_ino','st_dev','st_mode']}}
                for name in ['index','HEAD','config']}
    def fingerprint():
        # Same native-Git commands as the existing Windows controls; read-only verification only.
        env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1')
        shared=['GIT_OPTIONAL_LOCKS','GIT_TERMINAL_PROMPT','GIT_NO_LAZY_FETCH']
        env['WSLENV']=':'.join([v for v in env.get('WSLENV','').split(':') if v and v.split('/')[0] not in shared]+shared)
        def git(argv):
            command=[plan['git'],'--no-pager','--literal-pathspecs','-C',plan['native_root']]
            if argv[0]=='diff':command+=['-c','diff.autoRefreshIndex=false']
            return subprocess.check_output(command+argv,env=env,timeout=180)
        h=hashlib.sha256()
        for argv in [['rev-parse','HEAD'],['show-ref'],['ls-files','--stage','-z'],
                     ['status','--porcelain=v1','-z','--untracked-files=all'],
                     ['diff','--cached','--binary','--no-ext-diff'],['diff','--binary','--no-ext-diff']]: h.update(git(argv))
        for name in sorted(git(['ls-files','--others','--exclude-standard','-z']).split(b'\0')):
            if name:h.update(name);h.update((Path(plan['root'])/os.fsdecode(name)).read_bytes())
        value=h.hexdigest();assert value==plan['fixture_sha256'],value;return value
    failure=None
    try:
        save(); source_check()
        for name,digest in plan['support_files'].items(): assert sha(inputs/name)==digest,name
        host_proof=json.loads((inputs/'host-proof.json').read_text());assert host_proof['candidate_source_hash']==plan['source']['source_hash'];assert host_proof['tests']==plan['host_checks']['tests']
        assert sha(plan['baseline_worker']['path'])==plan['baseline_worker']['sha256']
        assert sha(plan['git'])==plan['git_sha256']
        for key in os.environ:
            assert not (key.startswith('GIT_TRACE') or key in ['GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES']), 'Unexpected Git environment: '+key
        state['guard_before']=guard();state['fingerprint_before']=fingerprint();assert guard()==state['guard_before'];save()
        env=dict(os.environ,**plan['build_environment']);env['PATH']='/home/max/.cargo/bin:'+env.get('PATH','')
        for key in ['CARGO_ENCODED_RUSTFLAGS','BRANCHLINE_GIT_WORKER_PATH']: env.pop(key,None)
        def run_phase(name, command, cwd):
            phase={'name':name,'argv':command,'cwd':str(cwd),'environment':plan['build_environment'],'started':time.time()}
            state['phases'].append(phase);save()
            path=output/(name+'.log')
            with path.open('wb') as log:
                child=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
                phase['pid']=child.pid;phase['start_ticks']=Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ',1)[1].split()[19];save()
                phase['exit']=child.wait()
            phase['finished']=time.time();phase['log_sha256']=sha(path);save();assert phase['exit']==0,(name,phase['exit'])
            return path
        manifest=str(inputs/'source/src-tauri/git-worker/Cargo.toml')
        build=['cargo','xwin','build','--offline','--locked','--release','--manifest-path',manifest,'--target','x86_64-pc-windows-msvc']
        run_phase('build-candidate-worker',build,inputs/'source')
        built=Path(env['CARGO_TARGET_DIR'])/'x86_64-pc-windows-msvc/release/branchline-git-worker.exe'
        candidate=native/'candidate-worker.exe';shutil.copy2(built,candidate);assert sha(candidate)==sha(built)
        imports=subprocess.check_output(['objdump','-p',str(candidate)],text=True);(output/'imports.txt').write_text(imports)
        dlls=[x.split(':',1)[1].strip() for x in imports.splitlines() if 'DLL Name:' in x]
        assert not any(any(v in x.lower() for v in ['vcruntime','msvcp','ucrtbase']) for x in dlls),dlls
        state['candidate_worker']={'path':str(candidate),'sha256':sha(candidate),'bytes':candidate.stat().st_size,'imports':dlls,'static_crt':True}
        test_log=run_phase('build-native-worker-unit-tests',
            ['cargo','xwin','test','--offline','--locked','--release','--manifest-path',manifest,
             '--target','x86_64-pc-windows-msvc','--bin','branchline-git-worker','--no-run','--message-format=json'],inputs/'source')
        artifacts=[]
        for line in test_log.read_text().splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('reason')=='compiler-artifact' and value.get('profile',{}).get('test') and value.get('executable'):artifacts.append(Path(value['executable']))
        assert len(artifacts)==1,artifacts
        unit=native/'worker-unit-tests.exe';shutil.copy2(artifacts[0],unit);assert sha(unit)==sha(artifacts[0])
        state['native_unit_tests']={'path':str(unit),'sha256':sha(unit),'source_artifact':str(artifacts[0])};save()
        run_phase('native-worker-unit-tests',[str(unit),'--test-threads=1'],native)
        state['versions']={k:subprocess.check_output(v,env=env,text=True).strip() for k,v in {'rustc':['rustc','-Vv'],'cargo_xwin':['cargo','xwin','--version'],'git':[plan['git'],'--version']}.items()};save()
        helper=module('backend',inputs/'backend_compare.py')
        manifest=json.loads((inputs/'workload.json').read_text()); expected={(g,p):info for g,files in manifest['local'].items() for p,info in files.items()};assert len(expected)==15
        baseline_tree=None; baseline_patches=None; raw=[]
        active=native/'branchline-git-worker.exe'
        state['cwd_probe']=subprocess.check_output(['/mnt/c/Windows/System32/cmd.exe','/d','/c','cd'],cwd=plan['root']).decode('utf-8-sig').strip()
        assert state['cwd_probe'].replace('\\','/').casefold()==plan['native_root'].casefold(),state['cwd_probe']
        for number,label in enumerate(plan['run_order']):
            source=Path(plan['baseline_worker']['path']) if label=='A' else candidate
            shutil.copy2(source,active);assert sha(source)==sha(active)
            records=[]; worker=helper.Worker(active,f'{number}-{label}',output,records,cwd=plan['root'])
            run={'variant':label,'number':number,'binary_sha256':sha(active),'launcher_pid':worker.process.pid,'launcher_start_ticks':Path(f'/proc/{worker.process.pid}/stat').read_text().rsplit(') ',1)[1].split()[19],'records':records,'requests':[]};state['runs'].append(run);save()
            identity=None
            try:
                def call(phase,op,iteration=0,**kwargs):
                    result=worker.call(phase,op,iteration,**kwargs)
                    run['requests'].append({'phase':phase,'iteration':iteration,'result':result});save();return result
                hello=call('hello','hello');assert hello['os']=='windows' and hello['protocol']==1
                identity=native_identity(hello['pid']);assert identity and identity['exe'].replace('\\','/').casefold()==plan['native_active'].casefold(),identity
                run['native_identity']=identity;save()
                opened=call('open','open',path=plan['native_root']);view=opened['repo'];assert view['checkout']==manifest['refs'][-1]
                for iteration in range(6):
                    tree=call('first_working_tree' if iteration==0 else 'working_tree','working_tree',iteration,view=view,checkout=view['checkout'],untracked_paths=None)
                    assert {(f['group'],f['path']) for f in tree['files']}==set(expected) and len(tree['files'])==15
                    if baseline_tree is None:baseline_tree=tree
                    assert tree==baseline_tree,'Raw frozen working-tree metadata/sections differ'
                # Keep validation calls out of the timed six-request sequence.
                patches={}
                for file in tree['files']:
                    key=(file['group'],file['path']);patch=call('validate_patch','patch',comparison=helper.header(tree),file=file)
                    assert any(expected[key]['marker'] in row['text'] and row.get('new')==expected[key]['line'] for row in patch),key
                    patches['/'.join(key)]=patch
                if baseline_patches is None:baseline_patches=patches
                assert patches==baseline_patches,'Raw frozen patches differ'
                assert (output/f'{number}-{label}.stderr').stat().st_size==0,'Unexpected worker stderr; no tracer/profiler is allowed'
                assert call('final_hello','hello')['pid']==hello['pid']
                assert native_identity(hello['pid'])==identity
            finally:
                worker.close();run['launcher_exit']=worker.process.returncode
                after=native_identity(identity['pid']) if identity else None;run['native_after']=after
                if after is not None:
                    assert after==identity,'Native PID identity changed; no cleanup authorized'
                    # Hold a process handle, then recheck creation+image before killing it.
                    quoted_exe=identity['exe'].replace("'","''");quoted_created=identity['created'].replace("'","''")
                    script=("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
                            f"$owned=[Diagnostics.Process]::GetProcessById({identity['pid']});$null=$owned.Handle;"
                            f"$again=Get-CimInstance Win32_Process -Filter 'ProcessId={identity['pid']}';"
                            f"if($null -eq $again -or $again.CreationDate.ToString('o') -cne '{quoted_created}' -or $again.ExecutablePath -ine '{quoted_exe}'){{throw 'Owned process changed; refusing kill'}};"
                            "$owned.Kill();$null=$owned.WaitForExit(5000);'true'")
                    assert ps(script) is True
                    run['forced_native_cleanup']=True
                    run['native_after_forced_cleanup']=native_identity(identity['pid'])
                save()
                assert run['launcher_exit']==0 and after is None,'Worker EOF did not exit cleanly; run invalid'
            raw.extend(records)
        state['wire_and_patch_parity']=True;state['valid']=True
        metrics={}
        for label in ['A','B']:
            metrics[label]={}
            for phase in ['hello','open','first_working_tree','working_tree']:
                vals=[r['elapsed_ns']/1e6 for r in raw if r['variant'].endswith('-'+label) and r['phase']==phase]
                metrics[label][phase]={'samples_ms':vals,'p50_ms':statistics.median(vals),'max_ms':max(vals)}
        state['metrics']=metrics
        state['interpretation']='Backend-only preliminary evidence, not GUI acceptance or a promoted speedup. Exact same NTFS helper path and repository cwd, serial A/B/B/A with one first and five repeated WT requests per fresh worker. Raw frozen metadata, sections and patches must agree across all24 WT requests. Fresh processes are not OS-cold. Canonical GUI scoring is still required.'
    except BaseException as error:
        failure=error;state.update(valid=False,error=str(error),traceback=traceback.format_exc())
    finally:
        if 'guard_before' in state:
            try:
                state['fingerprint_after']=fingerprint();state['guard_after']=guard();assert state['guard_after']==state['guard_before'];source_check()
                assert sha(plan['baseline_worker']['path'])==plan['baseline_worker']['sha256'];assert sha(plan['git'])==plan['git_sha256']
                if 'candidate_worker' in state:assert sha(state['candidate_worker']['path'])==state['candidate_worker']['sha256']
                if 'native_unit_tests' in state:assert sha(state['native_unit_tests']['path'])==state['native_unit_tests']['sha256']
            except BaseException as error:state['final_guard_error']=str(error);failure=failure or error;state['valid']=False
        state.update(status='failed' if failure else 'complete-backend-preliminary-only',finished=time.time());save()
    if failure:raise failure
    print(json.dumps({'state':str(output/'state.json'),'valid':True,'metrics':state['metrics']},indent=2))

if __name__=='__main__':main()
