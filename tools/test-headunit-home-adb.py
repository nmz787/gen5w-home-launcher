#!/usr/bin/env python3
"""Host-only integrity, target scope and transaction tests for the home pair."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('home', Path(__file__).with_name('headunit-home-adb.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def fixture(self, folder):
        files = {n: m.sha(b'original') for n in (*m.HOME_TARGETS, *m.HOME_APKS,
                 '/system/build.prop', '/system/framework/core.jar', '/system/framework/core.odex')}
        metadata = {t: {'mode': '644', 'uid': str(os.getuid()), 'gid': str(os.getgid()),
                        'context': None} for t in m.HOME_TARGETS}
        backup = {'serial': 'test', 'files': files, 'metadata': metadata}
        with tarfile.open(folder / 'backup.tar', 'w') as archive:
            for name in files:
                member = tarfile.TarInfo(name.lstrip('/'))
                member.size = 8
                archive.addfile(member, io.BytesIO(b'original'))
        backup['archive_sha256'] = m.sha((folder / 'backup.tar').read_bytes())
        (folder / 'backup.json').write_text(json.dumps(backup))
        manifest = {'_source': {'serial': 'test', 'files': dict(files)}, '_patches': {'test': 'hash'},
                    '_toolchain': {'test': 'toolchain'}}
        for carrier, output in m.PAIRS:
            dex = carrier + '.dex'
            data = b'dex\n035\x00patch'
            (folder / dex).write_bytes(data)
            with zipfile.ZipFile(folder / carrier, 'w') as archive:
                archive.writestr('classes.dex', data)
            manifest[dex] = {'sha256': m.sha(data)}
            manifest[carrier] = {'sha256': m.sha((folder / carrier).read_bytes()), 'dex': dex}
            data = b'dey\ncompiled'
            (folder / output).write_bytes(data)
            manifest[output] = {'sha256': m.sha(data)}
        (folder / 'build-manifest.json').write_text(json.dumps(manifest))
        return backup, manifest

    def device(self, backup):
        return SimpleNamespace(shell=lambda command: '19' if command.startswith('getprop') else 'Disabled',
                               hashes=lambda names: {n: backup['files'][n] for n in names})

    def test_exact_source_inventory_and_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); backup, manifest = self.fixture(folder)
            self.assertEqual(m.audio.load_backup(folder, 'test'), backup)
            self.assertEqual(m.read_build(folder, backup, 'test'), manifest)
            self.assertEqual(m.check(self.device(backup), backup),
                             {t: backup['files'][t] for t in m.HOME_TARGETS})

    def test_wrong_serial_and_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); self.fixture(folder)
            with self.assertRaisesRegex(RuntimeError, 'another ADB serial'):
                m.audio.load_backup(folder, 'other')
            (folder / 'backup.tar').write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError, 'archive checksum'):
                m.audio.load_backup(folder, 'test')

    def test_unknown_live_dependency_and_wrong_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            backup, manifest = self.fixture(Path(temp)); device = self.device(backup)
            changed = dict(backup['files']); changed['/system/framework/core.odex'] = 'unknown'
            device.hashes = lambda names: {n: changed[n] for n in names}
            with self.assertRaisesRegex(RuntimeError, 'firmware mismatch'):
                m.check(device, backup)
            backup['metadata'][m.HOME_TARGETS[0]] = {}
            with self.assertRaisesRegex(RuntimeError, 'metadata'):
                m.metadata_check(device, backup)

    def test_enforcing_missing_context_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            backup, _ = self.fixture(Path(temp))
            with self.assertRaisesRegex(RuntimeError, 'SELinux context'):
                m.metadata_check(SimpleNamespace(shell=lambda command: 'Enforcing'), backup)

    def test_missing_or_unknown_source_input_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); backup, manifest = self.fixture(folder)
            del manifest['_source']['files']['/system/framework/core.odex']
            (folder / 'build-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'source inventory'):
                m.read_build(folder, backup, 'test')

    def test_carrier_dex_digest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); backup, manifest = self.fixture(folder)
            carrier = m.PAIRS[0][0]
            manifest[manifest[carrier]['dex']]['sha256'] = 'bad'
            (folder / 'build-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'DEX checksum'):
                m.read_build(folder, backup, 'test')

    def test_restore_allows_only_known_target_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            backup, manifest = self.fixture(Path(temp)); device = self.device(backup)
            changed = dict(backup['files']); changed[m.HOME_TARGETS[0]] = manifest[m.PAIRS[0][1]]['sha256']
            device.hashes = lambda names: {n: changed[n] for n in names}
            m.check(device, backup, manifest, allow_modified=True)
            changed[m.HOME_TARGETS[0]] = 'unrelated'
            with self.assertRaisesRegex(RuntimeError, 'firmware mismatch'):
                m.check(device, backup, manifest, allow_modified=True)

    def test_compiled_runtime_and_output_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); _, manifest = self.fixture(folder)
            manifest['_patches'] = {'tools/headunit-home-adb.py': m.sha(Path(m.__file__).read_bytes())}
            runtime = {'native_files': {n: 'a' * 64 for n in m.artifact_cache.NATIVE},
                       'sdk': '19', 'abi': 'armeabi-v7a', 'boot_classpath': ['/system/framework/core.jar'],
                       'flags': m.artifact_cache.FLAGS}
            inputs = m.identity(manifest, runtime)
            manifest['_compilation'] = {'inputs': inputs, 'cache_key': m.artifact_cache.key(inputs)}
            with patch.object(m.artifact_cache, 'runtime', return_value=runtime):
                m.compiled_check(None, folder, manifest)
            different = dict(runtime, abi='armeabi')
            with patch.object(m.artifact_cache, 'runtime', return_value=different):
                with self.assertRaisesRegex(RuntimeError, 'runtime/input provenance'):
                    m.compiled_check(None, folder, manifest)
            (folder / m.PAIRS[0][1]).write_bytes(b'dey\ncorrupt')
            with patch.object(m.artifact_cache, 'runtime', return_value=runtime):
                with self.assertRaisesRegex(RuntimeError, 'checksum/header'):
                    m.compiled_check(None, folder, manifest)

    def transaction(self, failure):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); targets = tuple(str(folder / n) for n in ('launcher.odex', 'editor.odex'))
            sources = [folder / 'new-launcher', folder / 'new-editor']
            for target in targets: Path(target).write_bytes(b'original')
            for source in sources: source.write_bytes(b'patched')
            before = {t: m.sha(b'original') for t in targets}; after = {t: m.sha(b'patched') for t in targets}
            metadata = {t: {'mode': '644', 'uid': str(os.getuid()), 'gid': str(os.getgid()), 'context': None}
                        for t in targets}
            injected = ''
            if failure == 'stage': sources[1].unlink()
            if failure == 'rename':
                injected = 'mv() { case "$1" in *editor.odex.home-*-new) return 1 ;; esac; command mv "$@"; };\n'
            class Local:
                bb = 'env'; nemesis = False
                def hashes(self, names): return {n: m.sha(Path(n).read_bytes()) for n in names}
                def shell(self, command):
                    result = subprocess.run(['sh', '-c', 'mount() { :; }; sync() { :; };\n' + injected + command],
                                            capture_output=True, text=True)
                    if result.returncode: raise RuntimeError(result.stderr)
            with patch.object(m, 'HOME_TARGETS', targets):
                if failure:
                    with self.assertRaises(RuntimeError): m.replace(Local(), sources, metadata, before, after)
                else: m.replace(Local(), sources, metadata, before, after)
            for target in targets: self.assertEqual(Path(target).read_bytes(), b'original' if failure else b'patched')

    def test_transaction_success(self): self.transaction(None)
    def test_transaction_stage_failure(self): self.transaction('stage')
    def test_transaction_second_rename_failure(self): self.transaction('rename')

    def rollback_failure(self, failure):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); targets = [folder / 'launcher', folder / 'editor']
            for target in targets: target.write_bytes(b'original')
            busybox = folder / 'bb'
            busybox.write_text('#!/bin/sh\n' +
                ('case "$*" in "cp -p "*editor.home-before-*) printf partial > "$4"; exit 1 ;; esac\n'
                 if failure == 'partial' else '') + 'exec "$@"\n')
            busybox.chmod(0o755)
            template = Path(m.__file__).with_name('home-rollback.template.sh').read_text()
            body = template[template.index('REMOUNTED=0'):]
            body = body.replace('/system/xbin/nemesis remount rw', ':').replace('/system/xbin/nemesis remount ro', ':')
            body = body.replace('@PREPARE@', ':').replace('@SNAPSHOT0_LABEL@', ':').replace('@SNAPSHOT1_LABEL@', ':')
            prefix = ('set -eu\nBB=' + m.q(busybox) + '\nT0=' + m.q(targets[0]) + '\nT1=' + m.q(targets[1]) +
                      '\nC0=' + m.sha(b'original') + '\nC1=' + m.sha(b'original') + '\n' +
                      'fail() { echo "$*"; exit 1; };\n' +
                      'check_hash() { [ "$(sha256sum "$1" | cut -d " " -f 1)" = "$2" ] || fail hash; };\n')
            if failure == 'collision': prefix += 'printf unrelated > "$T0.home-before-$$"\n'
            result = subprocess.run(['sh', '-c', prefix + body], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            for target in targets: self.assertEqual(target.read_bytes(), b'original')
            if failure == 'collision':
                self.assertEqual(next(folder.glob('launcher.home-before-*')).read_bytes(), b'unrelated')
            else:
                self.assertEqual(next(folder.glob('editor.home-before-*')).read_bytes(), b'partial')

    def test_rollback_collision_does_not_restore_unrelated_file(self): self.rollback_failure('collision')
    def test_rollback_partial_snapshot_does_not_replace_original(self): self.rollback_failure('partial')

    def test_manual_rollback_kit_contains_originals_without_autorun(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); backup, manifest = self.fixture(folder)
            busybox = folder / 'busybox'; busybox.write_bytes(b'busybox')
            out = folder / 'kit'
            m.rollback_kit(out, folder, backup, folder, manifest, busybox)
            self.assertEqual((out / 'payload/Launcher_WP3.odex').read_bytes(), b'original')
            self.assertFalse((out / 'NEMESIS.data').exists())
            script = (out / 'restore-home.sh').read_text()
            self.assertNotIn('@', script)
            self.assertIn('Unknown launcher ODEX', script)
            self.assertEqual(subprocess.run(['sh', '-n', str(out / 'restore-home.sh')]).returncode, 0)

if __name__ == '__main__': unittest.main()
