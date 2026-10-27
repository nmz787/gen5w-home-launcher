#!/usr/bin/env python3
"""Deploy configurable home tile settings to the matching installed head unit.

This updates runtime JSON, referenced icons, and optionally the party-mode
script. It never writes launcher/editor APKs or ODEXs.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import shlex
import sys
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
AUDIO_TOOLS = ROOT.parent / 'gen5w-audio-shortcuts/tools'
HOME_TOOL = ROOT / 'tools/headunit-home-adb.py'
spec = importlib.util.spec_from_file_location('home_adb', HOME_TOOL)
home_adb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(home_adb)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in {'', '.', '..'} for p in path.parts):
        raise ValueError('Expected a safe relative path: ' + repr(value))
    return path


def validate_assets(asset_dir):
    config_path = asset_dir / 'tiles.json'
    config_bytes = config_path.read_bytes()
    if len(config_bytes) > 65536:
        raise ValueError('tiles.json exceeds 64 KiB')
    config = json.loads(config_bytes)
    tiles = config.get('tiles')
    if config.get('version') != 1 or not isinstance(tiles, list) or len(tiles) > 32:
        raise ValueError('Expected version 1 settings with at most 32 tiles')
    ids = set()
    paths = {'tiles.json'}
    for tile in tiles:
        tile_id = tile.get('id')
        if not isinstance(tile_id, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', tile_id) or tile_id in ids:
            raise ValueError('Invalid or duplicate tile id: ' + repr(tile_id))
        ids.add(tile_id)
        name = tile.get('display_name')
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError('Invalid display_name for tile ' + tile_id)
        for key in ('icon_day', 'icon_night'):
            value = tile.get(key)
            if value is None and key == 'icon_night':
                continue
            if not isinstance(value, str):
                raise ValueError('Missing or invalid ' + key + ' for tile ' + tile_id)
            rel = safe_relative(value)
            image = asset_dir.joinpath(*rel.parts)
            if image.is_symlink() or not image.resolve().is_relative_to(asset_dir.resolve()):
                raise ValueError('Icon path escapes the supplied assets directory: ' + value)
            data = image.read_bytes()
            if len(data) > 2 * 1024 * 1024 or len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError('Invalid PNG or image over 2 MiB: ' + value)
            width = int.from_bytes(data[16:20], 'big')
            height = int.from_bytes(data[20:24], 'big')
            if not 1 <= width <= 512 or not 1 <= height <= 512:
                raise ValueError('PNG dimensions must be at most 512x512: ' + value)
            paths.add(str(rel))
        action = tile.get('action')
        if not isinstance(action, dict) or action.get('type') not in {'activity', 'exec'}:
            raise ValueError('Unsupported action for tile ' + tile_id)
        if action['type'] == 'exec':
            argv = action.get('argv')
            if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or any(
                    not isinstance(arg, str) or len(arg) > 4096 or '\x00' in arg for arg in argv):
                raise ValueError('Invalid exec argv for tile ' + tile_id)
            if not argv[0].startswith('/'):
                raise ValueError('exec argv[0] must be an absolute path')
    files = {p: asset_dir.joinpath(*PurePosixPath(p).parts).read_bytes() for p in sorted(paths)}
    if (asset_dir / 'ambient_party_mode.sh').is_file():
        files['ambient_party_mode.sh'] = (asset_dir / 'ambient_party_mode.sh').read_bytes()
    return config, config_bytes, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='Current ADB serial for the deployed unit')
    parser.add_argument('--deployment', required=True, type=Path,
                        help='deployment.json for the currently installed ODEX pair')
    parser.add_argument('--previous-update', type=Path,
                        help='Most recent update.json, required after the first settings update')
    parser.add_argument('--assets', type=Path, default=ROOT / 'examples/configurable/assets')
    parser.add_argument('--out-dir', type=Path, help='Host backup/report directory (defaults beside deployment.json)')
    parser.add_argument('--nemesis', action='store_true', required=True)
    parser.add_argument('--busybox-device', required=True)
    parser.add_argument('--busybox-sha256', required=True)
    args = parser.parse_args()

    deployment = json.loads(args.deployment.read_text())
    previous_update = json.loads(args.previous_update.read_text()) if args.previous_update else None
    if previous_update and previous_update.get('build_fingerprint') not in (None, deployment.get('build_fingerprint')):
        raise RuntimeError('Previous settings update belongs to another firmware build')
    _, config_bytes, files = validate_assets(args.assets.resolve())
    sys.path.insert(0, str(AUDIO_TOOLS))

    command = argparse.Namespace(adb='adb', serial=args.serial, su=False, nemesis=True,
                                 busybox_device=args.busybox_device,
                                 busybox_sha256=args.busybox_sha256)
    device = home_adb.audio.Device(command)
    device.ready()
    device.bb = args.busybox_device
    expected_build = deployment['build_fingerprint']
    if (device.shell('getprop ro.build.fingerprint') != expected_build or
            device.shell('getprop ro.product.device') != deployment['product']):
        raise RuntimeError('Connected unit build identity differs from deployment record')
    launcher_paths = ['/system/app/Launcher_WP3.odex', '/system/app/HKMC_HomeSetting_WP.odex']
    installed = device.hashes(launcher_paths)
    recorded = deployment.get('installed') or deployment.get('after', {})
    if not all(path in recorded for path in launcher_paths):
        raise RuntimeError('Deployment record lacks installed launcher/editor ODEX hashes')
    for path in launcher_paths:
        if installed.get(path) != recorded.get(path):
            raise RuntimeError('Installed launcher/editor ODEX changed: ' + path)
    previous_files = (previous_update or {}).get('files')
    if previous_files is None:
        previous_files = {p: h for p, h in deployment.get('after', {}).items()
                          if p.startswith('/data/local/gen5w-home/')}
    actual_previous = device.hashes(list(previous_files))
    if actual_previous != previous_files:
        raise RuntimeError('Current settings/assets differ from the recorded deployment/update')

    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = (args.out_dir or args.deployment.parent / ('settings-update-' + now)).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    old_archive = out_dir / 'previous-settings.tar'
    device.stream(device.bb + ' tar -cf - -C /data/local/gen5w-home .', old_archive)
    old_script = None
    if 'ambient_party_mode.sh' in files:
        old_script = out_dir / 'ambient_party_mode.before.sh'
        device.stream('cat /data/local/tmp/ambient_party_mode.sh', old_script)

    payload = out_dir / 'settings-update.tar'
    with tarfile.open(payload, 'w') as archive:
        for name, data in files.items():
            if name == 'ambient_party_mode.sh':
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, __import__('io').BytesIO(data))
    payload_hash = digest(payload.read_bytes())
    tag = uuid.uuid4().hex
    remote = '/data/local/tmp/gen5w-home-update-' + tag
    backup_remote = '/data/local/gen5w-home.backup-' + tag
    q = shlex.quote
    device.shell('set -e; [ ! -e ' + q(remote) + ' ]; mkdir ' + q(remote) + '; chmod 755 ' + q(remote), unprivileged=True)
    device.push(payload, remote + '/settings-update.tar')
    if 'ambient_party_mode.sh' in files:
        staged_script = out_dir / 'ambient_party_mode.new.sh'
        staged_script.write_bytes(files['ambient_party_mode.sh'])
        device.push(staged_script, remote + '/ambient_party_mode.sh.new')

    if old_script:
        script_bytes = files['ambient_party_mode.sh']
        script_hash = digest(script_bytes)
        script_path = '/data/local/tmp/ambient_party_mode.sh'
        script_backup = script_path + '.backup-' + tag
        expected_script = (previous_update or {}).get('script_sha256')
        if expected_script is None:
            expected_script = deployment.get('after', {}).get(script_path)
        if device.hashes([script_path]).get(script_path) != expected_script:
            raise RuntimeError('Party script differs from the recorded deployment/update')
        old_script_remote = remote + '/ambient_party_mode.before.sh'
        device.push(old_script, old_script_remote)
        device.shell(f'''set -e
NEW={q(script_path + '.new-' + tag)}
cp {q(remote + '/ambient_party_mode.sh.new')} "$NEW"
chmod 644 "$NEW"
cp {q(script_path)} {q(script_backup)}
mv "$NEW" {q(script_path)}
''', unprivileged=True)
        if device.hashes([script_path]).get(script_path) != script_hash:
            raise RuntimeError('Party script readback mismatch')
    else:
        script_hash = device.hashes(['/data/local/tmp/ambient_party_mode.sh']).get(
            '/data/local/tmp/ambient_party_mode.sh')
        script_backup = None

    extract = [
        'set -e',
        'BB=' + q(device.bb),
        'BASE=/data/local/gen5w-home',
        'NEW=/data/local/gen5w-home.new-' + tag,
        'OLD=' + q(backup_remote),
        '[ -d "$BASE" ] && [ ! -e "$NEW" ] && [ ! -e "$OLD" ]',
        'mkdir "$NEW"',
        '"$BB" tar -xf ' + q(remote + '/settings-update.tar') + ' -C "$NEW"',
        'chmod 755 "$NEW"',
        'chmod 644 "$NEW/tiles.json"',
        'mv "$BASE" "$OLD"',
        'if ! mv "$NEW" "$BASE"; then mv "$OLD" "$BASE"; exit 1; fi',
        'sync',
    ]
    try:
        device.shell('\n'.join(extract))
    except Exception:
        device.shell('if [ -d ' + q(backup_remote) + ' ]; then [ ! -e /data/local/gen5w-home ] || mv /data/local/gen5w-home ' +
                     q('/data/local/gen5w-home.failed-' + tag) + '; mv ' + q(backup_remote) +
                     ' /data/local/gen5w-home; fi')
        if old_script:
            device.shell('cp ' + q(old_script_remote) + ' ' + q('/data/local/tmp/ambient_party_mode.restore-' + tag) +
                         '; mv ' + q('/data/local/tmp/ambient_party_mode.restore-' + tag) + ' ' +
                         q('/data/local/tmp/ambient_party_mode.sh'), unprivileged=True)
        raise

    expected_files = {'/data/local/gen5w-home/' + name: digest(data)
                      for name, data in files.items() if name != 'ambient_party_mode.sh'}
    actual_files = device.hashes(list(expected_files))
    try:
        if actual_files != expected_files:
            raise RuntimeError('Settings/assets readback mismatch: ' + repr(actual_files))
        if script_hash and device.hashes(['/data/local/tmp/ambient_party_mode.sh']).get(
                '/data/local/tmp/ambient_party_mode.sh') != script_hash:
            raise RuntimeError('Party script readback mismatch')
    except Exception:
        device.shell('set -e; mv /data/local/gen5w-home ' + q('/data/local/gen5w-home.failed-' + tag) +
                     '; mv ' + q(backup_remote) + ' /data/local/gen5w-home')
        if old_script:
            device.shell('set -e; mv ' + q('/data/local/tmp/ambient_party_mode.sh') + ' ' +
                         q('/data/local/tmp/ambient_party_mode.failed-' + tag) + '; mv ' +
                         q(script_backup) + ' ' + q('/data/local/tmp/ambient_party_mode.sh'),
                         unprivileged=True)
        raise
    record = {'serial': args.serial, 'product': deployment['product'],
              'build_fingerprint': expected_build,
              'time_utc': datetime.now(timezone.utc).isoformat(),
              'deployment_manifest': str(args.deployment.resolve()),
              'settings_sha256': digest(config_bytes), 'payload_sha256': payload_hash,
              'previous_update': str(args.previous_update.resolve()) if args.previous_update else None,
              'files': expected_files, 'script_sha256': script_hash,
              'previous_settings_archive': str(old_archive),
              'previous_settings_archive_sha256': digest(old_archive.read_bytes()),
              'device_previous_settings': backup_remote,
              'previous_script_backup': str(old_script) if old_script else None,
              'device_previous_script': script_backup,
              'requires_restart': ['com.android.launcher3', 'com.hkmc.system.app.homesetting']}
    (out_dir / 'update.json').write_text(json.dumps(record, indent=2) + '\n')
    try:
        device.shell(device.bb + ' rm -r ' + q(remote), unprivileged=True)
    except Exception:
        print('Temporary upload directory retained:', remote)
    print('Settings and icon hashes verified. No ODEX files were changed.')
    print('Restart both OEM menu processes to load the new settings generation.')
    print('Update record:', out_dir / 'update.json')


if __name__ == '__main__':
    main()
