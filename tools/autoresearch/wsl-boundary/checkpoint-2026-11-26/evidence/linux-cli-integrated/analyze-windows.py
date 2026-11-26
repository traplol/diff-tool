#!/usr/bin/env python3
"""Host-only JSON analysis of the integrated Windows two-cell series."""
from pathlib import Path
import hashlib
import json
import math
import statistics
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'tools/autoresearch/wsl-boundary'));import score
RUN=HERE/'evaluation-controls/windows/run-20261126T010119508886Z';STATE=RUN/'state.json'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();state=json.loads(STATE.read_text());protocol=json.loads((HERE/'evaluation-controls/protocol.json').read_text())
assert state['status']=='complete-valid-awaiting-charter-review' and state['acceptance']==protocol
assert state['fixture_before']==state['fixture_after'] and state['contract_sha256']==score.contract_identity()['sha256']==protocol['contract_sha256']
assert state['case_order']==['windows_linux','windows_windows'] and len(state['runs'])==12
assert [(r['case'],r['variant'],r['number'],r['repetitions']) for r in state['runs']]==[(c,v,n,k) for c in state['case_order'] for v,n,k in [('A',1,3),('B',1,3),('A',2,3),('B',2,3),('A',3,20),('B',3,20)]]
rows=[];processes=[];inputs={};actions=('open',*score.ACTIONS)
def read(p):
 p=Path(p);inputs[str(p)]=sha(p);return json.loads(p.read_text())
def stats(x):
 x=list(x);assert x and all(math.isfinite(v) for v in x)
 return {'count':len(x),'p50_ms':score.percentile(x,.5),'median_ms':statistics.median(x),'p95_ms':score.percentile(x,.95),'max_ms':max(x)}
def union(calls,total):
 out=[]
 for a,b in sorted((max(0,c['start_ms']),min(total,c['start_ms']+c['elapsed_ms'])) for c in calls if c.get('elapsed_ms') is not None):
  if b<=a:continue
  if out and a<=out[-1][1]:out[-1][1]=max(b,out[-1][1])
  else:out.append([a,b])
 return out
for run in state['runs']:
 version=state['variants'][run['variant']];case=run['case'];directory=Path(run['directory'])
 verdict=read(run['verdict']);launch=read(directory/'launch.json');cleanup=read(directory/'cleanup.json');welcome=read(directory/'welcome-ready.json');source=read(directory/'score/source.json')
 assert run['status']=='complete-valid-stopped' and run['cleanup_complete'] and run['score_exit']==0
 assert verdict['valid'] and verdict['case']==case and verdict['repetitions']==run['repetitions'] and verdict['contract']['sha256']==state['contract_sha256']
 assert verdict['source_hash']==version['source_hash'] and verdict['binary_sha256']==version['binary_sha256']
 assert launch==run['launch']==verdict['launch'] and launch['source_hash']==version['source_hash'] and launch['binary_sha256']==version['binary_sha256']
 assert source==score.source_identity(version['source']) and source['source_hash']==version['source_hash']
 assert launch['profile']==state['cases'][case]['profile'] and run['welcome_startup_error_observed']
 assert cleanup==run['cleanup'] and cleanup['exact_owned_processes_absent'] and cleanup['ports_free']
 sample_path=Path(run['samples']);inputs[str(sample_path)]=sha(sample_path);raw=[json.loads(line) for line in sample_path.read_text().splitlines()];score.validate_samples(raw,run['repetitions']);assert score.summarize(raw,run['repetitions'])['actions']==verdict['actions']
 for s in raw:
  assert (s['action']=='open' and s['phase']=='fresh_process') or (s['action']!='open' and s['phase']==('first_use' if s['repetition']==0 else 'repeated'))
  total=s['elapsed_ms'];fg=union(s['ipc'],total);bg=union(s.get('background_ipc',[]),total);coverage=sum(b-a for a,b in fg)
  assert all(c['start_ms']>=0 and c['start_ms']+c['elapsed_ms']<=total+.001 for c in s['ipc'])
  rows.append({**s,'case':case,'variant':run['variant'],'process_number':run['number'],'foreground_union_intervals_ms':fg,'foreground_ipc_union_ms':coverage,'non_foreground_ipc_remainder_ms':total-coverage,'after_last_foreground_ipc_ms':total-max(b for a,b in fg),'completed_background_union_ms':sum(b-a for a,b in bg),'pending_background_count':sum(c.get('elapsed_ms') is None for c in s.get('background_ipc',[])),'source_samples':str(sample_path)})
 processes.append({'case':case,'variant':run['variant'],'number':run['number'],'repetitions':run['repetitions'],'launch':launch,'verdict':run['verdict'],'cleanup':cleanup,'welcome_ready':True,'viewport':welcome['viewport'],'valid':True})
