import json,pathlib,os,time
record=pathlib.Path('/home/max/benchmarks/branchline-boundary/native-helper-deployment-b2de070-03fecde11c0a-native/supervisor.json')
s=json.loads(record.read_text()); phase=s['phases'][-1] if s['phases'] else None
hz=os.sysconf('SC_CLK_TCK'); pages=os.sysconf('SC_PAGE_SIZE')
def snapshot(pid):
    rows=[]; pending=[pid]; seen=set()
    while pending:
        pid=pending.pop()
        if pid in seen: continue
        seen.add(pid); p=pathlib.Path('/proc')/str(pid)
        try:
            values=(p/'stat').read_text().rsplit(') ',1)[1].split()
            rows.append({'pid':pid,'start_ticks':values[19],'state':values[0],
                'cpu_ticks':int(values[11])+int(values[12]),'rss_mb':int(values[21])*pages/1024/1024,
                'args':(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')[:600]})
            for task in (p/'task').iterdir():
                try: pending.extend(int(x) for x in (task/'children').read_text().split())
                except (FileNotFoundError,ProcessLookupError): pass
        except (FileNotFoundError,ProcessLookupError): pass
    return rows
first=snapshot(phase['pid']) if phase else []; t=time.monotonic(); time.sleep(1); elapsed=time.monotonic()-t
second=snapshot(phase['pid']) if phase else []
for row in second:
    prior=next((x for x in first if x['pid']==row['pid'] and x['start_ticks']==row['start_ticks']),None)
    row['cpu_percent_over_sample']=(row['cpu_ticks']-prior['cpu_ticks'])/hz/elapsed*100 if prior else None
fresh=json.loads(record.read_text()); log=pathlib.Path(phase['log']) if phase else None
print(json.dumps({'pid':s['pid'],'start_ticks':s['start_ticks'],'status':fresh['status'],'current_phase':fresh.get('current_phase'),
    'observed_phase':phase,'cpu_sample_seconds':elapsed,'owned_child_tree':second,
    'log_bytes':log.stat().st_size if log else None,'log_mtime_unix':log.stat().st_mtime if log else None,
    'log_tail':log.read_text(errors='replace')[-2400:] if log else None},indent=2))
