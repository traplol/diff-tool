#!/usr/bin/env python3
"""Upload and run the pinned diagnostic only after the root agent releases the VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True)
    args=parser.parse_args()
    release='VM GIT COMMAND DIAGNOSTIC RELEASED'
    if args.release!=release:parser.error('Wait for root to release the serial VM slot')
    base=Path(__file__).resolve().parent
    archive=json.loads((base/'native-input.json').read_text());plan=json.loads((base/'native-plan.json').read_text())
    assert sha(base/archive['name'])==archive['sha256']
    for name,digest in archive['controls'].items():assert sha(base/name)==digest,name
    for name,digest in plan['source']['files'].items():assert sha(base/'source'/name)==digest,name
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
            f'os.execv("/usr/bin/python3",["/usr/bin/python3","-u",str(p/"native-diagnostic.py"),"--input",str(p),"--release",{release!r}])')
        command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','-d','Ubuntu-26.04','-u','max','--exec','/usr/bin/python3','-u','-c',script])
        run('native-diagnostic',ssh+[command]);state.update(status='complete; copy and inspect native state before any claim',finished=time.time());save()
    except BaseException as error:
        state.update(status='failed; inspect exact live owner before retry',error=str(error),finished=time.time());save();raise

if __name__=='__main__':main()
