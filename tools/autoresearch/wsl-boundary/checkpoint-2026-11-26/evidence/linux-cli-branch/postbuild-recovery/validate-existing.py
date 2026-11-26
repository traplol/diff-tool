#!/usr/bin/env python3
"""Complete existing R2 artifacts after correcting the root-feature assumption; no build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

PLAN=Path('/home/max/benchmarks/branchline-boundary/linux-cli-branch-a4a08d-r2-input/build-plan.json')
FAILED=Path('/home/max/benchmarks/branchline-boundary/linux-cli-branch-a4a08d-r2-native/supervisor.json')
FAILED_SHA='bac4e31155c5b23de0c51ef35cd206a076051023214203267459426d35c6b29c'
GUI_SHA='6d19d864c30a9753b6570f83e890356cd3445e591047f5e877992c7289a90c77'
WORKER_SHA='92d98807a79d628c0c6b28da28845d669e869b08bf68885ce29ed7748f7a0ffd'
OUTPUT=Path('/home/max/benchmarks/branchline-boundary/linux-cli-branch-a4a08d-r2-postbuild-recovery')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',required=True);args=parser.parse_args()
    if args.release!='VM LINUX CLI POSTBUILD RECOVERY RELEASED':parser.error('Wait for root release')
    assert sha(PLAN)=='3d61fc781ec075b4e04ee785373ee07f02b4c1132c73fc0c157d40bb9db9ae52';assert sha(FAILED)==FAILED_SHA
    plan=json.loads(PLAN.read_text());old=json.loads(FAILED.read_text());source=PLAN.parent/'source'
    assert old['status']=='failed' and old['error']=='GUI producer lacks packaged custom-protocol assets'
    assert old['source']==plan['source'] and old['fixture_before']==old['fixture_after']
    assert all(p['exit']==0 for p in old['phases'])
    def gone(pid,start):
        p=Path('/proc')/str(pid)/'stat';return not p.exists() or p.read_text().rsplit(') ',1)[1].split()[19]!=start
    assert gone(old['pid'],old['start_ticks']);assert all(gone(p['pid'],p['start_ticks']) for p in old['phases'])
    def verify_source():
        for name,digest in plan['snapshot_files'].items():assert sha(source/name)==digest,name
        env=dict(os.environ)
        for key in ['GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES']:env.pop(key,None)
        head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],env=env,text=True).strip();tree=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD^{tree}'],env=env,text=True).strip()
        assert head==plan['source']['git_head'] and tree==plan['bundle']['git_tree'];assert not (source/'.git/objects/info/alternates').exists()
        current={'git_head':head,'files':{name:sha(source/name) for name in plan['source']['files']}}
        assert hashlib.sha256(json.dumps(current,sort_keys=True,separators=(',',':')).encode()).hexdigest()==plan['source']['source_hash']
    def guards():
        actual={}
        for platform,root in [('linux',Path('/home/max/benchmarks/branchline-boundary/kernel-wsl')),('windows',Path('/mnt/c/Users/max/branchline-bench/kernel-windows'))]:
            values={}
            for relative in ['.git/index','.git/HEAD','.git/config']:
                p=root/relative;s=p.stat();values[relative]={'sha256':sha(p),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'inode':s.st_ino,'mode':s.st_mode}
            assert values==old['fixture_after'][platform]['files'];actual[platform]=values
        return actual
    verify_source();before=guards()
    provenance=old['source_git_provenance'];assert provenance['head']==plan['source']['git_head'] and provenance['tree']==plan['bundle']['git_tree'] and provenance['bundle_sha256']==plan['bundle']['sha256'] and not provenance['external_alternates']
    for key,name,kind,test in [('linux_worker','branchline-git-worker','bin',False),('linux_worker_tests','branchline-git-worker','bin',True),('linux_worker_stdio','stdio','test',True)]:
        p=old['producer_artifacts'][key];assert p['fresh'] is False and p['profile']['opt_level']=='3' and p['profile']['test'] is test and p['target']['name']==name and p['target']['kind']==[kind] and p['manifest_path']==str(source/'src-tauri/git-worker/Cargo.toml') and p['executable'] in p['filenames']
    assert old['native_test_names']==sorted(plan['expected_unit_tests']+plan['expected_stdio_tests'])
    kernel,=old['kernel_proofs'];assert kernel['exit']==0 and kernel['exact_actor_absent'] and kernel['hello']['protocol']==1 and kernel['hello']['os']=='linux'
    assert len(kernel['expected'])==30 and kernel['result']['metadata']==kernel['expected'] and len(kernel['result']['comparisons'])==3
    assert all(len(c['metadata'])==30 and c['metadata']==c['expected'] for c in kernel['result']['comparisons'])
    worker=Path(old['workers']['linux']['path']);assert sha(worker)==WORKER_SHA==old['workers']['linux']['sha256']==kernel['sha256']
    log=FAILED.parent/'windows-gui-build.log';messages=[]
    for line in log.read_text().splitlines():
        try:messages.append(json.loads(line))
        except ValueError:pass
    def producer(name,kind,manifest=None):
        matches=[p for p in messages if p.get('reason')=='compiler-artifact' and p.get('target',{}).get('name')==name and p['target']['kind']==[kind] and (manifest is None or p.get('manifest_path')==str(manifest))]
        assert len(matches)==1,(name,len(matches));return matches[0]
    gui=producer('branchline','bin',source/'src-tauri/Cargo.toml');library=producer('branchline','lib',source/'src-tauri/Cargo.toml')
    for p in [gui,library]:assert p['fresh'] is False and p['profile']['opt_level']=='3' and p['profile']['test'] is False
    tauri=producer('tauri','lib');macros=producer('tauri_macros','proc-macro')
    assert tauri['package_id'].endswith('#tauri@2.11.6') and macros['package_id'].endswith('#tauri-macros@2.6.3')
    assert 'custom-protocol' in tauri['features'] and 'custom-protocol' in macros['features']
    build,=[p for p in messages if p.get('reason')=='build-script-executed' and p.get('package_id')==gui['package_id']]
    tauri_build,=[p for p in messages if p.get('reason')=='build-script-executed' and p.get('package_id')==tauri['package_id']]
    assert 'dev' not in build['cfgs'] and 'custom_protocol' in tauri_build['cfgs'] and 'dev' not in tauri_build['cfgs']
    original=Path(gui['executable']);assert str(original) in gui['filenames'] and sha(original)==GUI_SHA
    data=original.read_bytes();assert data.startswith(b'MZ') and worker.read_bytes() in data
    imports_text=subprocess.check_output(['objdump','-p',str(original)],text=True);imports=[line.split(':',1)[1].strip() for line in imports_text.splitlines() if 'DLL Name:' in line]
    assert not any(any(t in n.lower() for t in ['vcruntime','msvcp','ucrtbase']) for n in imports)
    dist={str(p.relative_to(source)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted((source/'dist/web').rglob('*')) if p.is_file()}
    assert len(dist)==3 and 'dist/web/index.html' in dist and any(n.endswith('.js') for n in dist) and any(n.endswith('.css') for n in dist)
    assets=[];assetdir=Path(build['out_dir'])/'tauri-codegen-assets'
    if assetdir.exists():
        for p in sorted(assetdir.rglob('*')):
            if p.is_file():
                value=p.read_bytes();assert value and value in data,p
                assets.append({'path':str(p),'sha256':sha(p),'bytes':len(value),'entire_blob_in_gui':True})
        assert any(p['path'].endswith('.js') for p in assets) and any(p['path'].endswith('.css') for p in assets) and any(p['path'].endswith('.html') for p in assets)
    packaged={'tauri_producer':tauri,'macros_producer':macros,'root_library_producer':library,'root_build_script':build,'tauri_build_script':tauri_build,'dist_files':dist,'generated_assets':assets,'production_dependency_features_verified':True,'root_feature_list_required':False,'runtime_validation':'Canonical WELCOME_READY plus real app/render/content/comment gates still mandatory before any performance result.'}
    destination=Path('/mnt/c/'+plan['windows_binary'][3:]);assert not destination.exists();assert not OUTPUT.exists()
    OUTPUT.mkdir();shutil.copy2(original,destination);assert sha(destination)==GUI_SHA
    report={'status':'recovered-without-rebuild','valid':True,'created':time.time(),'original_failed_record':str(FAILED),'original_failed_sha256':FAILED_SHA,'original_error':old['error'],'original_record_unchanged':True,'source':plan['source'],'source_git_provenance':provenance,'source_snapshot_files_verified':len(plan['snapshot_files']),'source_application_files_verified':len(plan['source']['files']),'all_exact_actors_absent':True,'fixture_guards_before':before,'fixture_guards_after':guards(),'windows_gui_producer':gui,'windows_gui_library_producer':library,'packaged_assets':packaged,'windows_gui':{'path':str(destination),'sha256':GUI_SHA,'bytes':len(data),'embedded_helper_sha256':WORKER_SHA,'embedded_helper_verified':True,'renderer':'production default','imports':imports,'static_crt_import_check':True,'producer_executable':str(original),'producer_fresh':False},'builds_tests_or_benchmarks_run':False,'only_writes':[str(destination),str(OUTPUT/'recovery.json')]}
    verify_source();assert sha(FAILED)==FAILED_SHA;assert report['fixture_guards_before']==report['fixture_guards_after']
    (OUTPUT/'recovery.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'report':str(OUTPUT/'recovery.json'),'report_sha256':sha(OUTPUT/'recovery.json'),'windows_gui':report['windows_gui']}))

if __name__=='__main__':main()
