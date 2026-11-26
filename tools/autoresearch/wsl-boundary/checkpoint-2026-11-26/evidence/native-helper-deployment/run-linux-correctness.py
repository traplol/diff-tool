import pathlib,subprocess,shlex,sys
base=pathlib.Path(__file__).resolve().parent
command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','--distribution','Ubuntu-26.04','--user','max','--exec','/usr/bin/python3','-u','-'])
p=subprocess.Popen(['ssh','-F',str(pathlib.Path.home()/'.ssh/config'),'-o','BatchMode=yes','-o','ConnectTimeout=10','windows-vm',command],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
p.stdin.write((base/'linux-correctness-remote.py').read_text());p.stdin.close()
with (base/'linux-correctness.log').open('w') as log:
    for line in p.stdout: log.write(line);log.flush();print(line,end='',flush=True)
raise SystemExit(p.wait())
