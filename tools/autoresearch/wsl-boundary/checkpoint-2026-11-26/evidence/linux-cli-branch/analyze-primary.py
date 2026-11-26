#!/usr/bin/env python3
"""Host-only analysis of the frozen a4 primary series; no runtime or retries."""
from pathlib import Path
import hashlib
import json
import math
import statistics
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'tools/autoresearch/wsl-boundary'))
import score
RUN=HERE/'evaluation-windows-wsl/run-20261126T002806794314Z'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
state=json.loads((RUN/'state.json').read_text());acceptance=json.loads((HERE/'evaluation-windows-wsl/acceptance.json').read_text())
assert state['status']=='complete-valid-awaiting-charter-review'
assert state['acceptance']==acceptance and state['contract_sha256']==score.contract_identity()['sha256']==acceptance['contract_sha256']
assert state['fixture_before']==state['fixture_after'];assert len(state['runs'])==6
assert [(r['variant'],r['number'],r['repetitions']) for r in state['runs']]==[('A',1,3),('B',1,3),('A',2,3),('B',2,3),('A',3,20),('B',3,20)]
actions=('open',*score.ACTIONS);rows=[];records=[];inputs={};viewports=[]

def read(path):
    path=Path(path);inputs[str(path)]=sha(path);return json.loads(path.read_text())

def stats(values):
    values=list(values);assert values and all(math.isfinite(v) for v in values)
    return {'count':len(values),'p50_ms':score.percentile(values,.5),'median_ms':statistics.median(values),'p95_ms':score.percentile(values,.95),'max_ms':max(values)}

def merged(calls,total):
    intervals=[]
    for c in calls:
        start=c.get('start_ms');elapsed=c.get('elapsed_ms')
        if elapsed is None:continue
        assert isinstance(start,(int,float)) and isinstance(elapsed,(int,float)) and math.isfinite(start) and math.isfinite(elapsed)
        a=max(0,start);b=min(total,start+elapsed)
        if b>a:intervals.append([a,b])
    result=[]
    for a,b in sorted(intervals):
        if result and a<=result[-1][1]:result[-1][1]=max(b,result[-1][1])
        else:result.append([a,b])
    return result

for run in state['runs']:
    version=state['variants'][run['variant']]
    assert run['status']=='complete-valid-stopped' and run['cleanup_complete'] and run['score_exit']==0
    verdict=read(run['verdict']);launch=read(Path(run['directory'])/'launch.json');cleanup=read(Path(run['directory'])/'cleanup.json');welcome=read(Path(run['directory'])/'welcome-ready.json')
    assert verdict['valid'] and verdict['repetitions']==run['repetitions'] and verdict['case']=='windows_linux' and verdict['contract']['sha256']==state['contract_sha256']
    assert verdict['source_hash']==version['source_hash'] and verdict['binary_sha256']==version['binary_sha256']
    assert launch==run['launch']==verdict['launch'] and launch['source_hash']==version['source_hash'] and launch['binary_sha256']==version['binary_sha256']
    assert launch['profile']==state['cases']['windows_linux']['profile']
    assert cleanup==run['cleanup'] and cleanup['exact_owned_processes_absent'] and cleanup['ports_free'] and run['welcome_startup_error_observed']
    samples_path=Path(run['samples']);inputs[str(samples_path)]=sha(samples_path);samples=[json.loads(line) for line in samples_path.read_text().splitlines()];score.validate_samples(samples,run['repetitions'])
    assert score.summarize(samples,run['repetitions'])['actions']==verdict['actions']
    source=read(Path(run['directory'])/'score/source.json');assert source['source_hash']==version['source_hash']
    assert source==score.source_identity(version['source'])
    viewports.append({'variant':run['variant'],'number':run['number'],'viewport':welcome.get('viewport'),'width':welcome.get('width'),'height':welcome.get('height')})
    for s in samples:
        assert (s['action']=='open' and s['phase']=='fresh_process') or (s['action']!='open' and s['phase']==('first_use' if s['repetition']==0 else 'repeated'))
        total=s['elapsed_ms'];intervals=merged(s['ipc'],total);union=sum(b-a for a,b in intervals);background=merged(s.get('background_ipc',[]),total)
        assert union<=total+.001
        for c in s['ipc']:assert c['start_ms']>=0 and c['start_ms']+c['elapsed_ms']<=total+.001
        rows.append({**s,'variant':run['variant'],'process_number':run['number'],'foreground_union_intervals_ms':intervals,
                     'foreground_ipc_union_ms':union,'non_foreground_ipc_remainder_ms':total-union,
                     'after_last_foreground_ipc_ms':total-max(b for a,b in intervals),
                     'completed_background_union_ms':sum(b-a for a,b in background),
                     'pending_background_count':sum(c.get('elapsed_ms') is None for c in s.get('background_ipc',[])),
                     'source_samples':str(samples_path)})
    records.append({'variant':run['variant'],'number':run['number'],'repetitions':run['repetitions'],'launch':launch,'verdict':run['verdict'],'cleanup':cleanup,'score_valid':True,'welcome_ready':True})
