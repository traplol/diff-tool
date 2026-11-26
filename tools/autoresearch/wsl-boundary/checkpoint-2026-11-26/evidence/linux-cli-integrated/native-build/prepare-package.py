#!/usr/bin/env python3
"""Package the frozen integrated source and verify a real Git extraction before SSH."""
from pathlib import Path
import hashlib
import json
import subprocess
import shutil
import sys
import tarfile
base=Path(__file__).resolve().parent;candidate=base.parent;root=base.parents[3];source=candidate/'source'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
identity=json.loads((candidate/'source.json').read_text());proof=json.loads((candidate/'proof.json').read_text());assert proof['source_hash']==identity['source_hash']
assert identity['git_head']=='ce75cd6be9f0a0f1d0587aef0ce603d21c0fc3df' and identity['source_hash']=='c2006e96fdcb418c83b35c02741f3acafe5d79fc4bdfa0608f5256fd3ef176c1'
for name,digest in identity['files'].items():assert sha(source/name)==digest,name
assert not (base/'input-tar.json').exists(),'Prepared package already exists; inspect its identity before any replacement'
for name in ['vm-build-supervisor.py','build-after-release.py','verify-package.py']:assert (base/name).is_file(),name
bundle=base/'source-ce75cd6.bundle';assert not bundle.exists();subprocess.run(['git','-C',str(source),'bundle','create',str(bundle),'HEAD'],check=True,capture_output=True)
head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip();tree=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD^{tree}'],text=True).strip();assert head==identity['git_head']
# Build inputs only. Commit history is retained in the real bundle, without unpacking historical benchmark archives.
paths=set(identity['files']);paths.update(str(p.relative_to(source)) for p in (source/'src-tauri/icons').rglob('*') if p.is_file());snapshot={name:sha(source/name) for name in sorted(paths)}
label='integrated-c200-r1';logs=(candidate/'worker-tests.log').read_text();names=[line[5:].split(' ... ',1)[0] for line in logs.splitlines() if line.startswith('test ') and line.endswith(' ... ok')];assert len(names)==26
workload=root/'tools/autoresearch/wsl-boundary/workload.py'
(base/'controls').mkdir(exist_ok=True);shutil.copy2(workload,base/'controls/workload.py')
plan={'status':'prepared-host-only-no-VM-build-test-scoring','label':label,'source':identity,'app_files':identity['files'],'snapshot_files':snapshot,'bundle':{'name':bundle.name,'sha256':sha(bundle),'bytes':bundle.stat().st_size,'git_head':head,'git_tree':tree,'self_contained':True},'host_proof_files':{name:sha(candidate/name) for name in ['proof.json','host-gates.json','worker-tests.log','gui-tests.log']},'patch_sha256':sha(candidate/'candidate.patch'),'source_input_directory':'/home/max/benchmarks/branchline-boundary/'+label+'-input','artifact_directory':'/home/max/benchmarks/branchline-boundary/'+label+'-native','windows_binary':'C:/Users/max/branchline-bench/binaries/'+label+'/branchline.exe','linux_binary':'/home/max/benchmarks/branchline-boundary/binaries/'+label+'/branchline','protocol':1,'fixture_sha256':'db66016f41a604c102cc81121c4e81f9c93db3b3f4430ef51dab5ba1c9da97c2','release_required':'VM INTEGRATED CLI BUILD RELEASED','worker_target_cache':'/home/max/workspace/diff-tool/src-tauri/target/git-worker','gui_target_cache':'/home/max/workspace/diff-tool/src-tauri/target','workload_sha256':sha(workload),'expected_unit_tests':names[:-1],'expected_stdio_tests':names[-1:],'expected_windows_unit_tests':proof['expected_windows_unit_tests'],'scope':'All4 native artifacts tied to exact integrated49 source; currentmain tests preserved. Fresh root GNU/PE/WinGUI/LinuxGUI compiler JSON/executable bindings, dependency packagedfeatures, static helpers/WinCRT,25+1Linux/23Windows tests and native kernel metadata parity. No source or rendering knobs.','source_snapshot_scope':'Canonical49 app files plus packaging icons. RealGitbundle retains exactce75history; historicalbenchmark working files are not expanded into buildinput.'}
(base/'build-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
archive=base/(label+'-input.tar')
with tarfile.open(archive,'w') as tar:
 for name,digest in snapshot.items():assert sha(source/name)==digest;tar.add(source/name,arcname='source/'+name)
 for name in ['build-plan.json','vm-build-supervisor.py',bundle.name]:tar.add(base/name,arcname=name)
 tar.add(workload,arcname='controls/workload.py')
record={'name':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'source_hash':identity['source_hash'],'bundle_sha256':sha(bundle),'build_plan_sha256':sha(base/'build-plan.json'),'vm_supervisor_sha256':sha(base/'vm-build-supervisor.py'),'host_launcher_sha256':sha(base/'build-after-release.py'),'host_verifier_sha256':sha(base/'verify-package.py'),'status':'prepared; mandatory realGit hostextract/49hash verification before SSH'}
(base/'input-tar.json').write_text(json.dumps(record,indent=2)+'\n');subprocess.run([sys.executable,str(base/'verify-package.py')],check=True);print(json.dumps(record))
