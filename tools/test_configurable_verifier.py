#!/usr/bin/env python3
"""Exercise exact structural verification and deliberate corruptions; host only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--framework-dir', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--ghidra-home', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    if not any((build / name).is_file() for name in ('manifest.json', 'build-manifest.json')):
        raise RuntimeError('Require a completed build manifest before running tests')
    out = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='configurable-verifier-tests-'))
    if out.exists() and any(out.iterdir()):
        raise RuntimeError('Test output directory must be fresh or empty')
    out.mkdir(parents=True, exist_ok=True)
    jars = sorted(args.ghidra_home.resolve().rglob('*.jar'))
    cp = os.pathsep.join(map(str, jars))
    classes = out / 'java-classes'
    classes.mkdir()
    java = args.java_home.resolve() / 'bin/java'
    javac = args.java_home.resolve() / 'bin/javac'
    inputs = [build / 'classes.dex'] + [build / (name + suffix) for name in
        ('Launcher_WP3', 'HKMC_HomeSetting_WP') for suffix in ('-source.dex', '-patched.dex')]
    hashes = {str(path): sha(path) for path in inputs}
    results = []

    def run(command, name, expected_error=None):
        result = subprocess.run(list(map(str, command)), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (name + '.log')).write_text(result.stdout)
        passed = (result.returncode == 0) if expected_error is None else (result.returncode != 0 and expected_error in result.stdout)
        results.append({'test': name, 'passed': passed, 'returncode': result.returncode,
                        'expected_error': expected_error, 'log': name + '.log'})
        if not passed:
            raise AssertionError(name + ' failed:\n' + result.stdout[-5000:])
        print(name + ': passed', flush=True)

    run([javac, '-cp', cp, '-d', classes, ROOT / 'VerifyConfigurableLauncher.java',
         ROOT / 'MutateConfigurableLauncher.java'], 'compile-tests')
    java_command = [java, '-Xmx2g', '-cp', str(classes) + os.pathsep + cp]

    def verify(name, patched, helper, label, error=None):
        flags = ['--home-setting'] if name == 'HKMC_HomeSetting_WP' else []
        run([*java_command, 'VerifyConfigurableLauncher', build / (name + '-source.dex'),
             patched, helper, args.framework_dir.resolve(), *flags], label, error)

    for name in ('Launcher_WP3', 'HKMC_HomeSetting_WP'):
        verify(name, build / (name + '-patched.dex'), build / 'classes.dex', 'baseline-' + name)
    cases = [
        ('oem-instruction', 'Launcher_WP3', 'Unapproved change survives reversal'),
        ('helper-instruction', 'Launcher_WP3', 'Helper differs'),
        ('missing-click', 'Launcher_WP3', 'Expected exactly one launcher click dispatcher hook'),
        ('wrong-click-register', 'Launcher_WP3', 'Unapproved change survives reversal'),
        ('editor-click', 'HKMC_HomeSetting_WP', 'Dispatch hook outside audited launcher click handler'),
    ]
    for mode, name, error in cases:
        mutant = out / (mode + '.dex')
        run([*java_command, 'MutateConfigurableLauncher', build / (name + '-patched.dex'), mutant, mode], 'mutate-' + mode)
        verify(name, mutant, build / 'classes.dex', 'reject-' + mode, error)
    assert hashes == {str(path): sha(path) for path in inputs}, 'Test altered a build input'
    report = {'scope': 'Host structural verification; no device operations',
              'inputs': hashes, 'sources': {str(path): sha(path) for path in
                  (Path(__file__), ROOT / 'MutateConfigurableLauncher.java', ROOT / 'VerifyConfigurableLauncher.java')},
              'tests': results, 'passed': all(item['passed'] for item in results)}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Evidence: ' + str(out / 'results.json'))


if __name__ == '__main__':
    main()
