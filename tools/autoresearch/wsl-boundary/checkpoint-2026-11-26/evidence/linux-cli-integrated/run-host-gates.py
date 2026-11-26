#!/usr/bin/env python3
"""Serial existing suites for the integrated source, with fresh root producer evidence."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time
base=Path(__file__).resolve().parent;root=base.parents[2];source=base/'source'
sys.path.insert(0,str(root/'tools/autoresearch/wsl-boundary'));from score import source_identity
expected=json.loads((base/'source.json').read_text());assert source_identity(source)==expected
record_path=base/'host-gates.json';assert not record_path.exists(),'Existing gate owner/results must be inspected; never restart on observation timeout'
state={'pid':os.getpid(),'start_ticks':Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19],'status':'running','source':expected,'started':time.time(),'phases':[]}
def save():
 temp=record_path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(record_path)
def producer(log,manifest,name,kind):
 values=[]
 for line in log.read_text().splitlines():
  try:d=json.loads(line)
  except ValueError:continue
  if d.get('reason')=='compiler-artifact' and d.get('manifest_path')==str(manifest) and d.get('target',{}).get('name')==name and d['target']['kind']==[kind] and d.get('profile',{}).get('test') is True and d.get('executable'):values.append(d)
 assert len(values)==1,(name,kind,len(values));d=values[0]
 assert d['fresh'] is False and d['profile']['opt_level']=='0' and d['executable'] in d['filenames'],(name,'Stale or wrong-profile root artifact')
 return d
try:
 save()
 for name,relative,target in [('worker','src-tauri/git-worker/Cargo.toml','git-worker'),('gui','src-tauri/Cargo.toml','')]:
  manifest=source/relative;env=dict(os.environ,CARGO_BUILD_JOBS='1',CMAKE_BUILD_PARALLEL_LEVEL='1',CARGO_TARGET_DIR=str(root/'src-tauri/target'/target))
  if name=='gui':
   directory=root/'build/linux-dev/root/usr/lib/x86_64-linux-gnu';env.update(PKG_CONFIG_PATH=str(directory/'pkgconfig'),LIBRARY_PATH=str(directory),LD_LIBRARY_PATH=str(directory))
  command=['cargo','test','--offline','--locked','--manifest-path',str(manifest),'--message-format=json']
  if name=='gui':command+=['--lib']
  command+=['--','--test-threads=1'];log=base/(name+'-tests.log')
  phase={'name':name,'argv':command,'cwd':str(source),'started':time.time(),'log':str(log),'environment':{k:env[k] for k in ['CARGO_BUILD_JOBS','CMAKE_BUILD_PARALLEL_LEVEL','CARGO_TARGET_DIR','PKG_CONFIG_PATH','LIBRARY_PATH','LD_LIBRARY_PATH'] if k in env}};state['phases'].append(phase);save()
  with log.open('wb') as stream:
   child=subprocess.Popen(command,cwd=source,env=env,stdout=stream,stderr=subprocess.STDOUT);phase['pid']=child.pid;phase['start_ticks']=Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ',1)[1].split()[19];save();phase['exit']=child.wait()
  phase.update(finished=time.time(),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest());save();assert phase['exit']==0,(name,phase['exit'])
  phase['producer_artifacts']={'unit':producer(log,manifest,'branchline-git-worker' if name=='worker' else 'branchline','bin' if name=='worker' else 'lib')}
  if name=='worker':phase['producer_artifacts']['stdio']=producer(log,manifest,'stdio','test')
  phase['suite_results']=[{'passed':int(a),'failed':int(b),'ignored':int(c)} for a,b,c in re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;',log.read_text())]
  save();assert source_identity(source)==expected
 state.update(status='passed; exact integrated source and fresh root producers verified; native matrix pending',finished=time.time());save()
except BaseException as error:
 state.update(status='failed; inspect preserved evidence before retry',error=str(error),finished=time.time());save();raise
print(json.dumps({'status':state['status'],'source_hash':expected['source_hash'],'phases':[{k:p[k] for k in ['name','pid','exit','suite_results']} for p in state['phases']]}),flush=True)
