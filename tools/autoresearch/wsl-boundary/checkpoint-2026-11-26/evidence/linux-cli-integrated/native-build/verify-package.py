#!/usr/bin/env python3
"""Verify a fresh input-tar extraction and real Git discovery before any SSH."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    base = Path(__file__).resolve().parent
    root = base.parents[3]
    sys.path.insert(0, str(root / 'tools/autoresearch/wsl-boundary'))
    from score import source_identity

    plan = json.loads((base / 'build-plan.json').read_text())
    archive = json.loads((base / 'input-tar.json').read_text())
    assert sha(base / archive['name']) == archive['sha256'], 'Input tar changed'
    for name, field in [('build-plan.json', 'build_plan_sha256'),
                        ('vm-build-supervisor.py', 'vm_supervisor_sha256'),
                        ('build-after-release.py', 'host_launcher_sha256'),
                        ('verify-package.py', 'host_verifier_sha256')]:
        assert sha(base / name) == archive[field], name
    assert sha(base / 'controls/workload.py') == plan['workload_sha256']
    assert plan['app_files'] == plan['source']['files'] and len(plan['app_files']) == 49
    records = []
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0')
    # source_identity invokes Git itself, so give it the same isolated environment.
    os.environ.clear()
    os.environ.update(environment)
    with tempfile.TemporaryDirectory(prefix='integrated-cli-package-') as directory:
        extraction = Path(directory)
        with tarfile.open(base / archive['name']) as packed:
            packed.extractall(extraction, filter='data')
        for name in ['build-plan.json', 'vm-build-supervisor.py', 'controls/workload.py']:
            assert (extraction / name).read_bytes() == (base / name).read_bytes(), name
        assert sha(extraction / 'controls/workload.py') == plan['workload_sha256']
        source = extraction / 'source'
        bundle = extraction / plan['bundle']['name']
        assert sha(bundle) == plan['bundle']['sha256']
        assert plan['bundle']['self_contained'] is True
        assert not (source / '.git').exists()
        for name, digest in plan['snapshot_files'].items():
            assert sha(source / name) == digest, name

        def git(*arguments):
            command = ['git', *arguments]
            result = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True)
            records.append({'argv': command, 'exit': result.returncode,
                            'stdout': result.stdout, 'stderr': result.stderr})
            assert result.returncode == 0, records[-1]
            return result.stdout.strip()

        git('init', '--quiet', str(source))
        git('bundle', 'verify', str(bundle))
        git('fetch', '--no-tags', str(bundle), 'HEAD')
        fetched = git('rev-parse', 'FETCH_HEAD')
        assert fetched == plan['source']['git_head'], 'Bundle fetched another commit'
        git('update-ref', '--no-deref', 'HEAD', fetched)
        git('read-tree', 'HEAD')
        head = git('rev-parse', 'HEAD')
        tree = git('rev-parse', 'HEAD^{tree}')
        assert head == plan['source']['git_head'] and tree == plan['bundle']['git_tree']
        assert not (source / '.git/objects/info/alternates').exists()
        actual = source_identity(source)
        assert len(actual['files']) == 49 and actual == plan['source'], 'Canonical app source differs'
        assert os.access(source / 'build.sh', os.X_OK), 'build.sh lost its executable mode'
        for name, digest in plan['snapshot_files'].items():
            assert sha(source / name) == digest, name
    proof = {'status': 'host-extract-git-discovery-and-source-passed',
             'archive_sha256': archive['sha256'], 'bundle_sha256': plan['bundle']['sha256'],
             'git_head': head, 'git_tree': tree, 'canonical_app_files': len(actual['files']),
             'source_hash': actual['source_hash'], 'all_snapshot_files_unchanged': True,
             'snapshot_file_count': len(plan['snapshot_files']), 'external_alternates': False,
             'build_sh_executable': True, 'workload_control_sha256': plan['workload_sha256'],
             'commands': records, 'vm_calls': False, 'builds_tests_or_scoring': False}
    (base / 'package-verification.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({key: proof[key] for key in
                      ['status', 'archive_sha256', 'source_hash', 'canonical_app_files']}))


if __name__ == '__main__':
    main()
