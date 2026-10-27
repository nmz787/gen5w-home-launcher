#!/usr/bin/env python3
"""Check native reconstructed configurable DEX and reject deliberate changes."""
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
    parser.add_argument('--native-dir', type=Path, required=True,
                        help='Directory containing NAME-compiled.dex reconstructed outputs')
    parser.add_argument('--framework-dir', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--dexlib-libs', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    native = args.native_dir.resolve()
    out = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='native-configurable-verifier-tests-'))
    if out.exists() and any(out.iterdir()):
        raise RuntimeError('Test output directory must be fresh or empty')
    out.mkdir(parents=True, exist_ok=True)
    classes = out / 'java-classes'
    classes.mkdir()
    cp = os.pathsep.join(map(str, sorted(args.dexlib_libs.resolve().rglob('*.jar'))))
    java = args.java_home.resolve() / 'bin/java'
    javac = args.java_home.resolve() / 'bin/javac'
    names = ('Launcher_WP3', 'HKMC_HomeSetting_WP')
    inputs = [path for name in names for path in (build / (name + '-patched.dex'), native / (name + '-compiled.dex'))]
    hashes = {str(path): sha(path) for path in inputs}
    results = []

    def run(command, label, expected_error=None):
        result = subprocess.run(list(map(str, command)), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (label + '.log')).write_text(result.stdout)
        passed = result.returncode == 0 if expected_error is None else result.returncode != 0 and expected_error in result.stdout
        results.append({'test': label, 'passed': passed, 'returncode': result.returncode,
                        'expected_error': expected_error, 'log': label + '.log'})
        if not passed:
            raise AssertionError(label + ' failed:\n' + result.stdout[-6000:])
        print(label + ': passed', flush=True)

    run([javac, '-cp', cp, '-d', classes, ROOT / 'VerifyCompiledConfigurableLauncher.java',
         ROOT / 'MutateConfigurableLauncher.java'], 'compile-tests')
    java_command = [java, '-Xmx2g', '-cp', str(classes) + os.pathsep + cp]

    def verify(name, actual, label, error=None):
        run([*java_command, 'VerifyCompiledConfigurableLauncher', build / (name + '-patched.dex'),
             actual, args.framework_dir.resolve()], label, error)

    for name in names:
        verify(name, native / (name + '-compiled.dex'), 'baseline-' + name)
    cases = [
        ('oem-instruction', 'Unexpected native change outside compiled helper namespace'),
        ('helper-instruction', 'Native instruction inventory changed'),
        ('helper-flags', 'Unexpected helper native class access flags'),
    ]
    for mode, error in cases:
        name = 'Launcher_WP3'
        mutant = out / (mode + '.dex')
        run([*java_command, 'MutateConfigurableLauncher', native / (name + '-compiled.dex'), mutant, mode], 'mutate-' + mode)
        verify(name, mutant, 'reject-' + mode, error)
    assert hashes == {str(path): sha(path) for path in inputs}, 'Test altered a build input'
    report = {'scope': 'Host native-reconstruction structural verification; no device operations',
              'inputs': hashes, 'sources': {str(path): sha(path) for path in
                  (Path(__file__), ROOT / 'MutateConfigurableLauncher.java', ROOT / 'VerifyCompiledConfigurableLauncher.java')},
              'tests': results, 'passed': all(item['passed'] for item in results)}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Evidence: ' + str(out / 'results.json'))


if __name__ == '__main__':
    main()
