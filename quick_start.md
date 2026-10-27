# Quick start: build and deploy configurable home tiles

This guide covers the one-time launcher/editor ODEX change and later JSON tile
updates. The build reads an original, complete firmware capture, compiles the
DEX carriers on the matching head unit, and pulls verified ODEXs back to the
host. Deployment is a separate step. Do not use emulator ODEXs on a physical
unit.

## 1. Connect and identify the head unit

For Wi-Fi ADB, connect and pin the serial on every command:

```sh
HU_SERIAL=HEADUNIT_IP:5555
adb connect "$HU_SERIAL"
adb devices -l
adb -s "$HU_SERIAL" shell 'getprop ro.product.device; getprop ro.build.fingerprint; getprop ro.build.version.sdk'
```

Confirm the product, fingerprint, and API 19 runtime are the intended target.
The privileged steps below require the already-installed NEMESIS root channel
and an existing, verified BusyBox. They do not install either tool.

## 2. Capture or select the original OEM files

The build source must be a complete capture made while the launcher and
Edit Home Icons ODEXs are still original. A capture made after installing this
patch is a rollback/current-state backup; it cannot replace the original build
source. Keep the capture private because it contains OEM files and device data.

To capture a still-original unit, use the capture helper from the adjacent
`preconditioning-workflow` project. It uses ADB/NEMESIS to pull and hash the
launcher, editor, and matching framework inputs:

```sh
BACKUP_DIR=/private/path/original-headunit-capture
BUSYBOX_DEVICE=/data/local/tmp/path/to/verified/busybox
BUSYBOX_SHA256=expected_sha256_of_busybox

python3 ../preconditioning-workflow/capture.py \
  --serial "$HU_SERIAL" \
  --nemesis \
  --busybox-device "$BUSYBOX_DEVICE" \
  --busybox-sha256 "$BUSYBOX_SHA256" \
  --out "$BACKUP_DIR"
```

The capture helper does not install or reboot. If the target already has a
modified launcher/editor pair, use the verified pre-install capture retained
for that unit instead of capturing its current ODEXs as originals. This repo's
successful reproduction used
`backups/preconditioning_button/live-home-20261022T055934Z`.

## 3. Build locally, then compile on the head unit

Clone `gen5w-audio-shortcuts` next to this repository. Set the pinned host
toolchain paths and use a new, empty output directory for every build:

```sh
BUILD_DIR=/private/path/configurable-home-build
JAVA_HOME=/path/to/jdk-25
ANDROID_SDK=/path/to/Android/Sdk
GHIDRA_HOME=/path/to/ghidra_12.1.4_PUBLIC

python3 tools/build_configurable.py \
  --backup-dir "$BACKUP_DIR" \
  --out "$BUILD_DIR" \
  --java-home "$JAVA_HOME" \
  --android-sdk "$ANDROID_SDK" \
  --ghidra-home "$GHIDRA_HOME"
```

Compile using the connected target's API 19 `dexopt`. The tool pushes the two
compiler carriers to temporary storage under `/data`, invokes `dexopt`, pulls
the ODEXs to `BUILD_DIR`, and reconstructs/verifies them locally. This does
not install or reboot:

```sh
python3 tools/compile_configurable.py \
  --serial "$HU_SERIAL" \
  --backup-dir "$BACKUP_DIR" \
  --build-dir "$BUILD_DIR" \
  --java-home "$JAVA_HOME" \
  --ghidra-home "$GHIDRA_HOME" \
  --nemesis \
  --busybox-device "$BUSYBOX_DEVICE" \
  --busybox-sha256 "$BUSYBOX_SHA256"
```

If the target has other known ODEX modifications, pass one
`--allow-live-drift /system/path.odex=sha256` for each exact hash, after
checking it against that unit's installation record. The compiler accepts
only those explicit live hashes. The installer has a stricter source-state
check and does not accept these drift exceptions.

The compiler-carrier ZIP metadata is pinned so re-running the same sources and
toolchain reproduces the same physical ODEX bytes. The 2026-10-27 reproduction
matched both ODEXs already on the head unit byte for byte.

## 4. Install the ODEX pair on a matching original target

The installation helper stages files with `adb push`, then uses NEMESIS to
replace only the two ODEXs transactionally and verify their hashes. It never
replaces the signed OEM APKs and does not reboot:

```sh
python3 tools/headunit-home-adb.py check \
  --serial "$HU_SERIAL" --nemesis \
  --busybox-device "$BUSYBOX_DEVICE" \
  --busybox-sha256 "$BUSYBOX_SHA256" \
  --backup-dir "$BACKUP_DIR" --build-dir "$BUILD_DIR"

python3 tools/headunit-home-adb.py install \
  --serial "$HU_SERIAL" --nemesis \
  --busybox-device "$BUSYBOX_DEVICE" \
  --busybox-sha256 "$BUSYBOX_SHA256" \
  --backup-dir "$BACKUP_DIR" --build-dir "$BUILD_DIR"
```

