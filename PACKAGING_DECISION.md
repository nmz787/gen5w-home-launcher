# Packaging decision

## Use this project's patcher and target-native build

Do not package this change as a Lucky Patcher, ReVanced, or Morphe patch.
Keep the firmware-specific DEX transformations, the original-input verifier,
and the Gen5W `dexopt` compilation in this project. ReVanced CLI and Morphe
Desktop are documented around patching APK inputs and emitting patched APKs;
Morphe Patcher exposes bytecode and APK-resource operations, but it does not
provide this project's target ODEX compilation and paired system-file
deployment. Those frameworks would still need custom glue for the part that
matters here: both OEM menu owners, exact physical framework bindings, unchanged
OEM signatures, two native ODEXs, and rollback. See the
[ReVanced CLI usage guide](https://github.com/ReVanced/revanced-cli/blob/main/docs/1_usage.md),
[Morphe Desktop](https://github.com/MorpheApp/morphe-desktop), and
[Morphe Patcher](https://github.com/MorpheApp/morphe-patcher).

Lucky Patcher is also a poor fit: this deliverable is a source-controlled,
hash-pinned firmware transformation, not an interactive APK modification or
patch-protection workflow. Its app-oriented custom patches would not replace
the exact-source checks, compiled ODEX comparison, or target install record.

## What is repeatable now

The one-time launcher change is firmware-specific. `tools/build_configurable.py`
reconstructs the original launcher and HomeSetting code, applies the audited
DEX transforms, and verifies that only the intended code changed. The
resulting APK-shaped files are DEX compiler carriers; they do not replace the
signed OEM APKs. `tools/compile_configurable.py` runs the carriers through the
connected target's Android 4.4 `dexopt`, checks source/runtime hashes, then
reconstructs and verifies both emitted ODEXs.

After that code is installed, routine tile additions and edits are a runtime
settings update. Run `tools/update_configurable_settings.py` with the current
deployment record and an assets directory. It checks the installed ODEX pair
and firmware identity, validates JSON and referenced PNGs, saves the prior
settings and script, updates the files, and checks their hashes. It never
rewrites ODEXs. Restart both OEM menu processes after an update.

The new toolchain compiles and verifies replacement ODEXs, but it does not yet
provide a universal installer for replacing an already modified ODEX pair.
That operation needs a fresh target before-state and rollback plan. This does
not affect adding tiles: those changes use the settings updater and leave the
ODEXs untouched.

Reverse engineering is still required when an OEM firmware update changes the
launcher/editor code or framework. The verifier should stop on an unrecognized
layout; that is the deliberate point where a person must re-audit the new
firmware rather than reuse stale offsets.

## Device-specific records

The maintainer's deployment record, original system captures, and rollback
files remain outside this repository because they contain private, firmware-
specific artifacts. Keep those files with the target device's deployment. The
example physical install was not rebooted into the new ODEX pair; its UI
behavior still requires a reboot and inspection.
