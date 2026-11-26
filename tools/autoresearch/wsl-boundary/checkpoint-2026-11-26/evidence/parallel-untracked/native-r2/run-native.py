#!/usr/bin/env python3
"""Upload and run the pinned experiment only after the root agent releases the VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import time


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True)
    args=parser.parse_args()
    release='VM PARALLEL UNTRACKED NATIVE R2 RELEASED'
    if args.release!=release:parser.error('Wait for root to release the serial VM slot')
    base=Path(__file__).resolve().parent
    archive=json.loads((base/'native-input.json').read_text());plan=json.loads((base/'native-plan.json').read_text())
    assert sha(base/archive['name'])==archive['sha256']
    for name,digest in archive['controls'].items():assert sha(base/name)==digest,name
    for name,digest in plan['source']['files'].items():assert sha(base.parent/'source'/name)==digest,name
    assert sha(base/plan['bundle']['name'])==plan['bundle']['sha256']
    subprocess.run([sys.executable,str(base/'verify-package.py')],check=True)
    state_path=base/'native-owner.json';assert not state_path.exists(),'Existing run record: inspect same owner/results, never blindly restart'
    state={'pid':os.getpid(),'started':time.time(),'status':'running','archive':archive,'phases':[]}
    def save():
        t=state_path.with_suffix('.tmp');t.write_text(json.dumps(state,indent=2)+'\n');t.replace(state_path)
    def run(name,argv,data=None):
        record={'name':name,'argv':argv,'started':time.time()};state['phases'].append(record);save()
        with (base/(name+'.log')).open('wb') as log:
            child=subprocess.Popen(argv,stdin=subprocess.PIPE if data else subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            record['pid']=child.pid;record['start_ticks']=Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ',1)[1].split()[19];save()
            child.communicate(data);record.update(exit=child.returncode,finished=time.time());save();assert child.returncode==0,(name,child.returncode)
    ssh=['ssh','-F',str(Path.home()/'.ssh/config'),'-o','BatchMode=yes','-o','ConnectTimeout=10','windows-vm']
    try:
        save();upload='/c/Users/max/branchline-bench/'+archive['name']
        run('upload-native-input',ssh+['cat > '+shlex.quote(upload)],(base/archive['name']).read_bytes())
        script=(
            'import hashlib,os,pathlib,tarfile; '
            f'a=pathlib.Path({("/mnt/c/Users/max/branchline-bench/"+archive["name"])!r}); '
            f'assert hashlib.sha256(a.read_bytes()).hexdigest()=={archive["sha256"]!r}; '
            f'p=pathlib.Path({plan["input"]!r});p.mkdir(exist_ok=False); '
            'tarfile.open(a).extractall(p,filter="data"); '
            f'os.execv("/usr/bin/python3",["/usr/bin/python3","-u",str(p/"native-experiment.py"),"--input",str(p),"--release",{release!r}])')
        command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','-d','Ubuntu-26.04','-u','max','--exec','/usr/bin/python3','-u','-c',script])
        run('native-experiment',ssh+[command])
        collect=(
            'import json,pathlib,sys,tarfile; '
            f'p=pathlib.Path({plan["output"]!r});s=json.loads((p/"state.json").read_text()); '
            'assert s["status"]=="complete-backend-preliminary-only" and s["valid"] is True; '
            'a=pathlib.Path("/proc")/str(s["pid"])/"stat"; '
            'assert not a.exists() or a.read_text().rsplit(") ",1)[1].split()[19]!=s["start_ticks"]; '
            't=tarfile.open(fileobj=sys.stdout.buffer,mode="w|");t.add(p,arcname="."); '
            f't.add({plan["native_output"]!r},arcname="binaries");t.close()')
        collect_command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','-d','Ubuntu-26.04','-u','max','--exec','/usr/bin/python3','-u','-c',collect])
        run('native-evidence',ssh+[collect_command])
        with tarfile.open(base/'native-evidence.log') as packed:packed.extractall(base/'native-evidence',filter='data')
        proof=json.loads((base/'native-evidence/state.json').read_text())
        assert proof['source_identity']==plan['source'] and proof['guard_before']==proof['guard_after']
        assert all(value['fresh'] is False for value in proof['producer_artifacts'].values())
        for field in ['candidate_worker','native_unit_tests']:
            assert sha(base/'native-evidence/binaries'/Path(proof[field]['path']).name)==proof[field]['sha256']
        state.update(status='complete backend-only; no GUI acceptance or promotion',finished=time.time());save()
    except BaseException as error:
        state.update(status='failed; inspect exact live owner before retry',error=str(error),finished=time.time());save();raise

if __name__=='__main__':main()