assert len(rows)==636
assert state['master_check']['exit']==0 and state['master_exit_request']['exit']==0 and state['tunnel_exit']==255 and state['control_socket_absent'] and state['host_loopback_port_free']
tunnel=state['tunnel'];assert '-M' in tunnel['argv'] and tunnel['control_socket'] in tunnel['argv'] and '127.0.0.1:19223:127.0.0.1:29223' in tunnel['argv'];assert not Path(tunnel['control_socket']).exists()
actors=[]
for a in [state,tunnel]:
 p=Path('/proc')/str(a['pid'])/'stat';current=p.read_text().rsplit(') ',1)[1].split()[19] if p.exists() else None;assert current!=a['start_ticks'];actors.append({'pid':a['pid'],'start_ticks':a['start_ticks'],'exact_owned_actor_absent_now':True,'current_start_ticks':current})
metrics={};ipc={};guards={};selections={}
for case in state['case_order']:
 metrics[case]={};ipc[case]={};guards[case]=[];selections[case]={}
 for variant in ['A','B']:
  metrics[case][variant]={};ipc[case][variant]={}
  for action in actions:
   all_rows=[r for r in rows if r['case']==case and r['variant']==variant and r['action']==action]
   measured=all_rows if action=='open' else [r for r in all_rows if r['process_number']==3]
   strict=[r for r in measured if r['phase']=='repeated']
   metrics[case][variant][action]={'measurement':stats(r['elapsed_ms'] for r in measured),'strict_repeated19':stats(r['elapsed_ms'] for r in strict) if strict else None,'all_series':stats(r['elapsed_ms'] for r in all_rows),'first_use_by_process_ms':[r['elapsed_ms'] for r in all_rows if r['repetition']==0]}
   ipc[case][variant][action]={k:stats(r[k] for r in measured) for k in ['foreground_ipc_union_ms','non_foreground_ipc_remainder_ms','after_last_foreground_ipc_ms']}
   ops={}
   for r in measured:
    for c in r['ipc']:ops.setdefault(c['command']+'/'+c.get('op',''),[]).append(c['elapsed_ms'])
   ipc[case][variant][action]['by_command_and_op']={k:stats(v) for k,v in ops.items()}
   ordered=sorted(measured,key=lambda r:r['elapsed_ms']);n=len(ordered)
   selections[case].setdefault(action,{})[variant]={k:ordered[i] for k,i in [('near_p50',math.ceil(n*.5)-1),('p95',math.ceil(n*.95)-1),('max',n-1)]}
 for action in actions:
  a=metrics[case]['A'][action]['measurement'];b=metrics[case]['B'][action]['measurement']
  for key in (['median_ms','p95_ms'] if case=='windows_windows' else ['p95_ms']):
   guards[case].append({'action':action,'metric':key,'A_ms':a[key],'B_ms':b[key],'change_percent':(b[key]/a[key]-1)*100,'limit_ratio':1.1,'pass':b[key]<=1.1*a[key]})
