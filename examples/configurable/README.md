# Configurable home tiles

This example provides a one-time firmware-specific ODEX change that adds a
generic JSON-backed tile registry and action dispatcher, implemented in
[`TileRegistry.java`](src/com/android/launcher3/configurable/TileRegistry.java).
Both the launcher and Edit Home Icons load the same settings and artwork from
`/data/local/gen5w-home/`. After that initial code change, adding supported
tiles requires only settings/assets updates and restarting both apps; no
per-tile launcher patch is needed. The signed OEM APK resources remain
unchanged.

The DEX patch and QEMU investigation are complete. Both OEM menus, day/night
icons, settings-only tile changes, and the managed party worker were exercised
in QEMU. One physical Gen5W received the ODEX pair and runtime files, which
were hash-verified. That unit has not rebooted into the new ODEXs, so its UI and
lighting behavior remain unverified. Device-specific logs and rollback files
are intentionally kept outside this repository.

## Settings and artwork

[`assets/tiles.json`](assets/tiles.json) defines Preconditioning and Ambient Party
Mode. Its installed location is `/data/local/gen5w-home/tiles.json`:

```json
{
  "version": 1,
  "theme": "auto",
  "tiles": [
    {
      "id": "preconditioning",
      "display_name": "Preconditioning",
      "icon_day": "icons/preconditioning-day.png",
      "icon_night": "icons/preconditioning-night.png",
      "action": {
        "type": "activity",
        "component": "com.paytondev.launchpad/.MainActivity"
      }
    },
    {
      "id": "ambient_party_mode",
      "display_name": "Ambient Party Mode",
      "icon_day": "icons/ambient-party-day.png",
      "icon_night": "icons/ambient-party-night.png",
      "action": {
        "type": "exec",
        "argv": [
          "/system/bin/sh",
          "/data/local/tmp/ambient_party_mode.sh",
          "--toggle",
          "--state-dir",
          "/data/data/com.android.launcher3/files/ambient-party-mode",
          "--loop",
          "--random"
        ],
        "toggle": false
      }
    }
  ]
}
```

- `version` must be `1`. `theme` defaults to `auto`; `day` and `night` force
  artwork selection for inspection. Automatic selection reads the active
  Android resource configuration's night bits. Attached visible drawables
  invalidate approximately once per second to pick up a change.
- Keep each `id` stable when changing its label, images or action. IDs match
  `[a-z][a-z0-9_]{0,47}` and must be unique. A deterministic checked resource-ID
  mapping keeps configuration ordering separate from tile identity. The helper
  uses synthetic package/class identities in both OEM menus. It does not
  automatically migrate the older hard-coded Preconditioning tile's position.
- `display_name` contains 1–80 characters. At most 32 custom tiles and 64 KiB of
  UTF-8 configuration are accepted.
- Image paths resolve inside `/data/local/gen5w-home/`. Images must decode to
  at most 512×512 pixels and have file size at most 2 MiB. `icon_night` may be
  omitted to reuse the day image. The displayed intrinsic tile size is 144×144.
- The supplied PNGs and their SVG sources in `assets/icons/` are code-authored
  artwork with transparent backgrounds and separate day/night colors. OEM
  normal/disabled icon state remains independent; disabled custom icons render
  with reduced alpha.
- An `activity` action requires an enabled exported activity in an enabled
  application. Unavailable activity tiles are omitted from the menu.
- An `exec` action passes `argv` as arguments, without interpreting its contents
  as shell syntax. The executable path must be absolute. Use `/system/bin/sh`
  followed by a readable script path to run a shell script. There may be 1–32
  arguments, each at most 4096 characters with no NUL characters.

Malformed settings or artwork reject the whole candidate generation. The last
valid generation is retained only within the current process; after a fresh
process start with invalid settings, the extension contributes no custom tiles
and the OEM menu remains. There is no persisted last-known-good settings store.

## Execution and stopping commands

Commands run on a worker thread under the launcher's existing UID, which is
Android's system UID on the tested profile, **not root**. This mechanism adds
no privilege escalation. The working directory is `/data/local/gen5w-home/`;
`TMPDIR` points to the launcher's private cache directory.

