#!/usr/bin/env python3
"""Reconstruct and patch original physical launcher/editor for configurable tiles, host only.

Emits standard DEX compiler carriers, never device ODEXs or replacement OEM APKs.
All input hashes are checked against a completed read-only backup, and every
original class is independently checked after reversing only audited transforms.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/configurable'
PAIRS = ('Launcher_WP3', 'HKMC_HomeSetting_WP')
# Android 4.4 dexopt records the compiler carrier's classes.dex checksum in
# ODEX dependency metadata. Keep the APK entry metadata stable so a rebuild
# produces the same physical ODEX bytes, independent of host build time.
CARRIER_TIMESTAMPS = {
    'Launcher_WP3': (2026, 10, 26, 21, 22, 18),
    'HKMC_HomeSetting_WP': (2026, 10, 26, 21, 22, 28),
}
HELPER_JAR_TIMESTAMP = (2026, 10, 26, 21, 22, 8)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_inventory(backup):
    files = backup['files']
    if any('..' in PurePosixPath(n).parts for n in files):
        raise RuntimeError('Invalid backup source path')
    required = {'/system/build.prop'} | {
        '/system/app/' + name + suffix for name in PAIRS for suffix in ('.apk', '.odex')}
    if not required.issubset(files) or not any(
            n.startswith('/system/framework/') and n.endswith('.odex') for n in files):
        raise RuntimeError('Backup lacks launcher/editor or framework source inputs')
    return {n: files[n] for n in sorted(files) if n.startswith('/system/')}


def verify_inputs(directory, backup):
    if backup.get('complete') is not True or not backup.get('serial'):
        raise RuntimeError('Require a completed backup with an explicit source serial')
    files = source_inventory(backup)
    for name, expected in files.items():
        path = directory / name.lstrip('/')
        if not path.is_file() or path.is_symlink() or digest(path) != expected:
            raise RuntimeError('Captured source checksum mismatch: ' + name)
    archive = directory / 'backup.tar'
    if not archive.is_file() or digest(archive) != backup['archive_sha256']:
        raise RuntimeError('Backup archive checksum mismatch')
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--android-sdk', type=Path, default=os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT'))
    parser.add_argument('--dexlib-libs', required=True, type=Path,
                        help='Directory containing dexlib2/baksmali Java dependency JARs')
    parser.add_argument('--build-tools-version', default='36.0.0')
    args = parser.parse_args()
    if not args.java_home or not args.android_sdk:
        parser.error('Set --java-home and --android-sdk (or JAVA_HOME/ANDROID_HOME)')
    backup_dir = args.backup_dir.resolve()
    backup = json.loads((backup_dir / 'backup.json').read_text())
    source = verify_inputs(backup_dir, backup)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError('Use a fresh empty output directory to prevent stale artifacts')
    out.mkdir(parents=True, exist_ok=True)
    java = args.java_home.resolve() / 'bin/java'
    javac = args.java_home.resolve() / 'bin/javac'
    sdk = args.android_sdk.resolve()
    android = sdk / 'platforms/android-19/android.jar'
    bt = sdk / 'build-tools' / args.build_tools_version
    jars = sorted(args.dexlib_libs.resolve().rglob('*.jar'))
    if not any('dexlib' in p.name for p in jars):
        raise RuntimeError('DEX tooling classpath lacks dexlib2')
    classpath = os.pathsep.join(map(str, jars))
    environment = dict(os.environ, JAVA_HOME=str(args.java_home.resolve()))
    patch_paths = [ROOT / 'tools/build_configurable.py', ROOT / 'tools/VerifyConfigurableLauncher.java',
                   ROOT / 'examples/configurable/DeodexLauncher.java', EXAMPLE / 'PatchConfigurableLauncher.java',
                   *sorted((EXAMPLE / 'src').rglob('*.java'))]
    patches = {str(p.relative_to(ROOT)): digest(p) for p in patch_paths}
    toolchain_paths = [java, javac, android, bt / 'd8', bt / 'lib/d8.jar', *jars]
    toolchain = {str(p): digest(p) for p in toolchain_paths}
    manifest = {'_source': {'serial': backup['serial'], 'files': source},
                '_patches': patches, '_toolchain': toolchain,
                '_verification': {'runtime_tested': False,
                    'scope': 'Canonical class reversal, exact helper comparison, reflection contracts, Dalvik analysis; host only'}}

    def run(command, log):
        result = subprocess.run(list(map(str, command)), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=environment)
        (out / log).write_text(result.stdout)
        if result.returncode:
            raise RuntimeError('Command failed; see ' + str(out / log) + '\n' + result.stdout[-6000:])
        print(log + ': passed', flush=True)

    classes = out / 'helper-classes'
    classes.mkdir()
    run([javac, '-source', '8', '-target', '8', '-bootclasspath', android, '-d', classes,
         *sorted((EXAMPLE / 'src').rglob('*.java'))], 'helper-javac.log')
    with zipfile.ZipFile(out / 'helper.jar', 'w', zipfile.ZIP_STORED) as jar:
        for path in sorted(classes.rglob('*.class')):
            entry = zipfile.ZipInfo(str(path.relative_to(classes)), date_time=HELPER_JAR_TIMESTAMP)
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o664) << 16
            jar.writestr(entry, path.read_bytes())
    run([bt / 'd8', '--min-api', '19', '--lib', android, '--output', out,
         out / 'helper.jar'], 'helper-d8.log')
    framework = backup_dir / 'system/framework'
    for name in PAIRS:
        source_dex = out / (name + '-source.dex')
        patched = out / (name + '-patched.dex')
        run([java, '-Xmx2g', '-cp', classpath, ROOT / 'examples/configurable/DeodexLauncher.java',
             backup_dir / ('system/app/' + name + '.odex'), framework, source_dex], name + '-deodex.log')
        flags = ['--home-setting'] if name == 'HKMC_HomeSetting_WP' else []
        run([java, '-Xmx2g', '-cp', classpath, EXAMPLE / 'PatchConfigurableLauncher.java', source_dex,
             out / 'classes.dex', patched, *flags], name + '-patch.log')
        run([java, '-Xmx2g', '-cp', classpath, ROOT / 'tools/VerifyConfigurableLauncher.java',
             source_dex, patched, out / 'classes.dex', framework, *flags], name + '-verify.log')
        if patched.read_bytes()[:8] != b'dex\n035\0':
            raise RuntimeError('Expected API19-compatible DEX035')
        carrier = out / (name + '-preopt.apk')
        with zipfile.ZipFile(carrier, 'w', zipfile.ZIP_DEFLATED) as archive:
            entry = zipfile.ZipInfo('classes.dex', date_time=CARRIER_TIMESTAMPS[name])
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o664) << 16
            archive.writestr(entry, patched.read_bytes())
        for path in (source_dex, patched, carrier):
            manifest[path.name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
        manifest[carrier.name]['dex'] = patched.name
    # Detect source/source-tool changes while commands ran; publish only complete builds.
    if verify_inputs(backup_dir, backup) != source or any(digest(ROOT / p) != h for p, h in patches.items()):
        raise RuntimeError('Input or patch source changed during build')
    for name in ('classes.dex', 'helper.jar'):
        path = out / name
        manifest[name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    (out / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Physical-input carriers ready: ' + str(out), flush=True)
    print('No device compilation, installation, reboot, or runtime UI test performed.', flush=True)


if __name__ == '__main__':
    main()
