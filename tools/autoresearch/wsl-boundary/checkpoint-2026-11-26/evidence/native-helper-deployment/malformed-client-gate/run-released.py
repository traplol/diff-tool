from pathlib import Path
import hashlib,json,os,shlex,subprocess,tarfile,time,traceback
h=Path(__file__).resolve().parent;o=h/'host-evidence';o.mkdir(exist_ok=False);root='/home/max/benchmarks/branchline-boundary/native-helper-malformed-252dec';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads((h/'plan.json').read_text());plan['prepared_plan_sha256']=sha(h/'plan.json');plan['execution_release']='VM MALFORMED CLIENT GATE RELEASED';plan['observability_delta']='Added one fixture-installed JSON event before Connection creation; malformed-response assertions and retained-pipe invariant unchanged.';plan['files']={str(p.relative_to(h)):sha(p) for p in h.rglob('*') if p.is_file() and 'host-evidence' not in p.parts and p.name!='execution-plan.json'};(h/'execution-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
for n in ['supervisor.py']:compile((h/n).read_text(),str(h/n),'exec')
archive=o/'input.tar'
with tarfile.open(archive,'w') as t:
 for n in [*plan['files'],'execution-plan.json']:t.add(h/n,arcname=n,recursive=False)
ssh=['ssh','-F',str(Path.home()/'.ssh/config'),'-o','BatchMode=yes','-o','ConnectTimeout=10','windows-vm'];win='/c/Users/max/branchline-bench/native-helper-malformed-252dec.tar';mounted='/mnt/c/Users/max/branchline-bench/native-helper-malformed-252dec.tar'
owner={'host_pid':os.getpid(),'started':time.time(),'archive_sha256':sha(archive),'vm_root':root,'status':'running'}
def save():(o/'owner.json').write_text(json.dumps(owner,indent=2)+'\n')
def wsl(code):return ssh+['MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','--distribution','Ubuntu-26.04','--user','max','--exec','/usr/bin/python3','-u','-c',code])]
save();print(json.dumps(owner),flush=True)
try:
 subprocess.run(ssh+['test ! -e '+shlex.quote(win)+' && cat > '+shlex.quote(win)],input=archive.read_bytes(),check=True,timeout=120)
 code='import pathlib,tarfile,os,hashlib;p=pathlib.Path('+repr(root)+');p.mkdir(exist_ok=False);a=pathlib.Path('+repr(mounted)+');assert hashlib.sha256(a.read_bytes()).hexdigest()=='+repr(sha(archive))+';tarfile.open(a).extractall(p,filter="data");os.execv("/usr/bin/python3",["/usr/bin/python3","-u",str(p/"supervisor.py")])'
 child=subprocess.Popen(wsl(code),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True);owner['ssh_pid']=child.pid;save()
 with (o/'supervisor.stdout.log').open('w') as log:
  for line in child.stdout:
   log.write(line);log.flush();print(line,end='',flush=True)
   try:
    event=json.loads(line)
    if event.get('supervisor_pid'):owner['vm_supervisor']=event
    if event.get('child_pid'):owner['current_child']=event
    save()
   except ValueError:pass
 owner['exit']=child.wait()
 evidence=subprocess.check_output(wsl('import subprocess;subprocess.run(["tar","-C",'+repr(root)+',"-cf","-","evidence"],check=True)'),timeout=120);(o/'vm-evidence.tar').write_bytes(evidence)
 with tarfile.open(o/'vm-evidence.tar') as t:t.extractall(o/'vm',filter='data')
 owner['status']='terminal';save();raise SystemExit(owner['exit'])
except BaseException:
 owner['error']=traceback.format_exc();owner['finished']=time.time();save();raise
