#!/usr/bin/env python3
"""Combine the four completed integrated cells; never launch or repeat a measurement."""
from pathlib import Path
import hashlib
import json
import math
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'evaluation-controls'
sys.path.insert(0, str(ROOT / 'tools/autoresearch/wsl-boundary'))
import score

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
protocol_path = OUT / 'protocol.json'
protocol = json.loads(protocol_path.read_text())
paths = [OUT / 'windows/run-20261126T010119508886Z',
         OUT / 'wsl_windows/run-20261126T011418639510Z',
         OUT / 'wsl_linux/run-20261126T012713558173Z']
cases = ('windows_linux', 'windows_windows', 'wsl_windows', 'wsl_linux')
actions = ('open', *score.ACTIONS)
rows = []
cell_reports = {}
inputs = {str(protocol_path): sha(protocol_path)}
processes = []
transports = []


def stats(values):
    values = list(values)
    assert values and all(math.isfinite(v) for v in values)
    return {'count': len(values), 'p50_ms': score.percentile(values, .5),
            'median_ms': statistics.median(values), 'p95_ms': score.percentile(values, .95), 'max_ms': max(values)}


for path in paths:
    summary_path, ipc_path = path / 'summary.json', path / 'ipc-samples.json'
    summary = json.loads(summary_path.read_text())
    assert summary['source_hash'] == protocol['source_hash'] and summary['git_head'] == protocol['git_head']
    assert summary['contract_sha256'] == protocol['contract_sha256'] == score.contract_identity()['sha256']
    assert summary['fixture_before'] == summary['fixture_after'] and not summary['qualification']['promoted']
    assert all(sha(p) == expected for p, expected in summary['input_hashes'].items())
    incoming = json.loads(ipc_path.read_text())
    assert len(incoming) == summary['sample_count']
    rows.extend(incoming)
    for case in sorted({row['case'] for row in incoming}):
        assert case not in cell_reports
        cell_reports[case] = {'summary': str(summary_path), 'summary_sha256': sha(summary_path),
                              'state': summary['state'], 'state_sha256': summary['state_sha256'],
                              'fixture_sha256': summary['fixture_sha256'], 'variants': summary['variants'],
                              'metrics': summary['metrics'][case] if 'case' not in summary else summary['metrics']}
    for actor in summary['exact_host_controller_and_master_absent_now']:
        current = Path('/proc') / str(actor['pid']) / 'stat'
        ticks = current.read_text().rsplit(') ', 1)[1].split()[19] if current.exists() else None
        assert ticks != actor['start_ticks']
    assert all(p['valid'] and p['cleanup']['exact_owned_processes_absent'] and p['cleanup']['ports_free']
               for p in summary['processes_and_cleanup'])
    processes.extend(summary['processes_and_cleanup'])
    transports.append({'summary': str(summary_path), 'transport_cleanup': summary['transport_cleanup'],
                       'exact_host_actors_absent_now': summary['exact_host_controller_and_master_absent_now']})
    inputs[str(summary_path)] = sha(summary_path)
    inputs[str(ipc_path)] = sha(ipc_path)