assert len(rows)==318
assert state['master_check']['exit']==0 and state['master_exit_request']['exit']==0 and state['tunnel_exit']==255
assert state['control_socket_absent'] and state['host_loopback_port_free']
tunnel=state['tunnel'];argv=tunnel['argv'];assert '-M' in argv and '-S' in argv and tunnel['control_socket'] in argv and '127.0.0.1:19223:127.0.0.1:29223' in argv
assert not Path(tunnel['control_socket']).exists()
actor_checks=[]
for record in [{'pid':state['pid'],'start_ticks':state['start_ticks']},tunnel]:
    p=Path('/proc')/str(record['pid'])/'stat';current=p.read_text().rsplit(') ',1)[1].split()[19] if p.exists() else None
    assert current!=record['start_ticks'];actor_checks.append({'pid':record['pid'],'start_ticks':record['start_ticks'],'exact_actor_absent_now':True,'current_start_ticks':current})

metrics={};ipc={}
for variant in ('A','B'):
    metrics[variant]={};ipc[variant]={}
    for action in actions:
        all_rows=[r for r in rows if r['variant']==variant and r['action']==action]
        measured=all_rows if action=='open' else [r for r in all_rows if r['process_number']==3]
        strict=[r for r in measured if r['phase']=='repeated']
        metrics[variant][action]={'measurement':stats(r['elapsed_ms'] for r in measured),'all_new_series':stats(r['elapsed_ms'] for r in all_rows),'first_use_by_process_ms':[r['elapsed_ms'] for r in all_rows if r['repetition']==0],
            'strict_repeated19':stats(r['elapsed_ms'] for r in strict) if strict else None}
        ipc[variant][action]={key:stats(r[key] for r in measured) for key in ['foreground_ipc_union_ms','non_foreground_ipc_remainder_ms','after_last_foreground_ipc_ms']}
        ops={}
        for r in measured:
            for call in r['ipc']:ops.setdefault(call['command']+'/'+call.get('op',''),[]).append(call['elapsed_ms'])
        ipc[variant][action]['foreground_by_command_and_op']={k:stats(v) for k,v in ops.items()}

def change(a,b):return (b/a-1)*100

guards=[]
for action in actions:
    a=metrics['A'][action]['measurement'];b=metrics['B'][action]['measurement']
    for metric in (['median_ms','p95_ms','max_ms'] if action=='open' else ['p95_ms','max_ms']):
        guards.append({'action':action,'metric':metric,'A_ms':a[metric],'B_ms':b[metric],'change_percent':change(a[metric],b[metric]),'limit_ratio':1.1,'pass':b[metric]<=1.1*a[metric]})
failed=[g for g in guards if not g['pass']]
worst={v:max(metrics[v][a]['measurement']['p95_ms'] for a in actions) for v in ('A','B')}
branch={v:max(metrics[v][a]['measurement']['p95_ms'] for a in ['branch_first','branch_final','stack','comment_branch']) for v in ('A','B')}
open_median={v:metrics[v]['open']['measurement']['median_ms'] for v in ('A','B')}
primary_pass=worst['B']<=.9*worst['A'];branch_pass=branch['B']<=.9*branch['A'];open_pass=open_median['B']<=.9*open_median['A']
accept={'all_correctness_identity_fixture_cleanup_pass':True,'worst_primary_p95_ms':worst,'worst_primary_improvement_percent':-change(worst['A'],worst['B']),'worst_primary_10percent_gain_pass':primary_pass,
        'branch_group_worst_p95_ms':branch,'branch_group_improvement_percent':-change(branch['A'],branch['B']),'branch_group_10percent_gain_pass':branch_pass,
        'fresh_open_median_ms':open_median,'fresh_open_median_improvement_percent':-change(open_median['A'],open_median['B']),'fresh_open_median_10percent_gain_pass':open_pass,
        'corroboration_pass':branch_pass or open_pass,'all_10percent_guards_pass':not failed,'failed_guards':failed,
        'one_cell_qualification_pass':primary_pass and (branch_pass or open_pass) and not failed,'full_campaign_acceptance':False,'promoted':False}
