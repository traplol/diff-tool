"""Shared read-only integrated build gates for the Windows and Linux adapters."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BASE=ROOT/'build/autoresearch/wsl-boundary'
sys.path.insert(0,str(ROOT/'tools/autoresearch/wsl-boundary'))
import score
SOURCE='c2006e96fdcb418c83b35c02741f3acafe5d79fc4bdfa0608f5256fd3ef176c1'
CONTRACT='3db306b466166cb39b8c5a9dc27a9739b16df52fa9f83d32bd6656f226026b04'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def validate():
    assert score.contract_identity()['sha256']==CONTRACT
    source=json.loads((HERE/'source.json').read_text());assert source['source_hash']==SOURCE and source['git_head']=='ce75cd6be9f0a0f1d0587aef0ce603d21c0fc3df'
    assert score.source_identity(HERE/'source')==source
    proof=json.loads((HERE/'proof.json').read_text());assert proof['source_hash']==SOURCE and proof['source_unchanged']
    for key,passed in [('host_worker',25),('host_gui_rust',70)]:
        p=proof[key];assert p.get('unit_passed',p.get('passed'))==passed and p['failed']==0 and sha(HERE/p['log'])==p['log_sha256']
        assert all(v['fresh'] is False for v in p['producer_artifacts'].values())
    assert proof['host_worker']['real_stdio_passed']==1 and proof['host_gui_rust']['ignored']==1
    path=HERE/'native-build/build-plan.json';plan=json.loads(path.read_text());assert plan['source']==source and plan['protocol']==1
    archive=json.loads((HERE/'native-build/input-tar.json').read_text());assert sha(path)==archive['build_plan_sha256']
    for name,value in plan['host_proof_files'].items():assert sha(HERE/name)==value,name
    record=HERE/'native-build/native-evidence/supervisor.json'
    result={'ready':False,'source':source,'plan':plan,'build_plan_sha256':sha(path),'record':str(record)}
    if not record.exists():return result
    native=json.loads(record.read_text());assert native['status']=='built; canonical GUI evaluation pending'
    assert native['source']==source and native['fixture_before']==native['fixture_after']
    assert {p['git_state_sha256'] for p in native['fixture_after'].values()}=={plan['fixture_sha256']}
    provenance=native['source_git_provenance'];assert provenance['head']==source['git_head'] and provenance['tree']==plan['bundle']['git_tree'] and provenance['bundle_sha256']==plan['bundle']['sha256']
    assert not provenance['external_alternates'] and provenance['working_files_preserved']
    phases={p['name']:p for p in native['phases']};assert all(p['exit']==0 for p in phases.values())
    for platform in ('linux','windows'):
        for suffix in ['worker-root-clean','worker-build','kernel-proof','gui-root-clean','gui-build']:assert phases[platform+'-'+suffix]['exit']==0
    for name in ['linux-worker-tests','windows-worker-tests-build','windows-worker-tests']:assert phases[name]['exit']==0
    assert 'INTERP' not in (record.parent/'linux-worker-program-headers.log').read_text()
    assert '(NEEDED)' not in (record.parent/'linux-worker-dynamic.log').read_text()
    assert native['build_environments']['linux_worker']['RUSTFLAGS']=='-C target-feature=+crt-static' and native['build_environments']['linux_worker']['LIBZ_SYS_STATIC']=='1'
    assert native['native_test_names']['linux']==sorted(plan['expected_unit_tests']+plan['expected_stdio_tests'])
    assert len(plan['expected_unit_tests'])==25 and len(plan['expected_stdio_tests'])==1
    assert native['native_test_names']['windows']==sorted(plan['expected_windows_unit_tests']) and len(plan['expected_windows_unit_tests'])==23
    producers=native['producer_artifacts'];vm_source=Path(plan['source_input_directory'])/'source';worker_manifest=vm_source/'src-tauri/git-worker/Cargo.toml';gui_manifest=vm_source/'src-tauri/Cargo.toml'
    for key,manifest,name,kind,test in [
        ('linux_worker',worker_manifest,'branchline-git-worker','bin',False),('windows_worker',worker_manifest,'branchline-git-worker','bin',False),
        ('linux_worker_tests',worker_manifest,'branchline-git-worker','bin',True),('linux_worker_stdio',worker_manifest,'stdio','test',True),('windows_worker_tests',worker_manifest,'branchline-git-worker','bin',True),
        ('linux_gui',gui_manifest,'branchline','bin',False),('windows_gui',gui_manifest,'branchline','bin',False),('linux_gui_library',gui_manifest,'branchline','lib',False),('windows_gui_library',gui_manifest,'branchline','lib',False)]:
        value=producers[key];assert value['reason']=='compiler-artifact' and value['manifest_path']==str(manifest)
        assert value['target']['name']==name and value['target']['kind']==[kind] and value['profile']['test'] is test and value['profile']['opt_level']=='3' and value['fresh'] is False
        if kind!='lib':assert value['executable'] in value['filenames']
        expected_src=(manifest.parent/('tests/stdio.rs' if name=='stdio' else 'src/lib.rs' if kind=='lib' else 'src/main.rs'))
        assert value['target']['src_path']==str(expected_src)
        root=Path(plan['worker_target_cache'] if 'worker' in key else plan['gui_target_cache'])
        assert all(Path(p).is_relative_to(root) for p in value['filenames'])
    refs=json.loads((BASE/'workload.json').read_text())['refs']
    for platform,gui_file,worker_file in [('linux','branchline','branchline-git-worker'),('windows','branchline.exe','branchline-git-worker.exe')]:
        worker=native['workers'][platform];gui=native[platform+'_gui'];opposite='windows' if platform=='linux' else 'linux'
        assert worker['protocol']==1 and worker['producer_fresh'] is False and worker['producer_executable']==producers[platform+'_worker']['executable']
        assert sha(record.parent/worker_file)==worker['sha256'] and sha(record.parent/gui_file)==gui['sha256']
        assert gui['producer_fresh'] is False and gui['producer_executable']==producers[platform+'_gui']['executable']
        assert gui['embedded_helper_verified'] and gui['embedded_helper_sha256']==native['workers'][opposite]['sha256'] and gui['renderer']=='production default'
        packed=gui['packaged_assets'];assert packed['production_dependency_features_verified'] and packed['root_feature_list_required'] is False
        for key,name,kind,version in [('tauri_producer','tauri','lib','2.11.6'),('macros_producer','tauri_macros','proc-macro','2.6.3')]:
            d=packed[key];package='tauri-macros' if name=='tauri_macros' else name
            assert d['target']['name']==name and d['target']['kind']==[kind] and d['package_id'].endswith('#'+package+'@'+version) and 'custom-protocol' in d['features']
        assert packed['root_library_producer']==producers[platform+'_gui_library'] and 'dev' not in packed['root_build_script']['cfgs']
        assert 'custom_protocol' in packed['tauri_build_script']['cfgs'] and 'dev' not in packed['tauri_build_script']['cfgs']
        assert 'dist/web/index.html' in packed['dist_files'] and any(p.endswith('.js') for p in packed['dist_files']) and any(p.endswith('.css') for p in packed['dist_files'])
        assert all(p['entire_blob_in_gui'] for p in packed['generated_assets'])
        kernel,=[p for p in native['kernel_proofs'] if p['platform']==platform]
        assert kernel['sha256']==worker['sha256'] and kernel['exit']==0 and kernel['exact_actor_absent'] and kernel['hello']['protocol']==1 and kernel['hello']['os']==platform
        assert len(kernel['expected'])==30 and kernel['result']['metadata']==kernel['expected']
        pairs=kernel['result']['comparisons'];assert [(p['left'],p['right']) for p in pairs]==[(refs[0],refs[1]),(refs[1],refs[2]),(refs[0],refs[2])]
        assert all(len(p['metadata'])==30 and p['metadata']==p['expected'] for p in pairs)
        if platform=='windows':assert kernel['native_after'] is None and not kernel.get('forced_native_cleanup') and worker['static_crt_import_check'] and gui['static_crt_import_check']
    assert native['windows_gui']['path']=='/mnt/c/'+plan['windows_binary'][3:] and native['linux_gui']['path']==plan['linux_binary']
    result.update(ready=True,native=native,native_record_sha256=sha(record))
    return result
