#!/usr/bin/env python3
"""Exact-physical-firmware launcher/editor compilation, checks and manual deployment."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import tarfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
AUDIO_TOOLS = ROOT.parent / 'gen5w-audio-shortcuts/tools'
sys.path.insert(0, str(AUDIO_TOOLS))
spec = importlib.util.spec_from_file_location('audio_transport', AUDIO_TOOLS / 'headunit-audio-adb.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)
import artifact_cache

HOME_TARGETS = ('/system/app/Launcher_WP3.odex', '/system/app/HKMC_HomeSetting_WP.odex')
HOME_APKS = ('/system/app/Launcher_WP3.apk', '/system/app/HKMC_HomeSetting_WP.apk')
PAIRS = (('Launcher_WP3-preopt.apk', 'Launcher_WP3-patched.odex'),
         ('HKMC_HomeSetting_WP-preopt.apk', 'HKMC_HomeSetting_WP-patched.odex'))
q = audio.quote
sha = audio.digest


def source_inventory(backup):
    files = backup['files']
    required = set(HOME_TARGETS + HOME_APKS + ('/system/build.prop',))
    required.update(n for n in files if n.startswith('/system/framework/') and
                    Path(n).suffix in {'.jar', '.odex'})
    if not required.issubset(files) or not any(n.startswith('/system/framework/') for n in required):
        raise RuntimeError('Backup lacks launcher/editor or framework source inputs')
    return {n: files[n] for n in sorted(files) if n.startswith('/system/')}


def read_build(build, backup, serial):
    manifest = json.loads((build / 'build-manifest.json').read_text())
    source = manifest.get('_source', {})
    if source.get('serial') != serial or source.get('files') != source_inventory(backup):
        raise RuntimeError('Build source inventory/serial differs from exact launcher backup')
    for carrier, _ in PAIRS:
        data = (build / carrier).read_bytes()
        if sha(data) != manifest[carrier]['sha256']:
            raise RuntimeError('Carrier checksum mismatch: ' + carrier)
        # Bind each compiler carrier to the exact recorded patched DEX.
        dex_name = manifest[carrier]['dex']
        if Path(dex_name).name != dex_name or sha((build / dex_name).read_bytes()) != manifest[dex_name]['sha256']:
            raise RuntimeError('Patched DEX checksum mismatch: ' + carrier)
        with zipfile.ZipFile(build / carrier) as archive:
            if sha(archive.read('classes.dex')) != manifest[dex_name]['sha256']:
                raise RuntimeError('Carrier DEX provenance mismatch: ' + carrier)
    return manifest


def identity(manifest, runtime):
    if runtime['sdk'] != '19' or not runtime['abi'].startswith('armeabi'):
        raise RuntimeError('Expected matching API 19 ARM runtime')
    for key in ('_source', '_patches', '_toolchain'):
        if not manifest.get(key):
            raise RuntimeError('Missing build provenance: ' + key)
    return {'schema': 1, 'targets': list(HOME_TARGETS), 'source': manifest['_source'],
            'patches': manifest['_patches'], 'toolchain': manifest['_toolchain'],
            'carriers': {n: manifest[n] for n, _ in PAIRS}, 'runtime': runtime}


def metadata_check(device, backup):
    enforcing = device.shell('getenforce 2>/dev/null; exit 0') == 'Enforcing'
    import re
    for target in HOME_TARGETS:
        meta = backup.get('metadata', {}).get(target, {})
        if (not re.fullmatch('[0-7]{3,4}', str(meta.get('mode', ''))) or
                not str(meta.get('uid', '')).isdigit() or not str(meta.get('gid', '')).isdigit()):
            raise RuntimeError('Invalid launcher rollback metadata: ' + target)
        if enforcing and not meta.get('context'):
            raise RuntimeError('Missing enforcing SELinux context: ' + target)


def check(device, backup, manifest=None, allow_modified=False):
    if device.shell('getprop ro.build.version.sdk') != '19':
        raise RuntimeError('Launcher workflow requires SDK 19')
    expected = source_inventory(backup)
    actual = device.hashes(expected)
    modified = dict(zip(HOME_TARGETS, [manifest[n]['sha256'] for _, n in PAIRS])) if allow_modified else {}
    for target, value in expected.items():
        if actual.get(target) not in {value, modified.get(target, value)}:
            raise RuntimeError('Live launcher firmware mismatch: ' + target)
    metadata_check(device, backup)
    return {t: actual[t] for t in HOME_TARGETS}


def compiled_check(device, build, manifest):
    for name, digest in manifest['_patches'].items():
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or sha(source.read_bytes()) != digest:
            raise RuntimeError('Current launcher patch source mismatch: ' + name)
    current = identity(manifest, artifact_cache.runtime(device))
    recorded = manifest.get('_compilation', {})
    if recorded.get('inputs') != current or recorded.get('cache_key') != artifact_cache.key(current):
        raise RuntimeError('Compiled launcher runtime/input provenance mismatch')
    for _, name in PAIRS:
        data = (build / name).read_bytes()
        if not data.startswith(b'dey\n') or sha(data) != manifest[name]['sha256']:
            raise RuntimeError('Compiled launcher ODEX checksum/header mismatch: ' + name)


def replace(device, sources, metadata, expected_before, expected_after):
    """Transaction fixed to the two home ODEXs; signed APKs are never staged."""
    if device.hashes(HOME_TARGETS) != expected_before:
        raise RuntimeError('Launcher targets changed immediately before replacement')
    bb = q(device.bb)
    tag = '.home-' + uuid.uuid4().hex
    lines = []
    for number, (target, source) in enumerate(zip(HOME_TARGETS, sources)):
        meta = metadata[target]
        old, new = target + tag + '-old', target + tag + '-new'
        lines += [f'{bb} cp -p {q(target)} {q(old)}', f'{bb} cmp {q(target)} {q(old)}',
                  f'R{number}=1', f'{bb} cp {q(source)} {q(new)}',
                  f'chown {q(str(meta["uid"]) + ":" + str(meta["gid"]))} {q(new)}',
                  f'chmod {q(meta["mode"])} {q(new)}']
        if meta.get('context'):
            lines += [f'chcon {q(meta["context"])} {q(new)}', f'chcon {q(meta["context"])} {q(old)}']
        lines += [f'{bb} cmp {q(source)} {q(new)}']
    rollback = '\n'.join(f'if [ \"$R{n}\" = 1 ]; then mv {q(t + tag + "-old")} {q(t)}; fi'
                         for n, t in enumerate(HOME_TARGETS))
    rw = '/system/xbin/nemesis remount rw' if device.nemesis else 'mount -o remount,rw /system'
    ro = '/system/xbin/nemesis remount ro' if device.nemesis else 'mount -o remount,ro /system'
    body = ('set -e\nR0=0\nR1=0\n' + rw + '\nrollback() {\n' + rollback + '\nsync\n}\n' +
            'trap \'r=$?; if [ "$r" != 0 ]; then rollback; fi; ' + ro + ' || { if [ "$r" = 0 ]; then echo "Replacement committed and verified; remount ro failed"; fi; r=2; }; exit "$r"\' 0\n' +
            '\n'.join(lines) + '\n' +
            '\n'.join(f'mv {q(t + tag + "-new")} {q(t)}' for t in HOME_TARGETS) + '\n' +
            '\n'.join(f'[ \"$({bb} sha256sum {q(t)} | {bb} cut -d \' \' -f 1)\" = {q(expected_after[t])} ]'
                      for t in HOME_TARGETS) + '\nsync\n')
    device.shell(body)
    if device.hashes(HOME_TARGETS) != expected_after:
        raise RuntimeError('Launcher replacement readback mismatch')
    print('Both home ODEXs replaced and verified. Reboot must be requested separately.')


def compile_pair(device, build, manifest):
    environment = identity(manifest, artifact_cache.runtime(device))
    for _, output in PAIRS:
        if (build / output).exists():
            raise RuntimeError('Use a fresh build directory; output exists: ' + output)
    remote = '/data/local/tmp/home-compile-' + uuid.uuid4().hex
    device.shell('set -e\nmkdir ' + remote + '\nchmod 755 ' + remote, unprivileged=True)
    shell = audio.Device(argparse.Namespace(adb=device.prefix[0], serial=device.serial, su=False, nemesis=False))
    shell.bb = device.bb
    logs = build / 'compile-logs'
    logs.mkdir(exist_ok=False)
    for carrier, output in PAIRS:
        shell.push(build / carrier, remote + '/' + carrier)
        log = shell.shell('/system/bin/dexopt --preopt ' + remote + '/' + carrier + ' ' +
                          remote + '/' + output + ' ' + artifact_cache.FLAGS)
        (logs / (output + '.log')).write_text(log + '\n')
        shell.download(remote + '/' + output, build / output)
        data = (build / output).read_bytes()
        if not data.startswith(b'dey\n'):
            raise RuntimeError('Not an ODEX output: ' + output)
        manifest[output] = {'sha256': sha(data), 'bytes': len(data)}
    manifest['_compilation'] = {'inputs': environment, 'cache_key': artifact_cache.key(environment)}
    (build / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Compiled launcher/editor in /data only. Nothing installed or rebooted.')


def rollback_kit(output, backup_dir, backup, build, manifest, busybox):
    """Create manually invoked recovery files, without an auto-execution descriptor."""
    from types import SimpleNamespace
    metadata_check(SimpleNamespace(shell=lambda command: 'Disabled'), backup)
    for _, name in PAIRS:
        data = (build / name).read_bytes()
        if not data.startswith(b'dey\n') or sha(data) != manifest[name]['sha256']:
            raise RuntimeError('Invalid compiled rollback counterpart: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    payload = output / 'payload'
    payload.mkdir()
    with tarfile.open(backup_dir / 'backup.tar') as archive:
        for target in HOME_TARGETS:
            data = archive.extractfile(target.lstrip('/')).read()
            if sha(data) != backup['files'][target]:
                raise RuntimeError('Rollback member checksum mismatch: ' + target)
            (payload / Path(target).name).write_bytes(data)
    (payload / 'busybox-armv7').write_bytes(busybox.read_bytes())
    (payload / 'unchanged.sha256').write_text(''.join(v + '  ' + n + '\n' for n, v in
        source_inventory(backup).items() if n not in HOME_TARGETS))
    (payload / 'payload.sha256').write_text(''.join(sha(p.read_bytes()) + '  ' + p.name + '\n'
        for p in sorted(payload.iterdir())))
    substitutions = {'BB_SHA': sha(busybox.read_bytes()),
                     'LIST_SHA': sha((payload / 'payload.sha256').read_bytes())}
    target_script = []
    context_checks = []
    for i, (target, (_, patched)) in enumerate(zip(HOME_TARGETS, PAIRS)):
        meta = backup['metadata'][target]
        substitutions.update({f'T{i}': target, f'O{i}': backup['files'][target],
                              f'P{i}': manifest[patched]['sha256'],
                              f'SNAPSHOT{i}_LABEL': (f'chcon {q(meta["context"])} \"$T{i}.home-before-$$\"'
                                                     if meta.get('context') else ':')})
        target_script += [f'cp "$PAYLOAD/{Path(target).name}" "$T{i}.home-restore-$$"',
                         f'chown {q(str(meta["uid"]) + ":" + str(meta["gid"]))} "$T{i}.home-restore-$$"',
                         f'chmod {q(meta["mode"])} "$T{i}.home-restore-$$"']
        if meta.get('context'):
            target_script += [f'chcon {q(meta["context"])} "$T{i}.home-restore-$$"']
        else:
            context_checks += ['[ "$(getenforce 2>/dev/null)" != Enforcing ] || fail "Missing SELinux context"']
        target_script += [f'check_hash "$T{i}.home-restore-$$" "$O{i}"']
    script = (Path(__file__).with_name('home-rollback.template.sh')).read_text()
    substitutions['PREPARE'] = '\n'.join(target_script)
    substitutions['CONTEXT_CHECKS'] = '\n'.join(context_checks)
    for key, value in substitutions.items():
        script = script.replace('@' + key + '@', value)
    (output / 'restore-home.sh').write_text(script)
    (output / 'README.txt').write_text('Manual home ODEX rollback. No auto-execution descriptor.\n'
        'Verify kit SHA256SUMS on a trusted host before use. Invoke from NEMESIS root manually:\n'
        'sh restore-home.sh --check (reads firmware and stages tool in /data only), then --restore.\n'
        'No reboot is sent. APKs and app data are preserved. Install home before MODE;\n'
        'rollback MODE first, then home. Changed framework dependencies block this kit.\n')
    (output / 'rollback-manifest.json').write_text(json.dumps({
        'serial': backup['serial'], 'backup_archive_sha256': backup['archive_sha256'],
        'original': {t: backup['files'][t] for t in HOME_TARGETS},
        'modified': dict(zip(HOME_TARGETS, [manifest[n]['sha256'] for _, n in PAIRS])),
        'metadata': {t: backup['metadata'][t] for t in HOME_TARGETS}}, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(sha(p.read_bytes()) + '  ' + str(p.relative_to(output)) + '\n'
        for p in sorted(output.rglob('*')) if p.is_file()))
    print('Manual rollback kit created:', output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['compile', 'check', 'install', 'restore', 'rollback-kit'])
    p.add_argument('--serial', required=True)
    p.add_argument('--adb', default='adb')
    p.add_argument('--nemesis', action='store_true')
    p.add_argument('--su', action='store_true')
    p.add_argument('--busybox-device')
    p.add_argument('--busybox-sha256')
    p.add_argument('--backup-dir', type=Path, required=True)
    p.add_argument('--build-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--busybox', type=Path, help='Host BusyBox for local rollback kit')
    args = p.parse_args()
    backup = audio.load_backup(args.backup_dir, args.serial)
    build = args.build_dir.resolve()
    manifest = read_build(build, backup, args.serial)
    if args.action == 'rollback-kit':
        if not args.output_dir or not args.busybox:
            p.error('rollback-kit requires --output-dir and --busybox')
        rollback_kit(args.output_dir, args.backup_dir, backup, build, manifest, args.busybox)
        return
    if not args.busybox_device or not args.busybox_sha256 or (args.nemesis and args.su):
        p.error('Requires verified --busybox-device/--busybox-sha256 and one privilege channel')
    device = audio.Device(args)
    device.ready()
    before = check(device, backup, manifest, allow_modified=args.action == 'restore')
    if args.action == 'compile':
        compile_pair(device, build, manifest)
        return
    compiled_check(device, build, manifest)
    if args.action == 'check':
        print('Launcher/editor backup, live firmware, metadata and compilation identities verified. Read-only checks.')
        return
    if args.action == 'install':
        outputs = [(name, build / name) for _, name in PAIRS]
        after = dict(zip(HOME_TARGETS, [manifest[name]['sha256'] for _, name in PAIRS]))
    else:
        import tempfile
        with tempfile.TemporaryDirectory(prefix='home-restore-') as temp:
            outputs = []
            with tarfile.open(args.backup_dir / 'backup.tar') as archive:
                for target in HOME_TARGETS:
                    path = Path(temp) / Path(target).name
                    path.write_bytes(archive.extractfile(target.lstrip('/')).read())
                    outputs.append((path.name, path))
            remote = audio.stage_files(device, outputs, 'home-restore')
        after = {t: backup['files'][t] for t in HOME_TARGETS}
        replace(device, [remote + '/' + n for n, _ in outputs], backup['metadata'], before, after)
        return
    remote = audio.stage_files(device, outputs, 'home-install')
    replace(device, [remote + '/' + n for n, _ in outputs], backup['metadata'], before, after)


if __name__ == '__main__':
    main()
