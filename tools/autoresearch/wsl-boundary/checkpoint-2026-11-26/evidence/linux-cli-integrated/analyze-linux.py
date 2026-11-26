#!/usr/bin/env python3
"""Analyze one completed integrated Linux GUI cell using only saved host records."""
from pathlib import Path
import hashlib
import json
import math
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'tools/autoresearch/wsl-boundary'))
import score

RUN = Path(sys.argv[1]).resolve()
STATE = RUN / 'state.json'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
state = json.loads(STATE.read_text())
protocol_path = HERE / 'evaluation-controls/protocol.json'
protocol = json.loads(protocol_path.read_text())
case = state['case']
assert case in ('wsl_windows', 'wsl_linux') and RUN.parent.name == case
assert state['status'] == 'complete-valid-awaiting-10percent-review'
assert state['acceptance'] == protocol and not state['old_samples_pooled']
assert state['fixture_before'] == state['fixture_after']
assert state['contract_sha256'] == score.contract_identity()['sha256'] == protocol['contract_sha256']
assert state['variants']['B']['source_hash'] == protocol['source_hash']
assert [(r['variant'], r['number'], r['repetitions']) for r in state['runs']] == [
    ('A', 1, 3), ('B', 1, 3), ('A', 2, 3), ('B', 2, 3), ('A', 3, 20), ('B', 3, 20)]

inputs = {}
rows = []
processes = []
actions = ('open', *score.ACTIONS)


def read(path):
    path = Path(path)
    inputs[str(path)] = sha(path)
    return json.loads(path.read_text())


def stats(values):
    values = list(values)
    assert values and all(math.isfinite(v) for v in values)
    return {'count': len(values), 'p50_ms': score.percentile(values, .5),
            'median_ms': statistics.median(values), 'p95_ms': score.percentile(values, .95),
            'max_ms': max(values)}


def union(calls, total):
    intervals = []
    for a, b in sorted((max(0, c['start_ms']), min(total, c['start_ms'] + c['elapsed_ms']))
                       for c in calls if c.get('elapsed_ms') is not None):
        if b <= a:
            continue
        if intervals and a <= intervals[-1][1]:
            intervals[-1][1] = max(b, intervals[-1][1])
        else:
            intervals.append([a, b])
    return intervals


for run in state['runs']:
    version = state['variants'][run['variant']]
    verdict = read(run['verdict'])
    launch = read(run['record'])
    source = read(Path(run['run_dir']) / 'source.json')
    cleanup_path = Path(run['cleanup_log'])
    inputs[str(cleanup_path)] = sha(cleanup_path)
    cleanup = json.loads(cleanup_path.read_text().strip().splitlines()[-1])
    assert run['status'] == 'complete-valid-stopped' and run['cleanup_complete']
    assert run['score_exit'] == run['supervisor_exit'] == 0
    assert verdict['valid'] and verdict['case'] == case and verdict['repetitions'] == run['repetitions']
    assert verdict['contract']['sha256'] == state['contract_sha256']
    assert verdict['source_hash'] == version['source_hash'] and verdict['binary_sha256'] == version['binary_sha256']
    assert launch == run['launch'] == verdict['launch']
    assert launch['source_hash'] == version['source_hash'] and launch['binary_sha256'] == version['binary_sha256']
    assert launch['binary'] == version['binary'] and launch['profile'] == state['profile']
    assert launch['pid'] == launch['app_process']['pid'] and launch['created'] == launch['app_process']['start_ticks']
    assert source == score.source_identity(version['source']) and source['source_hash'] == version['source_hash']
    assert cleanup['exact_owned_processes_absent'] and cleanup['ports_free'] and cleanup['host_wrapper_absent_from_vm_environment']
    assert all(any(a['pid'] == wanted['pid'] and a['start_ticks'] == wanted['start_ticks']
                   for a in cleanup['observed_identities']) for wanted in [launch['app_process'], launch['driver_process']])
    sample_path = Path(run['samples'])
    inputs[str(sample_path)] = sha(sample_path)
    raw = [json.loads(line) for line in sample_path.read_text().splitlines()]
    score.validate_samples(raw, run['repetitions'])
    assert score.summarize(raw, run['repetitions'])['actions'] == verdict['actions']
    for sample in raw:
        assert sample['phase'] == ('fresh_process' if sample['action'] == 'open' else 'first_use' if sample['repetition'] == 0 else 'repeated')
        total = sample['elapsed_ms']
        fg = union(sample['ipc'], total)
        bg = union(sample.get('background_ipc', []), total)
        coverage = sum(b - a for a, b in fg)
        assert fg and all(c['start_ms'] >= 0 and c['start_ms'] + c['elapsed_ms'] <= total + .001 for c in sample['ipc'])
        rows.append({**sample, 'case': case, 'variant': run['variant'], 'process_number': run['number'],
                     'foreground_union_intervals_ms': fg, 'foreground_ipc_union_ms': coverage,
                     'non_foreground_ipc_remainder_ms': total - coverage,
                     'after_last_foreground_ipc_ms': total - max(b for a, b in fg),
                     'completed_background_union_ms': sum(b - a for a, b in bg),
                     'pending_background_count': sum(c.get('elapsed_ms') is None for c in sample.get('background_ipc', [])),
                     'source_samples': str(sample_path)})
    processes.append({'case': case, 'variant': run['variant'], 'number': run['number'], 'repetitions': run['repetitions'],
                      'launch': launch, 'verdict': run['verdict'], 'cleanup': cleanup,
                      'supervisor_exit': run['supervisor_exit'], 'host_supervisor_pid': run['host_supervisor_pid'], 'valid': True})

