#!/usr/bin/env python3
"""Build only after root explicitly releases the integrated candidate's VM slot."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time
import traceback

BENCH = Path('/home/max/benchmarks/branchline-boundary')
WORKSPACE = Path('/home/max/workspace/diff-tool')
NATIVE_BENCH = Path('/mnt/c/Users/max/branchline-bench')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_start(pid):
    path = Path('/proc') / str(pid) / 'stat'
    return path.read_text().rsplit(') ', 1)[1].split()[19] if path.exists() else None


def stop(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            child.wait()
            return
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def powershell(script):
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    data=subprocess.check_output(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],timeout=30)
    return json.loads(data.decode('utf-8-sig').strip())


def native_windows_identity(pid):
    return powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"+f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}';"+"if($null -eq $p){'null'}else{[ordered]@{pid=$p.ProcessId;created=$p.CreationDate.ToString('o');exe=$p.ExecutablePath}|ConvertTo-Json -Compress}")


def stop_windows_owned(identity):
    exe=identity['exe'].replace("'","''");created=identity['created'].replace("'","''")
    script=("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"+f"$owned=[Diagnostics.Process]::GetProcessById({identity['pid']});$null=$owned.Handle;"+f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={identity['pid']}';"+f"if($null -eq $p -or $p.CreationDate.ToString('o') -cne '{created}' -or $p.ExecutablePath -ine '{exe}'){{throw 'Owned process identity changed'}};"+"$owned.Kill();$null=$owned.WaitForExit(5000);'true'")
    if powershell(script) is not True:raise RuntimeError('Owned Windows process cleanup failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.release != 'VM INTEGRATED CLI BUILD RELEASED':
        parser.error("Wait for root's VM INTEGRATED CLI BUILD RELEASED")
    inputs = args.input.resolve()
    plan = json.loads((inputs / 'build-plan.json').read_text())
    source = inputs / 'source'
    output = BENCH / (plan['label'] + '-native')
    output.mkdir(exist_ok=False)
    native_output = NATIVE_BENCH / 'binaries' / plan['label']
    native_output.mkdir(parents=True, exist_ok=False)
    record_path = output / 'supervisor.json'
    state = {'pid': os.getpid(), 'start_ticks': process_start(os.getpid()), 'started': time.time(),
             'status': 'running', 'source': plan['source'], 'release': args.release,
             'input': str(inputs), 'phases': [], 'windows_gui_requested': True}

    def save():
        temporary = record_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(record_path)

    def run(name, command, environment, cwd=None):
        cwd = cwd or source
        phase = {'name': name, 'argv': command, 'cwd': str(cwd), 'started': time.time(),
                 'log': str(output / (name + '.log'))}
        state['phases'].append(phase)
        state['current_phase'] = name
        save()
        with Path(phase['log']).open('wb') as log:
            child = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            phase.update(pid=child.pid, start_ticks=process_start(child.pid))
            save()
            try:
                phase['exit'] = child.wait()
            finally:
                stop(child)
        phase['finished'] = time.time()
        save()
        if phase['exit']:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])
        return Path(phase['log'])

    def artifact(log, manifest, name, kind, test):
        matches=[]
        for line in log.read_text().splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('reason')=='compiler-artifact' and value.get('manifest_path')==str(Path(manifest).resolve()) and value.get('target',{}).get('name')==name and kind in value.get('target',{}).get('kind',[]) and value.get('profile',{}).get('test') is test and value.get('executable'):
                matches.append(value)
        if len(matches)!=1:raise RuntimeError('Expected one exact producer artifact: '+name+'/'+kind)
        result=matches[0]
        if result.get('fresh') is not False or result['profile'].get('opt_level')!='3':raise RuntimeError('Root artifact was reused or wrong release profile: '+name)
        if not Path(result['executable']).is_file():raise RuntimeError('Compiler artifact is missing: '+name)
        return result

    def library_artifact(log,manifest):
        matches=[]
        for line in log.read_text().splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('reason')=='compiler-artifact' and value.get('manifest_path')==str(Path(manifest).resolve()) and value.get('target',{}).get('name')=='branchline' and value['target']['kind']==['lib']:matches.append(value)
        if len(matches)!=1:raise RuntimeError('Expected one root GUI library producer')
        result=matches[0]
        if result.get('fresh') is not False or result['profile'].get('opt_level')!='3' or result['profile'].get('test') is not False:raise RuntimeError('GUI root library reused or wrong profile')
        return result

    def pe_imports(path,label):
        if not path.read_bytes().startswith(b'MZ'):raise RuntimeError('Expected a PE image')
        log=run(label,['objdump','-p',str(path)],common)
        dlls=[line.split(':',1)[1].strip() for line in log.read_text().splitlines() if 'DLL Name:' in line]
        if any(any(t in name.lower() for t in ['vcruntime','msvcp','ucrtbase']) for name in dlls):raise RuntimeError('Dynamic CRT imports')
        return dlls

    def packaging(log,producer,library,binary,source):
        messages=[]
        for line in log.read_text().splitlines():
            try:messages.append(json.loads(line))
            except ValueError:pass
        def only(name,kind):
            matches=[v for v in messages if v.get('reason')=='compiler-artifact' and v.get('target',{}).get('name')==name and v['target']['kind']==[kind]]
            if len(matches)!=1:raise RuntimeError('Expected one packaged dependency producer: '+name)
            return matches[0]
        tauri=only('tauri','lib');macros=only('tauri_macros','proc-macro')
        if not tauri['package_id'].endswith('#tauri@2.11.6') or not macros['package_id'].endswith('#tauri-macros@2.6.3'):raise RuntimeError('Packaged dependency differs from pinned Cargo.lock')
        if 'custom-protocol' not in tauri['features'] or 'custom-protocol' not in macros['features']:raise RuntimeError('Packaged Tauri dependency feature missing')
        root_build,=[v for v in messages if v.get('reason')=='build-script-executed' and v.get('package_id')==producer['package_id']]
        tauri_build,=[v for v in messages if v.get('reason')=='build-script-executed' and v.get('package_id')==tauri['package_id']]
        if 'dev' in root_build['cfgs'] or 'dev' in tauri_build['cfgs'] or 'custom_protocol' not in tauri_build['cfgs']:raise RuntimeError('Development-mode GUI build')
        dist={str(p.relative_to(source)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted((source/'dist/web').rglob('*')) if p.is_file()}
        if 'dist/web/index.html' not in dist or not any(n.endswith('.js') for n in dist) or not any(n.endswith('.css') for n in dist):raise RuntimeError('Packaged frontend files missing')
        blobs=[];folder=Path(root_build['out_dir'])/'tauri-codegen-assets';data=binary.read_bytes()
        if folder.exists():
            for p in sorted(folder.rglob('*')):
                if p.is_file():
                    value=p.read_bytes()
                    if not value or value not in data:raise RuntimeError('Generated frontend asset not embedded: '+str(p))
                    blobs.append({'path':str(p),'sha256':sha(p),'bytes':len(value),'entire_blob_in_gui':True})
        return {'tauri_producer':tauri,'macros_producer':macros,'root_library_producer':library,'root_build_script':root_build,'tauri_build_script':tauri_build,'dist_files':dist,'generated_assets':blobs,'production_dependency_features_verified':True,'root_feature_list_required':False}

    def verify_source():
        for name, expected in plan['snapshot_files'].items():
            if sha(source / name) != expected:
                raise RuntimeError('Source changed: ' + name)
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], env=git_environment, text=True).strip()
        if head != plan['source']['git_head']:
            raise RuntimeError('Pinned source HEAD changed')
        tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], env=git_environment, text=True).strip()
        if tree != plan['bundle']['git_tree'] or (source / '.git/objects/info/alternates').exists():
            raise RuntimeError('Source tree provenance changed or uses external alternates')

    if sha(inputs/'controls/workload.py')!=plan['workload_sha256']:raise RuntimeError('Pinned workload control changed')
    sys.path.insert(0,str(inputs/'controls'))
    import workload
    git_environment = {key: workload.ENV[key] for key in [
        'GIT_OPTIONAL_LOCKS', 'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_TERMINAL_PROMPT']}
    state['kernel_git_environment'] = {'linux': git_environment,
                                      'windows': dict(git_environment, GIT_CONFIG_GLOBAL='NUL')}

    def native_git(root, *arguments):
        # The canonical helper chooses native Git for each volume and disables
        # optional index writes. Explicitly disable diff's independent refresh.
        data = workload.git(root, '-c', 'diff.autoRefreshIndex=false', *arguments)
        state.setdefault('kernel_read_commands', []).append({
            'platform': 'windows' if root == workload.WINDOWS_ROOT else 'linux',
            'executable': str(workload.WINDOWS_GIT) if root == workload.WINDOWS_ROOT else 'git',
            'cwd': workload.WINDOWS_NATIVE_ROOT if root == workload.WINDOWS_ROOT else str(root),
            'argv': ['--no-optional-locks', '-C', workload.WINDOWS_NATIVE_ROOT if root == workload.WINDOWS_ROOT else str(root),
                     '-c', 'diff.autoRefreshIndex=false', *arguments],
            'stdout_sha256': hashlib.sha256(data).hexdigest(), 'stdout_bytes': len(data)})
        return data

    def fingerprint():
        values = {}

        def file_state(root):
            files = {}
            for relative in ['.git/index', '.git/HEAD', '.git/config']:
                path = root / relative
                info = path.stat()
                files[relative] = {'sha256': sha(path), 'size': info.st_size,
                                   'mtime_ns': info.st_mtime_ns, 'inode': info.st_ino, 'mode': info.st_mode}
            return files

        for name, root in [('linux', workload.LINUX_ROOT), ('windows', workload.WINDOWS_ROOT)]:
            files = file_state(root)
            digest = hashlib.sha256()
            for arguments in [
                ['rev-parse', 'HEAD'], ['show-ref'], ['ls-files', '--stage', '-z'],
                ['status', '--porcelain=v1', '-z', '--untracked-files=all'],
                ['diff', '--cached', '--binary', '--no-ext-diff'],
                ['diff', '--binary', '--no-ext-diff'],
            ]:
                digest.update(native_git(root, *arguments))
            for path in sorted(native_git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')):
                if path:
                    digest.update(path)
                    digest.update((root / os.fsdecode(path)).read_bytes())
            if file_state(root) != files:
                raise RuntimeError('Kernel metadata changed during fingerprint: ' + name)
            values[name] = {'git_state_sha256': digest.hexdigest(), 'files': files}
            if values[name]['git_state_sha256'] != plan['fixture_sha256']:
                raise RuntimeError('Kernel fixture differs: ' + name)
        return values

    def kernel_proof(platform,executable):
        root=workload.LINUX_ROOT if platform=='linux' else workload.WINDOWS_ROOT
        logical_root=str(root) if platform=='linux' else workload.WINDOWS_NATIVE_ROOT
        manifest = json.loads(workload.MANIFEST.read_text())
        proof = {'platform':platform,'executable':str(executable),'sha256':sha(executable),'cwd':str(root),'started':time.time()}
        state.setdefault('kernel_proofs',[]).append(proof)
        phase = {'name':platform+'-kernel-proof','argv':[str(executable),'--stdio'],'cwd':str(root),'started':time.time()}
        state['phases'].append(phase);state['current_phase']=phase['name'];save()
        with (output/(platform+'-kernel-proof.stderr')).open('wb') as errors:
            child=subprocess.Popen([str(executable),'--stdio'],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,start_new_session=True)
            phase.update(pid=child.pid,start_ticks=process_start(child.pid));proof.update(pid=child.pid,start_ticks=phase['start_ticks']);save()
            serial=0
            def request(operation):
                nonlocal serial
                serial+=1;child.stdin.write((json.dumps(dict(operation,id=serial))+'\n').encode());child.stdin.flush()
                if not select.select([child.stdout],[],[],120)[0]:raise RuntimeError('Worker request timed out')
                response=json.loads(child.stdout.readline())
                if response.get('id')!=serial or 'error' in response:raise RuntimeError('Worker request failed: '+repr(response))
                return response['result']
            try:
                hello=request({'op':'hello'});proof['hello']=hello
                if hello.get('protocol')!=1 or hello.get('os')!=platform:raise RuntimeError('Worker protocol/platform mismatch')
                if platform=='linux':
                    if hello.get('pid')!=child.pid:raise RuntimeError('Linux worker PID mismatch')
                    proof['native_identity']={'pid':child.pid,'start_ticks':process_start(child.pid),'exe':os.readlink('/proc/'+str(child.pid)+'/exe')}
                    if Path(proof['native_identity']['exe'])!=executable:raise RuntimeError('Worker executable differs')
                else:
                    proof['native_identity']=native_windows_identity(hello['pid'])
                    expected_exe=str(executable).replace('/mnt/c/','C:/').replace('\\','/')
                    if not proof['native_identity'] or proof['native_identity']['exe'].replace('\\','/').casefold()!=expected_exe.casefold():raise RuntimeError('Windows worker identity differs')
                save()
                view=request({'op':'open','path':logical_root})['repo']
                refs=manifest['refs'];comparisons=[]
                fields=['status','old','path','old_mode','mode','old_oid','oid','added','removed']
                for left,right in [(refs[0],refs[1]),(refs[1],refs[2]),(refs[0],refs[2])]:
                    base_oid=view['refs'][left];head_oid=view['refs'][right]
                    raw=native_git(root,'diff','--no-ext-diff','--no-textconv','--find-renames','--ignore-submodules=none','--raw','--no-abbrev','--numstat','-z',base_oid,head_oid,'--')
                    parts=raw.split(b'\0');i=0;expected=[]
                    while i<len(parts) and parts[i].startswith(b':'):
                        old_mode,mode,old_oid,oid,status=parts[i][1:].decode().split();name=parts[i+1].decode()
                        if status!='M':raise RuntimeError('Expected modified kernel paths only')
                        expected.append(dict(status=status,old=name,path=name,old_mode=old_mode,mode=mode,old_oid=old_oid,oid=oid));i+=2
                    counts={}
                    for item in parts[i:]:
                        if item:
                            added,removed,name=item.split(b'\t',2);counts[name.decode()]=(int(added),int(removed))
                    for item in expected:item['added'],item['removed']=counts[item['path']]
                    result=request({'op':'compare','view':view,'left':left,'right':right})
                    actual=[{key:item[key] for key in fields} for item in result['files']]
                    if len(actual)!=30 or actual!=expected:raise RuntimeError('Kernel branch metadata/OID/count parity failed')
                    if result['base']!=base_oid or result['head']!=head_oid:raise RuntimeError('Kernel branch header mismatch')
                    comparisons.append({'left':left,'right':right,'expected':expected,'metadata':actual,'raw_sha256':__import__('hashlib').sha256(raw).hexdigest()})
                if request({'op':'hello'})!=hello:raise RuntimeError('Persistent worker identity changed')
                proof.update(expected=expected,result={'metadata':actual,'comparisons':comparisons})
                child.stdin.close();phase['exit']=proof['exit']=child.wait(timeout=30)
                if proof['exit']!=0:raise RuntimeError('Worker did not exit normally')
            finally:
                stop(child)
                identity=proof.get('native_identity')
                if platform=='windows' and identity:
                    after=native_windows_identity(identity['pid']);proof['native_after']=after
                    if after is not None:
                        if after!=identity:raise RuntimeError('Windows PID changed; refusing cleanup')
                        stop_windows_owned(identity)
                        proof['forced_native_cleanup']=True
                        save()
                        raise RuntimeError('Windows worker survived EOF; owned cleanup required')
            if process_start(child.pid)==proof['start_ticks']:raise RuntimeError('Exact kernel-proof actor remains live')
            proof['exact_actor_absent']=True
        if (output/(platform+'-kernel-proof.stderr')).stat().st_size:raise RuntimeError('Unexpected kernel-proof stderr')
        phase['finished']=proof['finished']=time.time();save()

    def interrupt(signum, frame):
        raise KeyboardInterrupt('Supervisor interrupted by signal ' + str(signum))

    for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        signal.signal(signum, interrupt)
    common = dict(os.environ, CARGO_BUILD_JOBS='1', CMAKE_BUILD_PARALLEL_LEVEL='1', CARGO_NET_OFFLINE='true',
                  XWIN_MSVC_SYSROOT=str(WORKSPACE / 'build/prebuilt-msvc/windows-msvc-sysroot'),
                  XWIN_CROSS_COMPILER='clang', XWIN_CACHE_DIR=str(WORKSPACE / 'build/xwin'))
    for key in ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'BRANCHLINE_GIT_WORKER_PATH']:
        common.pop(key, None)
    worker_target = WORKSPACE / 'src-tauri/target/git-worker'
    worker_environment = dict(common, CARGO_TARGET_DIR=str(worker_target), RUSTFLAGS='-C target-feature=+crt-static')
    linux_worker_environment = dict(worker_environment, LIBZ_SYS_STATIC='1')
    manifest = str(source / 'src-tauri/git-worker/Cargo.toml')
    linux_target='x86_64-unknown-linux-gnu'
    state['build_environments'] = {name: {key: env[key] for key in [
        'CARGO_BUILD_JOBS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'CARGO_NET_OFFLINE', 'CARGO_TARGET_DIR',
        'RUSTFLAGS', 'XWIN_MSVC_SYSROOT', 'XWIN_CROSS_COMPILER', 'XWIN_CACHE_DIR']}
        for name, env in [('linux_worker',linux_worker_environment),('windows_worker',worker_environment)]}
    state['build_environments']['linux_worker']['LIBZ_SYS_STATIC'] = '1'
    failure = None
    try:
        save()
        print(json.dumps({'supervisor_pid': os.getpid(), 'record': str(record_path)}), flush=True)
        # Build Git metadata from the real self-contained bundle. No checkout
        # updates the extracted candidate working files.
        bundle = inputs / plan['bundle']['name']
        if sha(bundle) != plan['bundle']['sha256'] or (source / '.git').exists():
            raise RuntimeError('Bundle changed or source Git directory already exists')
        for name, expected in plan['snapshot_files'].items():
            if sha(source / name) != expected:
                raise RuntimeError('Source changed before Git bootstrap: ' + name)
        git_environment = dict(common, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                               GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
        for key in ['GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE',
                    'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG_COUNT']:
            git_environment.pop(key, None)
        state['source_git_environment'] = {key: git_environment[key] for key in [
            'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_TERMINAL_PROMPT', 'GIT_NO_LAZY_FETCH']}
        run('source-git-init', ['git', 'init', '--quiet', str(source)], git_environment)
        run('source-bundle-verify', ['git', 'bundle', 'verify', str(bundle)], git_environment)
        run('source-bundle-fetch', ['git', 'fetch', '--no-tags', str(bundle), 'HEAD'], git_environment)
        fetched = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'FETCH_HEAD'],
                                          env=git_environment, text=True).strip()
        if fetched != plan['source']['git_head']:
            raise RuntimeError('Bundle fetched another commit')
        run('source-git-head', ['git', 'update-ref', '--no-deref', 'HEAD', fetched], git_environment)
        run('source-git-index', ['git', 'read-tree', 'HEAD'], git_environment)
        verify_source()
        state['source_git_provenance'] = {'head': fetched, 'tree': plan['bundle']['git_tree'],
            'bundle_sha256': sha(bundle), 'external_alternates': False,
            'working_files_preserved': True, 'method': 'init/fetch/update-ref/read-tree; no checkout'}
        state['fixture_before'] = fingerprint()
        save()
        state['versions']={name:subprocess.check_output(command,env=common,text=True).strip() for name,command in {'rustc':['rustc','-Vv'],'cargo':['cargo','-V'],'cargo_xwin':['cargo','xwin','--version'],'clang':['clang','--version'],'gcc':['gcc','--version'],'node':['node','--version'],'npm':['npm','--version']}.items()}
        state['producer_artifacts']={};state['workers']={}
        for platform,target,environment,runner in [('linux',linux_target,linux_worker_environment,['cargo']),('windows','x86_64-pc-windows-msvc',worker_environment,['cargo','xwin'])]:
            run(platform+'-worker-root-clean',['cargo','clean','--offline','--locked','--release','--package','branchline-git-worker','--manifest-path',manifest,'--target',target],environment)
            log=run(platform+'-worker-build',runner+['build','--offline','--locked','--release','--manifest-path',manifest,'--target',target,'--message-format=json'],environment)
            producer=artifact(log,manifest,'branchline-git-worker','bin',False)
            original=Path(producer['executable']);destination=output/'branchline-git-worker' if platform=='linux' else native_output/'branchline-git-worker.exe'
            shutil.copy2(original,destination)
            if sha(original)!=sha(destination):raise RuntimeError('Fresh worker copy differs: '+platform)
            state['producer_artifacts'][platform+'_worker']=producer
            state['workers'][platform]={'path':str(destination),'sha256':sha(destination),'bytes':destination.stat().st_size,'protocol':1,'producer_executable':producer['executable'],'producer_fresh':False}
            if platform=='linux':
                run('linux-worker-format',['file',str(destination)],common)
                headers=run('linux-worker-program-headers',['readelf','-l',str(destination)],common)
                dynamic=run('linux-worker-dynamic',['readelf','-d',str(destination)],common)
                if 'INTERP' in headers.read_text() or '(NEEDED)' in dynamic.read_text():raise RuntimeError('GNU worker is not static')
                test_log=run('linux-worker-tests',['cargo','test','--offline','--locked','--release','--manifest-path',manifest,'--target',target,'--message-format=json','--','--test-threads=1'],environment)
                state['producer_artifacts']['linux_worker_tests']=artifact(test_log,manifest,'branchline-git-worker','bin',True)
                state['producer_artifacts']['linux_worker_stdio']=artifact(test_log,manifest,'stdio','test',True)
                names=sorted(line[5:].split(' ... ',1)[0] for line in test_log.read_text().splitlines() if line.startswith('test ') and line.endswith(' ... ok'))
                if names!=sorted(plan['expected_unit_tests']+plan['expected_stdio_tests']):raise RuntimeError('GNU test names differ from pinned25+1')
                state['native_test_names']={'linux':names}
            else:
                state['workers']['windows']['imports']=pe_imports(destination,'windows-worker-imports')
                state['workers']['windows']['static_crt_import_check']=True
                test_log=run('windows-worker-tests-build',['cargo','xwin','test','--offline','--locked','--release','--manifest-path',manifest,'--target',target,'--bin','branchline-git-worker','--no-run','--message-format=json'],environment)
                unit_producer=artifact(test_log,manifest,'branchline-git-worker','bin',True)
                state['producer_artifacts']['windows_worker_tests']=unit_producer
                unit=native_output/'worker-unit-tests.exe';shutil.copy2(unit_producer['executable'],unit)
                if sha(unit)!=sha(unit_producer['executable']):raise RuntimeError('Windows unit artifact copy differs')
                state['windows_unit_tests']={'path':str(unit),'sha256':sha(unit),'producer_executable':unit_producer['executable']}
                native_log=run('windows-worker-tests',[str(unit),'--test-threads=1'],common,cwd=native_output)
                names=sorted(line[5:].split(' ... ',1)[0] for line in native_log.read_text().splitlines() if line.startswith('test ') and line.endswith(' ... ok'))
                if names!=sorted(plan['expected_windows_unit_tests']):raise RuntimeError('Windows test names differ from pinned23')
                state['native_test_names']['windows']=names
            if sha(original)!=sha(destination):raise RuntimeError('Worker producer changed during tests')
            kernel_proof(platform,destination);save()
        gui_manifest=str(source/'src-tauri/Cargo.toml')
        state['build_environments']['gui']={}
        # Windows first, then Linux host-target. No renderer/runtime overrides.
        for platform,opposite in [('windows','linux'),('linux','windows')]:
            helper=Path(state['workers'][opposite]['path'])
            environment=dict(common,CARGO_TARGET_DIR=str(WORKSPACE/'src-tauri/target'),BRANCHLINE_GIT_WORKER_PATH=str(helper))
            target_args=['--target','x86_64-pc-windows-msvc'] if platform=='windows' else []
            state['build_environments']['gui'][platform]={'CARGO_TARGET_DIR':environment['CARGO_TARGET_DIR'],'BRANCHLINE_GIT_WORKER_PATH':str(helper),'renderer':'production default','RUSTFLAGS':'build.sh adds +crt-static for Windows; unset for Linux'}
            run(platform+'-gui-root-clean',['cargo','clean','--offline','--locked','--release','--package','branchline','--manifest-path',gui_manifest,*target_args],environment)
            args=['./build.sh','--windows'] if platform=='windows' else ['./build.sh','--no-bundle']
            log=run(platform+'-gui-build',args+['--','--message-format=json'],environment)
            gui_producer=artifact(log,gui_manifest,'branchline','bin',False)
            library=library_artifact(log,gui_manifest)
            original=Path(gui_producer['executable'])
            destination=Path('/mnt/c/'+plan['windows_binary'][3:]) if platform=='windows' else Path(plan['linux_binary'])
            if destination.exists():raise RuntimeError('Immutable GUI output exists: '+str(destination))
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,destination)
            if sha(original)!=sha(destination) or helper.read_bytes() not in destination.read_bytes():raise RuntimeError('GUI copy or opposite worker embedding differs')
            packaged=packaging(log,gui_producer,library,destination,source)
            state['producer_artifacts'][platform+'_gui']=gui_producer
            state['producer_artifacts'][platform+'_gui_library']=library
            state[platform+'_gui']={'path':str(destination),'sha256':sha(destination),'bytes':destination.stat().st_size,'embedded_helper_sha256':sha(helper),'embedded_helper_verified':True,'renderer':'production default','producer_executable':gui_producer['executable'],'producer_fresh':False,'packaged_assets':packaged}
            if platform=='windows':
                state['windows_gui']['imports']=pe_imports(destination,'windows-gui-imports')
                state['windows_gui']['static_crt_import_check']=True
            else:
                if not destination.read_bytes().startswith(b'\x7fELF'):raise RuntimeError('Linux GUI is not ELF')
                run('linux-gui-format',['file',str(destination)],common)
            save()
        for platform in ('linux','windows'):
            if sha(state['workers'][platform]['path'])!=state['workers'][platform]['sha256'] or sha(state[platform+'_gui']['path'])!=state[platform+'_gui']['sha256']:raise RuntimeError('Immutable artifact changed')
        verify_source()
    except BaseException as error:
        failure = error
        state.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if 'fixture_before' in state:
            try:
                state['fixture_after'] = fingerprint()
                if state['fixture_before'] != state['fixture_after']:
                    raise RuntimeError('Kernel index/config/HEAD metadata or Git state changed')
            except BaseException as error:
                state['fixture_after_error'] = str(error)
                failure = failure or error
        state.update(status='failed' if failure else 'built; canonical GUI evaluation pending', finished=time.time())
        save()
    if failure:
        raise failure
    print(json.dumps({'record':str(record_path),'windows_gui':state['windows_gui'],'linux_gui':state['linux_gui'],'workers':state['workers']},indent=2),flush=True)


if __name__ == '__main__':
    main()