assert set(cell_reports) == set(cases) and len(rows) == 1272 and len(processes) == 24
assert len({(r['case'], r['variant'], r['process_number'], r['action'], r['repetition']) for r in rows}) == 1272
assert all(r['correct'] and r['foreground_ipc_union_ms'] <= r['elapsed_ms'] + .001 for r in rows)
metrics, ipc, selections, guards = {}, {}, {}, {}
for case in cases:
    metrics[case], ipc[case], selections[case], guards[case] = {}, {}, {}, []
    for variant in ('A', 'B'):
        metrics[case][variant], ipc[case][variant] = {}, {}
        for action in actions:
            all_rows = [r for r in rows if r['case'] == case and r['variant'] == variant and r['action'] == action]
            measured = all_rows if action == 'open' else [r for r in all_rows if r['process_number'] == 3]
            strict = [r for r in measured if r['phase'] == 'repeated']
            first = [r for r in all_rows if r['repetition'] == 0]
            assert len(all_rows) == (3 if action == 'open' else 26)
            assert len(measured) == (3 if action == 'open' else 20) and len(first) == 3
            if action != 'open':
                assert len(strict) == 19
            metric = {'measurement': stats(r['elapsed_ms'] for r in measured),
                      'strict_repeated19': stats(r['elapsed_ms'] for r in strict) if strict else None,
                      'all_series': stats(r['elapsed_ms'] for r in all_rows),
                      'first_use_by_process_ms': [r['elapsed_ms'] for r in first]}
            assert metric == cell_reports[case]['metrics'][variant][action]
            metrics[case][variant][action] = metric
            ipc[case][variant][action] = {scope: {key: stats(r[key] for r in selected) for key in (
                'elapsed_ms', 'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms', 'after_last_foreground_ipc_ms')}
                if selected else None for scope, selected in (
                    ('measurement', measured), ('strict_repeated19', strict), ('all_series', all_rows), ('first_use', first))}
            ordered = sorted(measured, key=lambda r: r['elapsed_ms'])
            n = len(ordered)
            selections[case].setdefault(action, {})[variant] = {key: ordered[index] for key, index in (
                ('near_p50', math.ceil(n * .5) - 1), ('p95', math.ceil(n * .95) - 1), ('max', n - 1))}
    for action in actions:
        a, b = metrics[case]['A'][action]['measurement'], metrics[case]['B'][action]['measurement']
        for key in (('median_ms', 'p95_ms') if case in ('windows_windows', 'wsl_linux') else ('p95_ms',)):
            guards[case].append({'action': action, 'metric': key, 'A_ms': a[key], 'B_ms': b[key],
                                 'change_percent': (b[key] / a[key] - 1) * 100, 'limit_ratio': 1.1, 'pass': b[key] <= 1.1 * a[key]})
failed = {case: [g for g in guards[case] if not g['pass']] for case in cases}
branch_group = ('branch_first', 'branch_final', 'stack', 'comment_branch')
primary = {v: max(metrics['windows_linux'][v][a]['measurement']['p95_ms'] for a in branch_group) for v in ('A', 'B')}
gain = (1 - primary['B'] / primary['A']) * 100
gain_pass = primary['B'] <= .9 * primary['A']
qualified = gain_pass and not any(failed.values())
details = []
for case in cases:
    for guard in failed[case]:
        selected = selections[case][guard['action']]
        a, b = selected['A']['p95'], selected['B']['p95']
        details.append({'case': case, 'guard': guard, 'A_p95_row': a, 'B_p95_row': b,
                        'B_minus_A_at_p95_rows': {k: b[k] - a[k] for k in (
                            'elapsed_ms', 'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms')},
                        'A_max_row': selected['A']['max'], 'B_max_row': selected['B']['max']})
target = {case: {action: {'p95_ms': metrics[case]['B'][action]['measurement']['p95_ms'],
                         'p95_under250': metrics[case]['B'][action]['measurement']['p95_ms'] < 250,
                         'first_use_by_process_ms': metrics[case]['B'][action]['first_use_by_process_ms'],
                         'all_first_use_under250': all(v < 250 for v in metrics[case]['B'][action]['first_use_by_process_ms'])}
                 for action in actions} for case in cases}
summary = {'status': 'complete valid integrated matrix; ' + ('qualified for further verification' if qualified else 'failed frozen acceptance'),
           'source_hash': protocol['source_hash'], 'git_head': protocol['git_head'], 'contract_sha256': protocol['contract_sha256'],
           'protocol': protocol, 'sample_count': 1272, 'valid_runs': 24, 'old_pilot_samples_pooled': False,
           'cell_reports': cell_reports, 'metrics': metrics, 'foreground_ipc_union_and_remainder_by_scope': ipc,
           'qualification': {'primary_branch_group_worst_p95_ms': primary, 'primary_branch_group_improvement_percent': gain,
                             'primary_branch_gain_10percent_pass': gain_pass, 'per_case_guards': guards, 'failed_guards': failed,
                             'full_matrix_complete': True, 'optimization_qualified': qualified, 'promoted': False},
           'target250': target, 'failed_guard_ipc_details': details, 'retained_max_p95_near_p50_rows': selections,
           'processes_and_cleanup': processes, 'transport_cleanup': transports, 'input_hashes': inputs,
           'interpretation': ['All24 fresh processes and1272 raw samples are valid. All recorded fixture/content/comment/identity/cleanup gates pass.',
                              'Open3, full20, strict19, all-series26 and first-use observations remain distinct. Fresh processes are not OS-cold. No OS cache flush occurred.',
                              'Each cell keeps its own controls. No old pilot samples are pooled. The failed primary gain and all failed cell guards remain failures.',
                              'Foreground intervals are unions. The remainder includes UI, frames, waits and unrecorded work. It is not pure paint.',
                              'No sample removal, retries, waivers or noise/source/antivirus causality claims. Maxima are retained without adding a new hard maximum gate.',
                              'This report changes no source, production artifacts, frozen scorer, fixtures or acceptance rules. The full250ms goal is not completed.']}