`check` and `install` require the connected system to match the captured
baseline apart from the two launcher/editor ODEXs. If the check rejects a
changed file, stop and investigate; do not bypass the check or push directly
into `/system`. In particular, this helper cannot reinstall over an already
modified launcher pair or accept unrelated system ODEX drift. The head unit
used for the 2026-10-27 reproduction already had the new ODEX pair installed
and had two separately modified MODE shortcut ODEXs, so this command was not
run on that unit. For that deployment, the uploaded ODEXs were hash-checked
against the saved deployment record.

For the first runtime upload, stage the settings and icons with `adb push`,
then use the existing NEMESIS root channel to copy them into the shared
settings directory. `adb push` the party script directly so it remains
shell-owned. Stop any currently running party worker before replacing its
script.

```sh
STAGE=/data/local/tmp/gen5w-home-initial
adb -s "$HU_SERIAL" shell "mkdir -p '$STAGE/icons'"
adb -s "$HU_SERIAL" push examples/configurable/assets/tiles.json "$STAGE/tiles.json"
for image in examples/configurable/assets/icons/*.png; do
  adb -s "$HU_SERIAL" push "$image" "$STAGE/icons/"
done
adb -s "$HU_SERIAL" push examples/configurable/assets/ambient_party_mode.sh \
  /data/local/tmp/ambient_party_mode.sh
adb -s "$HU_SERIAL" shell chmod 644 /data/local/tmp/ambient_party_mode.sh
adb -s "$HU_SERIAL" shell /system/xbin/nemesis root -c \
  "mkdir -p /data/local/gen5w-home/icons && \
   cp '$STAGE/tiles.json' /data/local/gen5w-home/tiles.json && \
   cp '$STAGE/icons/'*.png /data/local/gen5w-home/icons/ && \
   chmod 755 /data/local/gen5w-home /data/local/gen5w-home/icons && \
   chmod 644 /data/local/gen5w-home/tiles.json /data/local/gen5w-home/icons/*.png"
adb -s "$HU_SERIAL" shell "$BUSYBOX_DEVICE sha256sum \
  /data/local/gen5w-home/tiles.json \
  /data/local/gen5w-home/icons/*.png \
  /data/local/tmp/ambient_party_mode.sh"
```

Compare the remote hashes with local `sha256sum` output before using the new
tiles. Save those hashes with the ODEX hashes in a private deployment record;
the settings updater uses the record to verify that it is updating the right
unit and generation. For example, its relevant fields are:

```json
{
  "product": "value from getprop ro.product.device",
  "build_fingerprint": "value from getprop ro.build.fingerprint",
  "installed": {
    "/system/app/Launcher_WP3.odex": "verified installed sha256",
    "/system/app/HKMC_HomeSetting_WP.odex": "verified installed sha256"
  },
  "after": {
    "/data/local/gen5w-home/tiles.json": "verified installed sha256",
    "/data/local/gen5w-home/icons/preconditioning-day.png": "verified installed sha256",
    "/data/local/gen5w-home/icons/preconditioning-night.png": "verified installed sha256",
    "/data/local/gen5w-home/icons/ambient-party-day.png": "verified installed sha256",
    "/data/local/gen5w-home/icons/ambient-party-night.png": "verified installed sha256",
    "/data/local/tmp/ambient_party_mode.sh": "verified installed sha256"
  }
}
```

After that initial deployment, make tile changes with the settings updater in
the next section; it pushes the new generation and verifies the hashes.

After verifying the installed ODEX hashes and runtime-file hashes, reboot
separately to load the new code:

```sh
adb -s "$HU_SERIAL" shell reboot
```

The helper deliberately does not reboot automatically. ADB may disconnect
during reboot; reconnect and verify the fingerprint and installed hashes after
the unit is back:

```sh
adb connect "$HU_SERIAL"
adb -s "$HU_SERIAL" shell 'getprop ro.build.fingerprint'
adb -s "$HU_SERIAL" shell /system/xbin/nemesis root -c \
  "$BUSYBOX_DEVICE sha256sum /system/app/Launcher_WP3.odex \
   /system/app/HKMC_HomeSetting_WP.odex"
```

## 5. Add or update tiles without rebuilding

Edit `examples/configurable/assets/tiles.json` and add/update the referenced
day/night PNGs. Retain the target's private deployment record; it must contain
the product, build fingerprint, installed launcher/editor ODEX hashes, and
hashes of the currently deployed settings tree under `after`. The updater
accepts the ODEX hash map under either `installed` or `after`.

```sh
DEPLOYMENT=/private/path/this-unit/deployment.json

python3 tools/update_configurable_settings.py \
  --serial "$HU_SERIAL" \
  --deployment "$DEPLOYMENT" \
  --assets examples/configurable/assets \
  --nemesis \
  --busybox-device "$BUSYBOX_DEVICE" \
  --busybox-sha256 "$BUSYBOX_SHA256"
```

The updater saves the previous settings/script, pushes a complete settings
generation over ADB, verifies hashes, and leaves the ODEX pair alone. Save its
printed `update.json`; pass it as `--previous-update` on the next update. Then
restart both OEM menu apps so each reloads the same generation. See
[`examples/configurable/README.md`](examples/configurable/README.md) for the
schema, actions, rollback behavior, and limitations.
