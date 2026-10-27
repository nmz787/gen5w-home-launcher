#!/usr/bin/env python3
"""Compile configurable launcher DEX carriers with a matching Gen5W dexopt."""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME_TOOL = ROOT / 'tools/headunit-home-adb.py'
spec = importlib.util.spec_from_file_location('home_adb', HOME_TOOL)
home_adb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(home_adb)


def parse_drift(values):
    result = {}
    for value in values:
        path, separator, digest = value.partition('=')
        if not separator or not path.startswith('/system/') or not path.endswith('.odex'):
            raise ValueError('--allow-live-drift must be /system/path.odex=64-hex-sha256')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid live-drift SHA-256: ' + digest)
        result[path] = digest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='Connected target ADB serial')
    parser.add_argument('--backup-dir', required=True, type=Path,
                        help='Original, unmodified physical source capture')
    parser.add_argument('--build-dir', required=True, type=Path,
                        help='Fresh output from build_configurable.py')
    parser.add_argument('--java-home', required=True, type=Path)
    parser.add_argument('--ghidra-home', required=True, type=Path)
    parser.add_argument('--nemesis', action='store_true', required=True)
    parser.add_argument('--busybox-device', required=True)
    parser.add_argument('--busybox-sha256', required=True)
    parser.add_argument('--allow-live-drift', action='append', default=[], metavar='PATH=SHA256',
                        help='Explicitly permit a known other ODEX patch on the target')
    args = parser.parse_args()
    backup_dir = args.backup_dir.resolve()
    build_dir = args.build_dir.resolve()
    backup_manifest = json.loads((backup_dir / 'backup.json').read_text())
    source_serial = backup_manifest['serial']
    backup = home_adb.audio.load_backup(backup_dir, source_serial)
    manifest = home_adb.read_build(build_dir, backup, source_serial)
    drift = parse_drift(args.allow_live_drift)

    device_args = argparse.Namespace(adb='adb', serial=args.serial, su=False, nemesis=True,
                                     busybox_device=args.busybox_device,
                                     busybox_sha256=args.busybox_sha256)
    device = home_adb.audio.Device(device_args)
    device.ready()
    if device.shell('getprop ro.build.version.sdk') != '19':
        raise RuntimeError('Target is not the API 19 runtime used by this launcher patch')

    expected = home_adb.source_inventory(backup)
    actual = device.hashes(expected)
    ignored = set(home_adb.HOME_TARGETS)
    for path, recorded_hash in drift.items():
        if path not in expected:
            raise RuntimeError('Live-drift path is not part of the source capture: ' + path)
        if actual.get(path) != recorded_hash:
            raise RuntimeError('Live-drift hash changed: ' + path)
        ignored.add(path)
    unexpected = [path for path, digest in expected.items()
                  if path not in ignored and actual.get(path) != digest]
    if unexpected:
        raise RuntimeError('Target system differs from the source capture: ' + ', '.join(unexpected))

    home_adb.compile_pair(device, build_dir, manifest)
    home_adb.compiled_check(device, build_dir, manifest)
    verifier = ROOT / 'tools/verify_compiled_configurable.py'
    command = [sys.executable, str(verifier), '--backup-dir', str(backup_dir),
               '--build-dir', str(build_dir), '--java-home', str(args.java_home.resolve()),
               '--ghidra-home', str(args.ghidra_home.resolve())]
    subprocess.run(command, check=True)
    record = {'target_serial': args.serial, 'source_serial': source_serial,
              'target_fingerprint': device.shell('getprop ro.build.fingerprint'),
              'explicit_live_odex_drift': drift,
              'compilation': manifest['_compilation'],
              'outputs': {name: manifest[name] for name in
                          ('Launcher_WP3-patched.odex', 'HKMC_HomeSetting_WP-patched.odex')}}
    (build_dir / 'target-compile.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Target ODEXs compiled and reconstructed/verified. Installation and reboot were not performed.')


if __name__ == '__main__':
    main()