# Retain exact maxima/p95 and near-p50 samples for both sides, including all original Open outliers.
outliers={}
for action in actions:
    outliers[action]={}
    for variant in ('A','B'):
        selected=[r for r in rows if r['variant']==variant and r['action']==action and (action=='open' or r['process_number']==3)]
        ordered=sorted(selected,key=lambda r:r['elapsed_ms']);n=len(ordered)
        outliers[action][variant]={label:ordered[index] for label,index in [('near_p50',math.ceil(n*.5)-1),('p95',math.ceil(n*.95)-1),('max',n-1)]}

inputs[str(RUN/'state.json')]=sha(RUN/'state.json');inputs[str(HERE/'evaluation-windows-wsl/acceptance.json')]=sha(HERE/'evaluation-windows-wsl/acceptance.json')
summary={'status':'valid primary series; frozen one-cell qualification passes; full campaign incomplete','state':str(RUN/'state.json'),'state_sha256':sha(RUN/'state.json'),'contract_sha256':state['contract_sha256'],'fixture_sha256':state['fixture_sha256'],'variants':state['variants'],'sample_count':318,'valid_runs':6,'old_samples_pooled':False,
         'statistics':'Canonical nearest-rank p50/p95 plus conventional median. Open uses all3 fresh processes; actions use final20 including first_use. Strict repeated19 and all-series26 are separate; n19 nearest-rank p95 is its maximum. No sample removed. Fresh process is not OS-cold.',
         'metrics':metrics,'foreground_ipc_union_and_remainder':ipc,'acceptance':accept,'all_action_10percent_guards':guards,'fresh_process_and_first_use':{v:{a:metrics[v][a]['first_use_by_process_ms'] for a in actions} for v in ('A','B')},
         'steady_open_pairs_process2and3':[{'process_number':i,'A_ms':metrics['A']['open']['first_use_by_process_ms'][i-1],'B_ms':metrics['B']['open']['first_use_by_process_ms'][i-1],'change_percent':change(metrics['A']['open']['first_use_by_process_ms'][i-1],metrics['B']['open']['first_use_by_process_ms'][i-1])} for i in (2,3)],
         'processes_and_cleanup':records,'fixture_before':state['fixture_before'],'fixture_after':state['fixture_after'],
         'transport_cleanup':{key:state[key] for key in ['tunnel','master_check','master_exit_request','tunnel_exit','control_socket_absent','host_loopback_port_free']},'host_exact_actor_checks':actor_checks,'cleanup_scope':'All6 recorded exact owned Windows app/observed child and task-port cleanups pass. Private host master/controller identities are absent now. No new VM process inventory or port access was performed during analysis.',
         'viewports':viewports,'input_hashes':inputs,'outlier_rows':outliers,'failed_guard_ipc_rows':{g['action']:outliers[g['action']] for g in failed},
         'target':{'ms':250,'B_actions_p95_pass':all(metrics['B'][a]['measurement']['p95_ms']<250 for a in score.ACTIONS),'B_actions_max_pass':all(metrics['B'][a]['measurement']['max_ms']<250 for a in score.ACTIONS),'B_fresh_open_p95_pass':metrics['B']['open']['measurement']['p95_ms']<250,'full_goal_met':False},
         'interpretation':['A1 Open1354.2ms retained; Openmedian improves only4.67%, with process2/3 pair gains about5–7%. Do not call the47% primary worst-p95 drop a steady Open gain.','Independent final20 branch-group p95 gain20.85% supplies frozen corroboration; source changes only Linux branch summaries.','Observed WT/WT-comment gains are retained but are not isolated causal evidence for the branch-summary edit.','Foreground coverage is the union of completed recorded native intervals; remainder includes UI, frames, waits, scheduling and unrecorded work, not paint-only.','This valid single-cell result supports retaining a4 for further matrix/integration verification, not promotion or full-goal completion.']}
