# Tooling and provenance

## Configurable launcher pipeline

`tools/build_configurable.py` uses `examples/configurable/DeodexLauncher.java`
to reconstruct each captured physical ODEX against its matching framework. It
then patches both OEM menu owners with `PatchConfigurableLauncher.java` and
checks the transformation with `VerifyConfigurableLauncher.java`.

`tools/compile_configurable.py` compiles the DEX carriers on the matching
head-unit runtime, then calls `tools/verify_compiled_configurable.py` to
reconstruct and compare both native ODEX results. `tools/update_configurable_settings.py`
updates runtime JSON/icons/script after checking the installed ODEX pair and
firmware identity. It does not alter ODEX files.

The `DeodexLauncher.java` reconstruction helper was adapted from the QEMU
launcher investigation in the adjacent `hyundai_gen5w_qemu` workspace. No OEM
APK, DEX, ODEX, system image, or emulator disk is included here.

## External ADB dependency

The compile and settings tools reuse
`../gen5w-audio-shortcuts/tools/headunit-audio-adb.py` and
`artifact_cache.py` for guarded ADB transport and runtime identity. Clone that
repository adjacent to this one. Their expected source hashes are recorded in
[`AUDIO_SHORTCUTS_PROVENANCE.json`](AUDIO_SHORTCUTS_PROVENANCE.json).

## Firmware and licensing

Supply an authorized, complete backup of the exact target firmware. Do not
commit physical backups, generated OEM code, rollback copies, or deployment
records. The sibling audio-shortcuts project has not selected a source license;
this repository does not grant rights to it or to OEM material.
