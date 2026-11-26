#!/usr/bin/env python3
"""Verify a fresh local extraction and real Git discovery before any SSH."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

base=Path(__file__).resolve().parent;root=base.parents[3]
sys.path.insert(0,str(root/'tools/autoresearch/wsl-boundary'))
from score import source_identity
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads((base/'build-plan.json').read_text());archive=json.loads((base/'input-tar.json').read_text())
assert sha(base/archive['name'])==archive['sha256']
for name,field in [('build-plan.json','build_plan_sha256'),('vm-build-supervisor.py','vm_supervisor_sha256'),('build-after-release.py','host_launcher_sha256'),('verify-package.py','host_verifier_sha256')]:assert sha(base/name)==archive[field],name
records=[]
with tempfile.TemporaryDirectory(prefix='linux-cli-package-') as directory:
    extraction=Path(directory)
    with tarfile.open(base/archive['name']) as packed:packed.extractall(extraction,filter='data')
    for name in ['build-plan.json','vm-build-supervisor.py']:assert (extraction/name).read_bytes()==(base/name).read_bytes(),name
    source=extraction/'source';bundle=extraction/plan['bundle']['name'];assert sha(bundle)==plan['bundle']['sha256'];assert not (source/'.git').exists()
    for name,digest in plan['snapshot_files'].items():assert sha(source/name)==digest,name
    env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1')
    for key in ['GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_CONFIG_COUNT']:env.pop(key,None)
    for command in [['git','init','--quiet',str(source)],['git','bundle','verify',str(bundle)],['git','fetch','--no-tags',str(bundle),'HEAD'],['git','update-ref','--no-deref','HEAD',plan['source']['git_head']],['git','read-tree','HEAD']]:
        result=subprocess.run(command,cwd=source,env=env,capture_output=True,text=True);records.append({'argv':command,'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr});assert result.returncode==0,records[-1]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,env=env,text=True).strip();tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=source,env=env,text=True).strip()
    assert head==plan['source']['git_head'];assert tree==plan['bundle']['git_tree'];assert not (source/'.git/objects/info/alternates').exists()
    actual=source_identity(source);assert actual==plan['source'];assert os.access(source/'build.sh',os.X_OK)
    for name,digest in plan['snapshot_files'].items():assert sha(source/name)==digest,name
proof={'status':'host-extract-git-discovery-and-source-passed','archive_sha256':archive['sha256'],'bundle_sha256':plan['bundle']['sha256'],'git_head':head,'git_tree':tree,'canonical_app_files':len(actual['files']),'source_hash':actual['source_hash'],'all_snapshot_files_unchanged':True,'snapshot_file_count':len(plan['snapshot_files']),'external_alternates':False,'build_sh_executable':True,'commands':records,'vm_calls':False,'builds_tests_or_scoring':False}
(base/'package-verification.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps({k:proof[k] for k in ['status','archive_sha256','source_hash','canonical_app_files']}))