failed={case:[g for g in cells if not g['pass']] for case,cells in guards.items()}
branch_group=['branch_first','branch_final','stack','comment_branch'];primary={v:max(metrics['windows_linux'][v][a]['measurement']['p95_ms'] for a in branch_group) for v in ['A','B']};gain=(1-primary['B']/primary['A'])*100;gain_pass=primary['B']<=.9*primary['A']
# Exact sample rows and interval deltas for every failed p95 guard; maxima are retained separately, never a new acceptance gate.
failed_details=[]
for case in state['case_order']:
 for g in failed[case]:
  selected=selections[case][g['action']];a=selected['A']['p95'];b=selected['B']['p95']
  failed_details.append({'case':case,'guard':g,'A_p95_row':a,'B_p95_row':b,'B_minus_A_at_p95_rows':{k:b[k]-a[k] for k in ['elapsed_ms','foreground_ipc_union_ms','non_foreground_ipc_remainder_ms']},'A_max_row':selected['A']['max'],'B_max_row':selected['B']['max']})
inputs[str(STATE)]=sha(STATE);inputs[str(HERE/'evaluation-controls/protocol.json')]=sha(HERE/'evaluation-controls/protocol.json')
summary={'status':'valid partial integrated matrix; primary gain and observed p95 guards fail; no promotion','scope':'WindowsGUI→WSL primary and WindowsGUI→NTFS same-side only; bothLinuxGUI cells pending. No oldpilot/source samples pooled.','source_hash':protocol['source_hash'],'git_head':protocol['git_head'],'state':str(STATE),'state_sha256':sha(STATE),'contract_sha256':state['contract_sha256'],'fixture_sha256':state['fixture_sha256'],'valid_runs':12,'sample_count':636,'variants':state['variants'],'statistics':'Canonical nearest-rank p50/p95 and conventional median. Actions use fullfinal20 including first_use, strictrepeated19 separate (n19nearest-rankp95 ismaximum), allseries26 retained. Openall3/fresh observations never dropped. No OScacheflush.','metrics':metrics,'foreground_ipc_union_and_remainder':ipc,'qualification':{'primary_branch_group_worst_p95_ms':primary,'primary_branch_group_improvement_percent':gain,'primary_branch_gain_10percent_pass':gain_pass,'per_case_guards':guards,'failed_guards':failed,'observed_windows_cells_guard_pass':not any(failed.values()),'full_matrix_complete':False,'optimization_qualified':False,'promoted':False},'failed_guard_ipc_details':failed_details,'retained_max_p95_near_p50_rows':selections,'processes_and_cleanup':processes,'fixture_before':state['fixture_before'],'fixture_after':state['fixture_after'],'transport_cleanup':{k:state[k] for k in ['tunnel','master_check','master_exit_request','tunnel_exit','control_socket_absent','host_loopback_port_free']},'exact_host_controller_and_master_absent_now':actors,'cleanup_scope':'All12 recorded exact Windowsapp/observedchild/taskport cleanups pass. No newVM inventory orportcheck during hostanalysis.','input_hashes':inputs,'interpretation':['Oldb2/a4pilot20.85%branchgroupgain is not replicated by this delivered-source comparison; oldGNU92d equals newGNU92d but this does not establish why samples differ.','Primarybranchgroup p95 gains only1.88%, below frozen10%; primaryWT andWTcomment p95 regress beyond10%. Allsixsame-side actionp95 guards fail, despite median guards passing.','No waiver, outlier removal, retry or noise/source/AV-causality claim.','Exact relative foreground/background intervals locate recorded extra time; the nonforeground remainder includes UI, frames, waits and unrecorded work, not paint-only.','Windows2cell decisions are partial; Linuxcells and fullgoal cold/delivered acceptance remain pending.']}
(RUN/'ipc-samples.json').write_text(json.dumps(rows,indent=2)+'\n');(RUN/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['The two Windows cells are valid, but this partial integrated matrix fails the frozen primary-gain requirement and observed p95 guards. Do not promote. The two Linux GUI cells remain pending.','',
'All12 fresh processes and636 samples pass native content/comment correctness, welcome readiness, exact source/binary identities, fixture guards and recorded Windowsapp/child/taskport cleanup. The private master received exit acknowledgement0 and exited255; its socket is absent and port19223 was recorded free. Exact host controller/master identities are absent now. No VM access or new port check occurred during this analysis.','',
f"Primary branch-group worst p95 {primary['A']:.1f}→{primary['B']:.1f}ms improves{gain:.2f}%, below10%. The older b2/a4pilot20.85% result is not pooled or reproduced here. Identical GNU92d bytes do not establish a cause for the difference. No noise, source or antivirus explanation is claimed. No maxima are turned into new hard acceptance gates.",'']
for case in state['case_order']:
 lines +=[case,'', 'Open by fresh process1/2/3: A '+ ' / '.join(f'{v:.1f}' for v in metrics[case]['A']['open']['first_use_by_process_ms'])+'ms; B '+' / '.join(f'{v:.1f}' for v in metrics[case]['B']['open']['first_use_by_process_ms'])+'ms. These are not OS-cold.','', '| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |','|---|---:|---:|---:|---:|']
 for action in actions:
  a=metrics[case]['A'][action]['measurement'];b=metrics[case]['B'][action]['measurement'];fmt=lambda s:f"{s['p50_ms']:.1f}/{s['p95_ms']:.1f}/{s['max_ms']:.1f}"
  lines.append(f"| {action} | {fmt(a)} | {fmt(b)} | {(b['median_ms']/a['median_ms']-1)*100:+.2f}% | {(b['p95_ms']/a['p95_ms']-1)*100:+.2f}% |")
 lines+=['','Failed frozen guards: '+('; '.join(f"{g['action']} {g['metric']} {g['change_percent']:+.2f}%" for g in failed[case]) or 'none')+'.','', '| Action | A first-use ms | B first-use ms |','|---|---:|---:|']
 for action in actions:lines.append('| '+action+' | '+' / '.join(f'{v:.1f}' for v in metrics[case]['A'][action]['first_use_by_process_ms'])+' | '+' / '.join(f'{v:.1f}' for v in metrics[case]['B'][action]['first_use_by_process_ms'])+' |')
 lines+=['','Foreground/remainder p50/p95/max ms (same Open3/final20 scope):','', '| Action | A foreground | B foreground | A remainder | B remainder |','|---|---:|---:|---:|---:|']
 for action in actions:
  fmt=lambda s:f"{s['p50_ms']:.1f}/{s['p95_ms']:.1f}/{s['max_ms']:.1f}"
  lines.append('| '+action+' | '+' | '.join(fmt(ipc[case][v][action][key]) for key in ['foreground_ipc_union_ms','non_foreground_ipc_remainder_ms'] for v in ['A','B'])+' |')
lines+=['','Failed p95 guard rows; these are exact order-statistic samples, not paired operations. Raw calls and every max are retained in summary.json and ipc-samples.json.','', '| Case/action | A p95 total/FG/remainder | B p95 total/FG/remainder | Delta total/FG/remainder |','|---|---:|---:|---:|']
for detail in failed_details:
 a=detail['A_p95_row'];b=detail['B_p95_row'];delta=detail['B_minus_A_at_p95_rows'];fmt=lambda r:'/'.join(f'{r[k]:.1f}' for k in ['elapsed_ms','foreground_ipc_union_ms','non_foreground_ipc_remainder_ms'])
 lines.append('| '+detail['case']+'/'+detail['guard']['action']+' | '+fmt(a)+' | '+fmt(b)+' | '+fmt(delta)+' |')
lines+=['','Primary B3 Open1996.7ms and the original A1 Opens remain present. Native Open/display_patch intervals and background work are retained verbatim. Full20, strict repeated19, all-series maxima and every first-use result are separate; no outlier is removed. Foreground coverage is a union, and the remainder is not paint-only.','',
'Decision: hold the integrated candidate unpromoted. Complete the already-planned remaining matrix cells and investigate observed failures without waivers. This host analysis performs no retries, VM calls, tests, builds, profiling or source/control changes. The250ms full goal remains unmet.']
(RUN/'decision.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'summary':str(RUN/'summary.json'),'summary_sha256':sha(RUN/'summary.json'),'samples':len(rows),'primary_gain_percent':gain,'failed_guards':{c:[g['action']+'/'+g['metric'] for g in v] for c,v in failed.items()},'decision':'partialfail; no promotion'}))
