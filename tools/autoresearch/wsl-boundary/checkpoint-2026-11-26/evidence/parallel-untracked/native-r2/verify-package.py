#!/usr/bin/env python3
"""Verify the R2 archive, real Git HEAD and canonical app identity without building."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

base=Path(__file__).resolve().parent
sys.path.insert(0,str(base.parents[3]/'tools/autoresearch/wsl-boundary'))
from score import source_identity

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

plan=json.loads((base/'native-plan.json').read_text())
archive=json.loads((base/'native-input.json').read_text())
assert sha(base/archive['name'])==archive['sha256']
for name,digest in archive['controls'].items():assert sha(base/name)==digest,name
for name in ['native-experiment.py','run-native.py','verify-package.py']:
    ast.parse((base/name).read_text(),filename=name)
records=[]
with tempfile.TemporaryDirectory(prefix='parallel-untracked-r2-package-') as directory:
    extraction=Path(directory)
    with tarfile.open(base/archive['name']) as packed:packed.extractall(extraction,filter='data')
    assert (extraction/'plan.json').read_bytes()==(base/'native-plan.json').read_bytes()
    assert (extraction/'native-experiment.py').read_bytes()==(base/'native-experiment.py').read_bytes()
    for name,digest in plan['support_files'].items():assert sha(extraction/name)==digest,name
    source=extraction/'source';bundle=extraction/plan['bundle']['name']
    assert not (source/'.git').exists() and sha(bundle)==plan['bundle']['sha256']
    env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
             GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1')
    for key in ['GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE',
                'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_CONFIG_COUNT']:
        env.pop(key,None)
    for command in [
        ['git','init','--quiet',str(source)],
        ['git','bundle','verify',str(bundle)],
        ['git','fetch','--no-tags',str(bundle),'HEAD'],
        ['git','update-ref','--no-deref','HEAD',plan['source']['git_head']],
        ['git','read-tree','HEAD']]:
        result=subprocess.run(command,cwd=source,env=env,capture_output=True,text=True,timeout=30)
        records.append({'argv':command,'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        assert result.returncode==0,records[-1]
    actual=source_identity(source)
    assert len(actual['files'])==49 and actual==plan['source'],'Canonical source identity differs'
    fetched=subprocess.check_output(['git','rev-parse','FETCH_HEAD'],cwd=source,env=env,text=True).strip()
    tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=source,env=env,text=True).strip()
    assert fetched==actual['git_head'] and tree==plan['bundle']['git_tree']
    assert not (source/'.git/objects/info/alternates').exists()
    assert len(plan['expected_unit_tests'])==28 and len(set(plan['expected_unit_tests']))==28
proof={'status':'host archive extraction, real Git discovery and canonical49 identity passed',
       'archive_sha256':archive['sha256'],'bundle_sha256':plan['bundle']['sha256'],
       'source_hash':actual['source_hash'],'git_head':actual['git_head'],'git_tree':tree,
       'canonical_app_files':len(actual['files']),'external_alternates':False,'commands':records,
       'syntax':'ast.parse only','vm_calls':False,'builds_tests_or_scoring':False}
(base/'package-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({k:proof[k] for k in ['status','archive_sha256','source_hash','canonical_app_files']}))
