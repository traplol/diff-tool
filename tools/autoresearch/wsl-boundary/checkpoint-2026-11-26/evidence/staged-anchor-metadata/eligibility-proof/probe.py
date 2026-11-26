
import hashlib,importlib.util,json,os,sqlite3,sys,time
from pathlib import Path
p={'worker': {'path': '/home/max/benchmarks/branchline-boundary/staged-anchor-metadata-aba80d920269-bundle-r2-native/branchline-git-worker', 'sha256': 'd729e0eaaff4d8ef4f7f8bed374b984115b2270aae210022ca91470f90741e2e', 'bytes': 4036144}, 'seam': '/home/max/benchmarks/branchline-boundary/git-command-cost-trace-e72a63-r1-input/backend_compare.py', 'seam_sha256': 'b184265bf085720774b3d661534878846eff5484befe3075345fbc8132e5a79b', 'root': '/home/max/benchmarks/branchline-boundary/kernel-wsl', 'db': '/mnt/c/Users/max/branchline-bench/profiles/baseline-windows-linux/data/Branchline/reviews.sqlite3'}
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
def identity(pid):
 d=Path('/proc')/str(pid)
 if not d.exists():return None
 return dict(pid=pid,start_ticks=(d/'stat').read_text().rsplit(') ',1)[1].split()[19],image=str((d/'exe').resolve()),cwd=str((d/'cwd').resolve()))
def guards():
 out={}
 for path in [Path(p['root'])/'.git'/x for x in ['index','config','HEAD']]+[Path(p['db'])]:
  a=path.stat();digest=sha(path);b=path.stat()
  fields=lambda st:dict(bytes=st.st_size,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns,inode=st.st_ino,device=st.st_dev,mode=st.st_mode)
  assert fields(a)==fields(b),'File changed while read'
  out[str(path)]={'sha256':digest,**fields(b)}
 return out
assert sha(p['worker']['path'])==p['worker']['sha256'] and Path(p['worker']['path']).stat().st_size==p['worker']['bytes'],'Pinned worker missing/mismatched; stop'
assert sha(p['seam'])==p['seam_sha256'],'Worker seam changed'
output=Path('/home/max/benchmarks/branchline-boundary/staged-note2-eligibility-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));output.mkdir()
r={'scope':'read-only saved note eligibility only; no GUI-path or benchmark claim','parameters':p,'controller':identity(os.getpid()),'before':guards(),'database_mode':'ro','output':str(output)}
print(json.dumps({'controller':r['controller'],'output':str(output)}),file=sys.stderr,flush=True)
with sqlite3.connect(Path(p['db']).as_uri()+'?mode=ro',uri=True) as db:
 row=db.execute('SELECT data,resolved FROM notes WHERE id=?',(2,)).fetchone()
 assert row is not None and row[1]==0
 note=json.loads(row[0]);assert note['body']=='Boundary benchmark working-tree comment'
 r['note']={key:note.get(key) for key in ['old_path','path','left','left_tip','group','file_version']};r['note']['id']=2
version=note['file_version'];assert isinstance(version,list) and len(version)==4
expected={'path':note['path'],'old_oid':version[0],'oid':version[1],'old_mode':version[2],'mode':version[3]}
spec=importlib.util.spec_from_file_location('existing_worker_seam',p['seam']);seam=importlib.util.module_from_spec(spec);spec.loader.exec_module(seam)
records=[];worker=seam.Worker(Path(p['worker']['path']),'note2',output,records,cwd=output)
try:
 r['hello']=worker.call('hello','hello');r['worker']=identity(worker.process.pid)
 assert r['hello']['protocol']==2 and r['hello']['os']=='linux' and r['hello']['pid']==worker.process.pid and r['worker']['image']==p['worker']['path']
 print(json.dumps({'worker':r['worker']}),file=sys.stderr,flush=True)
 view=worker.call('open','open',path=p['root'])['repo'];r['repo']={k:view[k] for k in ['checkout','refs']};r['expected']=expected
 r['proof']=worker.call('saved_note2','verify_staged_versions',view=view,checkout=view['checkout'],expected=[expected])
 r['metadata_proof_pass']=r['proof'] is not None and r['proof']['versions']==[expected]
 r['lookup_preconditions']={'same_raw_path':note['old_path']==note['path'],'checkout_matches_note_left':view['checkout']==note['left'],'staged_group':note['group']=='Staged','left_tip_equals_current_checkout_tip':note['left_tip']==view['refs'][view['checkout']]}
finally:
 worker.process.stdin.close()
 try:r['worker_exit']=worker.process.wait(timeout=15)
 except BaseException:
  r['graceful_eof_failed']=True;worker.close();raise
 worker.selector.close();worker.stderr.close()
 r['after']=guards();r['guards_unchanged']=r['before']==r['after'];r['exact_native_absent']=identity(worker.process.pid)!=r.get('worker')
 r['worker_stderr']=(output/'note2.stderr').read_text();r['requests']=[{'op':x['op'],'response_sha256':x['response_sha256']} for x in records]
 (output/'proof.json').write_text(json.dumps(r,indent=2)+'\n')
assert r['worker_exit']==0 and r['guards_unchanged'] and r['exact_native_absent']
print(json.dumps(r,indent=2),flush=True)