(OUT / 'ipc-samples.json').write_text(json.dumps(rows, indent=2) + '\n')
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
fmt = lambda s: f"{s['p50_ms']:.1f}/{s['p95_ms']:.1f}/{s['max_ms']:.1f}"
lines = ['All four integrated matrix cells are valid. The candidate fails frozen acceptance and remains unpromoted.', '',
         f"The primary branch-group worst p95 is {primary['A']:.1f}→{primary['B']:.1f}ms, a {gain:.2f}% improvement. The frozen requirement is at least10%. No older b2/a4 pilot observations are pooled.", '',
         'All24 fresh processes and1,272 samples pass recorded source/binary/content/comment/fixture and exact actor cleanup gates. Private mux exit acknowledgements, terminal statuses, absent sockets and recorded task-owned port checks pass. This aggregation uses local saved records only.', '']
for case in cases:
    lines += [case, '', 'Open by fresh process1/2/3: A ' + ' / '.join(f'{v:.1f}' for v in metrics[case]['A']['open']['first_use_by_process_ms']) + 'ms; B ' + ' / '.join(f'{v:.1f}' for v in metrics[case]['B']['open']['first_use_by_process_ms']) + 'ms.', '',
              '| Action | A p50/p95/max ms | B p50/p95/max ms | median change | p95 change |', '|---|---:|---:|---:|---:|']
    for action in actions:
        a, b = metrics[case]['A'][action]['measurement'], metrics[case]['B'][action]['measurement']
        lines.append(f"| {action} | {fmt(a)} | {fmt(b)} | {(b['median_ms'] / a['median_ms'] - 1) * 100:+.2f}% | {(b['p95_ms'] / a['p95_ms'] - 1) * 100:+.2f}% |")
    lines += ['', 'Failed frozen guards: ' + ('; '.join(f"{g['action']} {g['metric']} {g['change_percent']:+.2f}%" for g in failed[case]) or 'none') + '.', '']
lines += ['Exact p95 order-statistic rows for failed guards follow. These rows are not paired requests. Each maximum and all foreground/background intervals remain in the JSON reports.', '',
          '| Case/action/guard | A total/FG/remainder | B total/FG/remainder | Delta total/FG/remainder |', '|---|---:|---:|---:|']
for detail in details:
    triple = lambda r: '/'.join(f'{r[k]:.1f}' for k in ('elapsed_ms', 'foreground_ipc_union_ms', 'non_foreground_ipc_remainder_ms'))
    lines.append('| ' + detail['case'] + '/' + detail['guard']['action'] + '/' + detail['guard']['metric'] + ' | ' + triple(detail['A_p95_row']) + ' | ' + triple(detail['B_p95_row']) + ' | ' + triple(detail['B_minus_A_at_p95_rows']) + ' |')
lines += ['', 'The JSON includes Open3, full20, strict repeated19, all-series26, first-use values and all-scope native foreground/remainder statistics. No observations are dropped and no new hard maximum gate is introduced. The remainder is not pure paint. No timing cause is inferred.', '',
          'Decision: reject this integrated candidate for promotion. Preserve its isolated source, proofs and measurements. Do not change the frozen acceptance rules or replace controls with the older successful pilot. The full250ms cross-boundary goal remains unmet.']
(OUT / 'decision.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'summary': str(OUT / 'summary.json'), 'summary_sha256': sha(OUT / 'summary.json'), 'samples': len(rows),
                  'primary_gain_percent': gain, 'failed_guards': {case: [g['action'] + '/' + g['metric'] for g in failed[case]] for case in cases},
                  'optimization_qualified': qualified, 'promoted': False}))
