# Configurable Gen5W home launcher

This project adds configurable app and command tiles to the Hyundai/Kia Gen5W
launcher and its separate Edit Home Icons app. A one-time firmware-specific
patch adds a shared JSON-backed tile registry and action dispatcher to both
OEM ODEXs. Once installed, adding or editing a tile is a settings/assets update;
it does not require another DEX or ODEX change.

See [`quick_start.md`](quick_start.md) for the end-to-end ADB/build/deployment
workflow, and [`examples/configurable/README.md`](examples/configurable/README.md)
for the tile schema, assets, and runtime details. The patcher preserves the
signed OEM APKs and changes only the companion ODEX files.

## Reproduce the build

The repository does not include Hyundai/Mobis firmware, OEM APK/ODEX files,
physical backups, or prebuilt ODEXs. Supply an authorized, hash-verified
capture from the exact target firmware. Also clone `gen5w-audio-shortcuts`
adjacent to this repository; the ADB workflow imports its transport and
artifact-cache modules. Host build requirements are Java 25, Android SDK API 19
(build-tools 36.0.0), and Ghidra 12.1.4 for dexlib2/baksmali libraries.

1. Run `tools/build_configurable.py` with the original launcher/editor backup.
   It emits DEX compiler carriers and verifies the bounded transformations.
2. Run `tools/compile_configurable.py` against the matching head unit. It
   verifies captured system inputs, compiles the carriers with the target's
   `dexopt`, and reconstructs/verifies both ODEX outputs.
3. Install only with a reviewed, target-specific before-state and rollback plan.
   A universal installer for replacing an already modified ODEX pair is not
   included.

After initial installation, `tools/update_configurable_settings.py` checks the
installed ODEX pair and firmware identity, backs up the current settings, and
updates JSON, referenced icons, and the supplied script without touching ODEXs.
Restart both OEM menu apps to load each settings update.

The one-time patch relies on firmware-specific OEM classes and method shapes.
When firmware changes, the verifier fails closed and the patch points need to
be re-audited. See [`PACKAGING_DECISION.md`](PACKAGING_DECISION.md) for the
framework choice and limitations.

## Repository contents

- `examples/configurable/`: generic tile registry patch, sample settings and
  icons, and the firmware ODEX reconstruction helper used by its build.
- `tools/`: patch, structural verification, target compilation, settings
  update, and recovery tooling.
- `examples/configurable/README.md`: complete configuration and build guide.

Device backups and deployment records remain local to their target and should
not be committed. `.gitignore` excludes backups, generated APK/DEX/ODEX outputs,
and Python caches.