`toggle` defaults to `true`: tap once to start, then again to request SIGTERM.
With `toggle: false`, repeated taps while tracked as running are ignored. The
helper tracks the child PID in memory and uses SIGTERM so a shell script can
run its signal traps. It does not provide a durable process manager or process
group supervision. Scripts that daemonize or leave independent children need
their own cleanup.

For ordinary long-lived exec actions, stop them before restarting the launcher:
its generic job tracking is in memory. The party-mode tile instead uses the
script-managed background controls described below, which retain worker identity
in persistent app data and were tested across a launcher restart.

Merged stdout/stderr goes to the launcher's private
`files/tile-<id>.log`, overwritten on each run. The implementation retains at
most 1,048,576 decoded characters and continues draining excess output so the
child does not block. This is 1 MiB for ASCII output; multibyte UTF-8 output can
occupy more bytes. Start/exit/errors are also logged with tag `Gen5wTiles`.

The supplied [`ambient_party_mode.sh`](assets/ambient_party_mode.sh) is the
versioned source used by the party tile.
It supports foreground operation plus `--start`, `--stop`, `--toggle`, and
`--status`. The party tile invokes `--toggle` with a stable private `--state-dir`
and sets the launcher's generic `toggle` field to `false`. Each tap runs a short
controller; the script owns the detached worker and its durable PID/birth-time
record. A new launcher process can therefore request a later graceful stop.
This restart behavior was verified in the emulator; physical Android process
management remains untested.

The worker uses private TMPDIR for temporary reply files, ignores HUP, serializes
control operations, avoids duplicate starts, and checks PID plus Linux start time
before signalling. TERM cancels its current child and requests the final minimum
brightness. A stop waits for cleanup, reports failure or timeout, and never
forces SIGKILL. `daemon.log` under the state directory is truncated each cycle.
`--status` returns 0 when running, 2 for transitional or stale state, and 3
when stopped. SIGKILL or power loss cannot run shell cleanup. The provenance
file records the script hashes. No boot hook or automatic restart is installed.

## Updating settings and reloading

Use the updater for routine settings, image, and supplied script changes. It
checks the installed ODEX pair and firmware fingerprint against the deployment
record, validates the JSON and referenced PNGs, backs up the current settings
and script, transfers the new files, and verifies their hashes. The ADB serial
can change when the unit's address changes; the tool checks the installed
ODEXs and fingerprint instead.

From the project root, provide the current ADB endpoint, a deployment record
for the installed ODEX pair, and the verified BusyBox path/hash for that unit:

```sh
python3 tools/update_configurable_settings.py \
  --serial "$GEN5W_SERIAL" \
  --deployment "$GEN5W_DEPLOYMENT_JSON" \
  --assets examples/configurable/assets \
  --nemesis \
  --busybox-device "$GEN5W_BUSYBOX_DEVICE" \
  --busybox-sha256 "$GEN5W_BUSYBOX_SHA256"
```

The deployment record is device-specific and is not included. Keep it beside
that unit's rollback files. The updater verifies the ODEXs and firmware
fingerprint before writing.

The updater writes a timestamped backup and `update.json` beside the deployment
record. For each later update, pass the newest `update.json` as
`--previous-update`; it refuses a settings tree that changed outside the
recorded update chain. It also keeps the previous settings on the unit. Runtime
settings and icon files are root-owned and world-readable. The party script
remains shell-owned and readable in `/data/local/tmp`; this profile's NEMESIS
root channel lacks `CAP_CHOWN`.

The updater installs a complete settings generation. Stop generic
launcher-owned looping commands first; the party script has its own persistent
control state. The updater does not restart either process. **Restart both `com.android.launcher3` and
`com.hkmc.system.app.homesetting`** so their independent menu lists and resource
registries read the same generation. Returning Home alone is not a defined
configuration-reload operation. There is no file watcher or settings UI.

## Building from original firmware backups

