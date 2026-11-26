import json,os,time,hashlib,statistics,subprocess,importlib.util,resource
from pathlib import Path
root=Path('/home/max/benchmarks/branchline-boundary/kernel-wsl')
binary=Path('/home/max/.cache/branchline/git-workers/branchline-git-worker-328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa')
assert hashlib.sha256(binary.read_bytes()).hexdigest()=='328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa'
inputs=Path('/home/max/benchmarks/branchline-boundary/git-command-cost-trace-e72a63-r1-input')
m=json.loads((inputs/'workload.json').read_text());assert m['paths']['wsl_linux']==str(root)
p=Path('/home/max/benchmarks/branchline-boundary/branch-native-vs-cli-'+str(time.time_ns()));p.mkdir()
spec=importlib.util.spec_from_file_location('proven_worker',inputs/'backend_compare.py');backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
def guards():
 out={}
 for n in ['index','config','HEAD']:
  f=root/'.git'/n;s=f.stat();out[n]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'size':s.st_size,'mtime':s.st_mtime_ns,'ctime':s.st_ctime_ns,'inode':s.st_ino,'mode':s.st_mode}
 return out
before=guards();rows=[];meta=None;hz=os.sysconf('SC_CLK_TCK')
def proc(pid):
 v=Path('/proc',str(pid),'stat').read_text().rsplit(') ',1)[1].split();return {'start_ticks':v[19],'user':int(v[11]),'system':int(v[12]),'minor_faults':int(v[7]),'major_faults':int(v[9])}
left,right=m['refs'][0],m['refs'][-1]
env=dict(os.environ,LC_ALL='C',GIT_OPTIONAL_LOCKS='0',GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
print(json.dumps({'owner':os.getpid(),'start_ticks':proc(os.getpid())['start_ticks'],'output':str(p)}),flush=True)
for num,method in enumerate(['native','cli','cli','native','native','cli','cli','native']):
 if method=='native':
  records=[];w=backend.Worker(binary,'native-'+str(num),p,records,cwd=root,env=env);owned=proc(w.process.pid)
  try:
   hello=w.call('hello','hello');assert hello['os']=='linux' and hello['protocol']==1 and hello['pid']==w.process.pid
   opened=w.call('open','open',path=str(root));a=proc(w.process.pid)
   t=time.perf_counter_ns();result=w.call('first_compare','compare',view=opened['repo'],left=left,right=right);wall=(time.perf_counter_ns()-t)/1e6;b=proc(w.process.pid)
   fields=['status','old','path','old_mode','mode','old_oid','oid','added','removed'];values=[{k:f[k] for k in fields} for f in result['files']]
   assert len(values)==30 and all(f['status']=='M' for f in values)
   if meta is None:meta=values
   assert values==meta
   t=time.perf_counter_ns();again=w.call('second_compare','compare',view=opened['repo'],left=left,right=right);second=(time.perf_counter_ns()-t)/1e6;assert again==result
   row={'method':method,'number':num,'wall_ms':wall,'second_wall_ms':second,'cpu_ms':((b['user']-a['user'])+(b['system']-a['system']))*1000/hz,'minor_faults':b['minor_faults']-a['minor_faults'],'major_faults':b['major_faults']-a['major_faults'],'pid':w.process.pid,'start_ticks':owned['start_ticks'],'records':records}
  finally:w.close()
  assert w.process.returncode==0 and not Path('/proc',str(w.process.pid)).exists();row['exit']=0;row['native_gone']=True
 else:
  command=['git','--no-pager','--literal-pathspecs','-C',str(root),'diff','--no-ext-diff','--no-textconv','--find-renames','--ignore-submodules=none','--raw','--no-abbrev','--numstat','-z',m['kernel_base'],m['head'],'--']
  a=resource.getrusage(resource.RUSAGE_CHILDREN);t=time.perf_counter_ns();r=subprocess.run(command,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=30,check=True);wall=(time.perf_counter_ns()-t)/1e6;b=resource.getrusage(resource.RUSAGE_CHILDREN)
  (p/f'cli-{num}.stdout').write_bytes(r.stdout);(p/f'cli-{num}.stderr').write_bytes(r.stderr)
  parts=r.stdout.split(b'\0');i=0;values=[]
  while i<len(parts) and parts[i].startswith(b':'):
   old_mode,mode,old_oid,oid,status=parts[i][1:].decode().split();path=parts[i+1].decode();assert status=='M';values.append(dict(status=status,old=path,path=path,old_mode=old_mode,mode=mode,old_oid=old_oid,oid=oid));i+=2
  counts={}
  for v in parts[i:]:
   if v:
    add,remove,path=v.split(b'\t',2);counts[path.decode()]=(int(add),int(remove))
  for f in values:f['added'],f['removed']=counts[f['path']]
  assert values==meta
  row={'method':method,'number':num,'wall_ms':wall,'cpu_ms':((b.ru_utime-a.ru_utime)+(b.ru_stime-a.ru_stime))*1000,'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'metadata_parity':True}
 rows.append(row);(p/'state.json').write_text(json.dumps({'status':'running','root':str(root),'before':before,'rows':rows},indent=2)+'\n')
after=guards();assert after==before
summary={'status':'complete-diagnostic-only','source_worker_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'scope':'Fresh native worker vs a fresh native Linux Git child; OS caches are not flushed; exact30 file metadata/stats parity. No GUI verdict.','before':before,'after':after,'rows':rows,'summary':{name:{'median_wall_ms':statistics.median(x['wall_ms'] for x in rows if x['method']==name),'median_cpu_ms':statistics.median(x['cpu_ms'] for x in rows if x['method']==name)} for name in ['native','cli']}}
(p/'state.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'output':str(p),'summary':summary['summary'],'native_first_ms':[r['wall_ms'] for r in rows if r['method']=='native'],'native_second_ms':[r['second_wall_ms'] for r in rows if r['method']=='native'],'all_parity':True,'guard_unchanged':True}),flush=True)