assert len(rows) == 318
assert state['master_check']['exit'] == state['master_exit_request']['exit'] == 0
assert state['master_exit'] == 255 and state['control_socket_absent'] and state['host_port_free']
master = state['master']
assert '-M' in master['argv'] and master['socket'] in master['argv']
assert f"127.0.0.1:{state['ports']['host']}:127.0.0.1:{state['ports']['driver']}" in master['argv']
assert not Path(master['socket']).exists()
actors = []
for actor in (state, master):
    path = Path('/proc') / str(actor['pid']) / 'stat'
    current = path.read_text().rsplit(') ', 1)[1].split()[19] if path.exists() else None
    assert current != actor['start_ticks']
    actors.append({'pid': actor['pid'], 'start_ticks': actor['start_ticks'],
                   'exact_owned_actor_absent_now': True, 'current_start_ticks': current})

metrics = {}
ipc = {}
selections = {}
for variant in ('A', 'B'):
    metrics[variant] = {}
    ipc[variant] = {}
    for action in actions:
        all_rows = [r for r in rows if r['variant'] == variant and r['action'] == action]
        measured = all_rows if action == 'open' else [r for r in all_rows if r['process_number'] == 3]
        strict = [r for r in measured if r['phase'] == 'repeated']
        metrics[variant][action] = {'measurement': stats(r['elapsed_ms'] for r in measured),
                                    'strict_repeated19': stats(r['elapsed_ms'] for r in strict) if strict else None,
                                    'all_series': stats(r['elapsed_ms'] for r in all_rows),
                                    'first_use_by_process_ms': [r['elapsed_ms'] for r in all_rows if r['repetition'] == 0]}
        ipc[variant][action] = {k: stats(r[k] for r in measured) for k in (
            'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms', 'after_last_foreground_ipc_ms')}
        ops = {}
        for row in measured:
            for call in row['ipc']:
                ops.setdefault(call['command'] + '/' + call.get('op', ''), []).append(call['elapsed_ms'])
        ipc[variant][action]['by_command_and_op'] = {k: stats(v) for k, v in ops.items()}
        ordered = sorted(measured, key=lambda r: r['elapsed_ms'])
        n = len(ordered)
        selections.setdefault(action, {})[variant] = {k: ordered[i] for k, i in (
            ('near_p50', math.ceil(n * .5) - 1), ('p95', math.ceil(n * .95) - 1), ('max', n - 1))}

guards = []
for action in actions:
    a = metrics['A'][action]['measurement']
    b = metrics['B'][action]['measurement']
    for key in (('median_ms', 'p95_ms') if case == 'wsl_linux' else ('p95_ms',)):
        guards.append({'action': action, 'metric': key, 'A_ms': a[key], 'B_ms': b[key],
                       'change_percent': (b[key] / a[key] - 1) * 100, 'limit_ratio': 1.1, 'pass': b[key] <= 1.1 * a[key]})
failed = [g for g in guards if not g['pass']]
failed_details = []
for guard in failed:
    selected = selections[guard['action']]
    a, b = selected['A']['p95'], selected['B']['p95']
    failed_details.append({'case': case, 'guard': guard, 'A_p95_row': a, 'B_p95_row': b,
                           'B_minus_A_at_p95_rows': {k: b[k] - a[k] for k in (
                               'elapsed_ms', 'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms')},
                           'A_max_row': selected['A']['max'], 'B_max_row': selected['B']['max']})
inputs[str(STATE)] = sha(STATE)
inputs[str(protocol_path)] = sha(protocol_path)
summary = {'status': 'valid completed Linux GUI cell; no promotion', 'case': case,
           'scope': 'One integrated matrix cell only. Other cells and the old b2/a4 pilot are not pooled.',
           'source_hash': protocol['source_hash'], 'git_head': protocol['git_head'], 'state': str(STATE),
           'state_sha256': sha(STATE), 'contract_sha256': state['contract_sha256'], 'fixture_sha256': state['fixture_sha256'],
           'valid_runs': 6, 'sample_count': 318, 'variants': state['variants'],
           'statistics': 'Canonical nearest-rank p50/p95 and conventional median. Full final20 includes first_use; strict repeated19 and all-series26 are separate. Open retains all3 fresh processes. No OS cache flush.',
           'metrics': metrics, 'foreground_ipc_union_and_remainder': ipc,
           'qualification': {'per_case_guards': guards, 'failed_guards': failed, 'observed_cell_guard_pass': not failed,
                             'primary_gain_assessed_in_this_cell': False, 'full_matrix_complete': False,
                             'optimization_qualified': False, 'promoted': False},
           'failed_guard_ipc_details': failed_details, 'retained_max_p95_near_p50_rows': selections,
           'processes_and_cleanup': processes, 'fixture_before': state['fixture_before'], 'fixture_after': state['fixture_after'],
           'transport_cleanup': {k: state[k] for k in ('master', 'master_check', 'master_exit_request', 'master_exit',
                                                       'control_socket_absent', 'host_port_free', 'host_wrapper')},
           'exact_host_controller_and_master_absent_now': actors, 'input_hashes': inputs,
           'interpretation': ['Every recorded source/content/comment/fixture/identity/cleanup gate passes. No VM calls or new port checks occurred during this analysis.',
                              'No waiver, sample removal, retry or timing-causality claim. The unchanged Windows execution policy does not waive reversed-cross guards.',
                              'Foreground intervals use a union. The remainder includes UI, frames, waits and unrecorded work; it is not pure paint.',
                              'This cell cannot override the failed primary-gain requirement or other failed cells. The full250ms goal remains unmet.']}
