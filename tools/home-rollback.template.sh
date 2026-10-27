#!/system/bin/sh
# Invoke manually under NEMESIS root, never auto-run.
set -eu
export PATH=/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin
case "${1-}" in --check|--restore) ACTION=$1 ;; *) echo 'Usage: sh restore-home.sh --check|--restore'; exit 2 ;; esac
case "$0" in */*) HERE=${0%/*} ;; *) HERE=. ;; esac
cd "$HERE"
PAYLOAD="$(pwd)/payload"
WORK="/data/nemesis/home-manual-rollback-$$"
mkdir "$WORK"
chmod 700 "$WORK"
cp "$PAYLOAD/busybox-armv7" "$WORK/busybox"
chmod 700 "$WORK/busybox"
BB="$WORK/busybox"
fail() { echo "ERROR: $*"; exit 1; }
hash() { "$BB" sha256sum "$1" | "$BB" cut -d ' ' -f 1; }
check_hash() { [ "$(hash "$1")" = "$2" ] || fail "Checksum mismatch: $1"; }
check_hash "$BB" @BB_SHA@
[ "$("$BB" id -u)" = 0 ] || fail 'Root required'
check_hash "$PAYLOAD/payload.sha256" @LIST_SHA@
cd "$PAYLOAD"
"$BB" sha256sum -c payload.sha256 || fail 'Payload changed'
"$BB" sha256sum -c unchanged.sha256 || fail 'Firmware dependencies changed'
T0=@T0@
T1=@T1@
O0=@O0@
O1=@O1@
P0=@P0@
P1=@P1@
C0=$(hash "$T0")
C1=$(hash "$T1")
case "$C0" in "$O0"|"$P0") ;; *) fail 'Unknown launcher ODEX' ;; esac
case "$C1" in "$O1"|"$P1") ;; *) fail 'Unknown home editor ODEX' ;; esac
@CONTEXT_CHECKS@
if [ "$ACTION" = --check ]; then echo 'Rollback checks passed; no remount or replacement.'; exit 0; fi
REMOUNTED=0
COMMITTED=0
READY0=0
READY1=0
cleanup() {
    result=$?
    trap - 0 HUP INT TERM
    if [ "$COMMITTED" = 0 ]; then
        if [ "$READY0" = 1 ]; then "$BB" mv -f "$T0.home-before-$$" "$T0" || result=2; fi
        if [ "$READY1" = 1 ]; then "$BB" mv -f "$T1.home-before-$$" "$T1" || result=2; fi
    fi
    if [ "$REMOUNTED" = 1 ]; then
        "$BB" sync
        /system/xbin/nemesis remount ro || result=2
    fi
    exit "$result"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
/system/xbin/nemesis remount rw
REMOUNTED=1
for target in "$T0" "$T1"; do
    [ ! -e "$target.home-before-$$" ] || fail 'Rollback backup collision'
    [ ! -e "$target.home-restore-$$" ] || fail 'Rollback staging collision'
done
"$BB" cp -p "$T0" "$T0.home-before-$$"
check_hash "$T0.home-before-$$" "$C0"
@SNAPSHOT0_LABEL@
READY0=1
"$BB" cp -p "$T1" "$T1.home-before-$$"
check_hash "$T1.home-before-$$" "$C1"
@SNAPSHOT1_LABEL@
READY1=1
@PREPARE@
"$BB" mv -f "$T0.home-restore-$$" "$T0"
"$BB" mv -f "$T1.home-restore-$$" "$T1"
check_hash "$T0" "$O0"
check_hash "$T1" "$O1"
"$BB" sync
COMMITTED=1
echo 'Original launcher/editor ODEXs restored. Reboot manually; no reboot sent.'