Use [`tools/build_configurable.py`](../../tools/build_configurable.py) with a
completed, hash-verified backup of the original launcher/editor APKs and ODEXs,
their exact framework dependencies, `backup.json` and `backup.tar`. Use the
backup without the older Preconditioning patch. The patcher rejects inputs
already containing the configurable helper namespace. Do not supply the older
Preconditioning-patched inputs; select and verify the original backup.

```sh
python3 tools/build_configurable.py \
  --backup-dir /path/to/original-completed-backup \
  --out /path/to/fresh-empty-output-directory \
  --java-home /path/to/jdk-25 \
  --android-sdk /path/to/Android/Sdk \
  --ghidra-home /path/to/ghidra_12.1.4_PUBLIC
```

Run this command from the project root. It reconstructs source DEX, builds the
helper for API 19, patches both menus and launcher action dispatch, and checks
the result with `VerifyConfigurableLauncher.java`. The output includes
`Launcher_WP3-preopt.apk`, `HKMC_HomeSetting_WP-preopt.apk`, source/patched DEX,
logs and `build-manifest.json`. These APK-shaped files are **DEX compiler
carriers**, not replacement signed OEM APKs. The build performs no device
compilation, installation or reboot. ZIP metadata for the helper JAR and
compiler carriers is pinned so native ODEX outputs reproduce byte for byte.

Native ODEX compilation and compiled-code verification use the matching target
runtime. `tools/compile_configurable.py` checks the captured system inputs,
accepts explicit hashes for other known system ODEX modifications, invokes the
connected unit's `dexopt`, and reconstructs/verifies the outputs against the
captured framework. Never transplant emulator ODEXs to the physical unit. An
OEM firmware update can require adapting and rebuilding this extension.

Use a completed, hash-verified capture from the target firmware, a fresh build
folder, and the pinned host toolchain. The capture contains proprietary OEM
files and must be acquired separately. The tooling also imports
`gen5w-audio-shortcuts/tools/headunit-audio-adb.py` and `artifact_cache.py`;
clone that sibling repository adjacent to this one. From the project root,
set these task-specific paths for your machine and target:

```sh
GEN5W_ORIGINAL_BACKUP=/path/to/original-physical-backup
GEN5W_BUILD_DIR=/path/to/fresh-build-output
GEN5W_JAVA_HOME=/path/to/jdk-25
GEN5W_ANDROID_SDK=/path/to/Android-Sdk
GEN5W_GHIDRA_HOME=/path/to/ghidra_12.1.4_PUBLIC
GEN5W_SERIAL=ip:port
GEN5W_BUSYBOX_DEVICE=/data/local/tmp/path/to/verified/busybox
GEN5W_BUSYBOX_SHA256=sha256-of-that-busybox

python3 tools/build_configurable.py \
  --backup-dir "$GEN5W_ORIGINAL_BACKUP" \
  --out "$GEN5W_BUILD_DIR" \
  --java-home "$GEN5W_JAVA_HOME" \
  --android-sdk "$GEN5W_ANDROID_SDK" \
  --ghidra-home "$GEN5W_GHIDRA_HOME"

python3 tools/compile_configurable.py \
  --serial "$GEN5W_SERIAL" \
  --backup-dir "$GEN5W_ORIGINAL_BACKUP" \
  --build-dir "$GEN5W_BUILD_DIR" \
  --java-home "$GEN5W_JAVA_HOME" \
  --ghidra-home "$GEN5W_GHIDRA_HOME" \
  --nemesis \
  --busybox-device "$GEN5W_BUSYBOX_DEVICE" \
  --busybox-sha256 "$GEN5W_BUSYBOX_SHA256"
```

If the target has other known system ODEX modifications, add one
`--allow-live-drift /system/path.odex=expected-sha256` option for each exact
current hash. Unknown changes are rejected. The compile command does not
install or reboot.

This compiles and verifies; it does not install or reboot. Replacing an already
modified ODEX pair requires a fresh before-state backup and a reviewed
transaction. Keep the deployment record and rollback files with that unit;
they are not included in this repository. Do not use a record from another
head unit.

See [`PACKAGING_DECISION.md`](../../PACKAGING_DECISION.md) for the choice to
keep this firmware-specific DEX/ODEX workflow in this project.