(RUN / 'ipc-samples.json').write_text(json.dumps(rows, indent=2) + '\n')
(RUN / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
fmt = lambda s: f"{s['p50_ms']:.1f}/{s['p95_ms']:.1f}/{s['max_ms']:.1f}"
lines = [f"{case} is valid. Its frozen {'same-side median and p95' if case == 'wsl_linux' else 'reversed-cross p95'} guards {'pass' if not failed else 'fail'}. Keep the integrated candidate unpromoted.", '',
         'All6 fresh processes and318 samples pass source/binary identity, native content/comment correctness, fixture and exact Linux app/driver/child cleanup checks. The private master received exit acknowledgement0 and exited255. Its socket is absent and the task-owned host port was recorded free. Exact host controller/master identities are absent now. This analysis made no VM calls, new port checks, retries, tests or builds.', '',
         'Open by fresh process1/2/3: A ' + ' / '.join(f'{v:.1f}' for v in metrics['A']['open']['first_use_by_process_ms']) + 'ms; B ' + ' / '.join(f'{v:.1f}' for v in metrics['B']['open']['first_use_by_process_ms']) + 'ms. No OS cache flush occurred.', '',
         '| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |', '|---|---:|---:|---:|---:|']
for action in actions:
    a, b = metrics['A'][action]['measurement'], metrics['B'][action]['measurement']
    lines.append(f"| {action} | {fmt(a)} | {fmt(b)} | {(b['median_ms'] / a['median_ms'] - 1) * 100:+.2f}% | {(b['p95_ms'] / a['p95_ms'] - 1) * 100:+.2f}% |")
lines += ['', 'Failed frozen guards: ' + ('; '.join(f"{g['action']} {g['metric']} {g['change_percent']:+.2f}%" for g in failed) or 'none') + '.', '',
          '| Action | A first-use ms | B first-use ms | A strict19 p50/p95/max | B strict19 p50/p95/max |', '|---|---:|---:|---:|---:|']
for action in actions:
    first = lambda v: ' / '.join(f'{x:.1f}' for x in metrics[v][action]['first_use_by_process_ms'])
    strict = lambda v: fmt(metrics[v][action]['strict_repeated19']) if action != 'open' else 'n/a'
    lines.append(f"| {action} | {first('A')} | {first('B')} | {strict('A')} | {strict('B')} |")
lines += ['', 'Foreground/remainder p50/p95/max ms use the same Open3/final20 scope. Foreground coverage is an interval union.', '',
          '| Action | A foreground | B foreground | A remainder | B remainder |', '|---|---:|---:|---:|---:|']
for action in actions:
    lines.append('| ' + action + ' | ' + ' | '.join(fmt(ipc[v][action][key]) for key in (
        'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms') for v in ('A', 'B')) + ' |')
lines += ['', 'Failed guard p95 rows are exact order-statistic samples, not paired requests. Maxima and all raw intervals remain in summary.json and ipc-samples.json.', '',
          '| Action | A p95 total/FG/remainder | B p95 total/FG/remainder | Delta total/FG/remainder |', '|---|---:|---:|---:|']
for detail in failed_details:
    triple = lambda row: '/'.join(f'{row[k]:.1f}' for k in ('elapsed_ms', 'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms'))
    lines.append('| ' + detail['guard']['action'] + ' | ' + triple(detail['A_p95_row']) + ' | ' + triple(detail['B_p95_row']) + ' | ' + triple(detail['B_minus_A_at_p95_rows']) + ' |')
lines += ['', 'The full20, strict repeated19, all-series maxima and all first-use observations remain separate. No outlier is removed and no new maximum gate is introduced. No OS, source, antivirus or noise cause is inferred. The reversed-cross results receive no waiver because the Windows execution policy is unchanged.', '',
          'The complete integrated matrix must still include the other cells. This result cannot override its failed Windows primary-gain requirement. The full250ms goal remains unmet.']
(RUN / 'decision.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'summary': str(RUN / 'summary.json'), 'summary_sha256': sha(RUN / 'summary.json'), 'sample_count': len(rows),
                  'failed_guards': failed, 'exact_host_actors_absent': actors, 'decision': 'no promotion'}))