(RUN/'ipc-samples.json').write_text(json.dumps(rows,indent=2)+'\n');(RUN/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['The primary a4 series is valid and passes its frozen one-cell qualification. Keep the candidate for further verification; do not promote from this cell alone.','',
'All six serial fresh processes and318 samples pass canonical content/comment correctness, startup readiness, exact source/binary identities, both-fixture guards and recorded app/child cleanup. The private master received exit acknowledgement0 and exited255; its socket is absent and host port19223 was recorded free. Exact master/controller identities are absent now. No VM inventory or new port check ran during this analysis.','',
f"Open A: {' / '.join(f'{x:.1f}' for x in metrics['A']['open']['first_use_by_process_ms'])} ms; B: {' / '.join(f'{x:.1f}' for x in metrics['B']['open']['first_use_by_process_ms'])} ms. A1 remains an outlier. Openmedian {open_median['A']:.1f}→{open_median['B']:.1f}ms improves{-change(open_median['A'],open_median['B']):.2f}%, below10%. Process2/3 pair improvements are {summary['steady_open_pairs_process2and3'][0]['change_percent']:.2f}% and{summary['steady_open_pairs_process2and3'][1]['change_percent']:.2f}%. These are fresh-process observations, not OS-cold.",'',
f"Worst p95 {worst['A']:.1f}→{worst['B']:.1f}ms passes the10% primary gate, but is dominated by A1 Open. Independent branch-group worst p95 {branch['A']:.1f}→{branch['B']:.1f}ms improves{-change(branch['A'],branch['B']):.2f}%, so corroboration passes through branch interactions rather than Openmedian. Every final20 action p95/max and freshOpenmedian/p95/max10% guard passes. There are no failed guards to waive.",'',
'Canonical nearest-rank p50/p95/max below use all3 Opens or the final20 action samples including first use. Strict repeated19, all-series26 and every first-use value remain in summary.json; no sample is removed.','',
'| Action | A p50/p95/max ms | B p50/p95/max ms | p95 change | max change |','|---|---:|---:|---:|---:|']
for action in actions:
    a=metrics['A'][action]['measurement'];b=metrics['B'][action]['measurement'];fmt=lambda x:f"{x['p50_ms']:.1f}/{x['p95_ms']:.1f}/{x['max_ms']:.1f}"
    lines.append(f"| {action} | {fmt(a)} | {fmt(b)} | {change(a['p95_ms'],b['p95_ms']):+.2f}% | {change(a['max_ms'],b['max_ms']):+.2f}% |")
lines+=['','All B final20 action p95/max values are below250ms. Fresh Open remains665–715ms and fails the goal. The other matrix cells, cold scenarios and final delivered-source acceptance remain incomplete.','','First use by fresh process1/2/3:','','| Action | A first-use ms | B first-use ms |','|---|---:|---:|']
for action in actions:lines.append('| '+action+' | '+' / '.join(f'{x:.1f}' for x in metrics['A'][action]['first_use_by_process_ms'])+' | '+' / '.join(f'{x:.1f}' for x in metrics['B'][action]['first_use_by_process_ms'])+' |')
lines+=['','Foreground IPC coverage is the union of completed intervals. Remainder includes UI handling, rendering, frames, scheduling and unrecorded work; it is not paint-only. Figures use the same sample scope as the first table.','','| Action | A foreground p50/p95/max | B foreground p50/p95/max | A remainder p50/p95/max | B remainder p50/p95/max |','|---|---:|---:|---:|---:|']
for action in actions:
    fmt=lambda x:f"{x['p50_ms']:.1f}/{x['p95_ms']:.1f}/{x['max_ms']:.1f}"
    lines.append('| '+action+' | '+' | '.join(fmt(ipc[v][action][key]) for key in ['foreground_ipc_union_ms','non_foreground_ipc_remainder_ms'] for v in ['A','B'])+' |')
lines+=['','ipc-samples.json retains all318 raw samples and exact relative foreground/background intervals, pending calls, unions and remainders. summary.json retains p95/max/near-p50 rows for every action and source process. No failed-guard rows exist in this run. Observed WT improvements are not isolated causal evidence for a branch-only edit.','','Decision: retain a4 as a qualified primary candidate for the remaining matrix and integration checks. No promotion, retry, VM action, tests or builds occurred during this host analysis. The250ms full goal remains unmet.']
(RUN/'decision.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'summary':str(RUN/'summary.json'),'sample_count':len(rows),'acceptance':accept,'summary_sha256':sha(RUN/'summary.json')}))
