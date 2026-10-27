#!/system/bin/sh
# Hyundai Gen5W: foreground or managed background ambient-light animation.
# Uses the verified NEEV23 US System-service ABI. No root required.

LOOP=0
RANDOM_ORDER=0
DRY_RUN=0
STEP_MS=150
MIN=0
MAX=10
ACTIVE_PID=
TOUCHED=0
WORK=
CONTROL=foreground
DAEMON=0
STATE=${PARTY_MODE_STATE_DIR:-${TMPDIR:-/data/local/tmp}/ambient-party-mode}
SELF=$0
SHELL_BIN=${PARTY_MODE_SHELL:-/system/bin/sh}

usage() {
    echo '
Usage: sh ambient_party_mode.sh [--loop] [--random] [--step-ms N] [--min N] [--max N] [--dry-run]
  Default: one cycle through all 64 custom-wheel colors.
  --start       Start a detached background worker; no duplicate instance.
  --stop        Request TERM, wait for cleanup; no forced kill.
  --toggle      Stop a running worker, otherwise start one.
  --status      Report running, starting, or stopped (exit 0, 2, or 3).
  --state-dir P Store worker identity/logs in this directory (same path for control).
  --loop        Repeat until Ctrl-C or TERM/HUP.
  --random      Shuffle each cycle; visit every color once before repeating.
  --step-ms N   Delay after each step (default 150; live range 50..5000).
  --min N       Dim brightness, 0..9 (default 0).
  --max N       Peak brightness, 1..10 (default 10; must exceed --min).
  --dry-run     Print commands without sending them; allows --step-ms 0.
  --help        Show this help.

Without a control option, run in an interactive shell for Ctrl-C support.
Use the same UID and PARTY_MODE_STATE_DIR/TMPDIR for later control commands.
The launcher uses --toggle --loop --random; state survives launcher restarts.
Each color is selected at minimum brightness, then fades up and back down.
Stopping or finishing leaves the last color at --min brightness.
No original color/brightness snapshot is restored.
'
}

fail() { echo "$*" >&2; exit 1; }
uint() { case "$1" in ''|*[!0-9]*) return 1;; esac; }

# Bind signals to a recorded process birth time, not just a reusable PID.
birth() {
    uint "$1" || return 1
    [ -r "/proc/$1/stat" ] || return 1
    IFS= read -r proc_stat < "/proc/$1/stat" || return 1
    proc_fields=${proc_stat##*) }
    set -f
    set -- $proc_fields
    set +f
    [ "$#" -ge 20 ] && [ "$1" != Z ] || return 1
    shift 19
    echo "$1"
}

running() {
    [ -r "$STATE/run.pid" ] || return 1
    read -r worker_pid worker_birth < "$STATE/run.pid" || return 1
    uint "$worker_pid" && uint "$worker_birth" || return 1
    [ "$(birth "$worker_pid")" = "$worker_birth" ] && kill -0 "$worker_pid" 2>/dev/null
}

release_control() {
    rm -f "$STATE/control.lock/owner"
    rmdir "$STATE/control.lock" 2>/dev/null
}

take_control() {
    control_wait=0
    while ! mkdir "$STATE/control.lock" 2>/dev/null; do
        # A killed controller can leave a lock, but never clear a live owner's.
        if [ -r "$STATE/control.lock/owner" ]; then
            read -r owner_pid owner_birth < "$STATE/control.lock/owner"
            if uint "$owner_pid" && uint "$owner_birth" && [ "$(birth "$owner_pid")" != "$owner_birth" ]; then
                rm -f "$STATE/control.lock/owner"
                rmdir "$STATE/control.lock" 2>/dev/null
            fi
        fi
        control_wait=$((control_wait + 1))
        [ "$control_wait" -lt 100 ] || fail "Controller busy; inspect $STATE/control.lock"
        sleep 0.1
    done
    echo "$$ $(birth "$$")" > "$STATE/control.lock/owner"
    trap 'release_control' 0
    trap 'exit 143' TERM
    trap 'exit 130' INT
    trap 'exit 129' HUP
}

start_worker() {
    if running; then echo "Party mode already running (PID $worker_pid)."; return 0; fi
    rm -f "$STATE/run.pid" "$STATE/ready" "$STATE/last_exit"
    token=$$-$(birth "$$")
    echo "$token" > "$STATE/launch.token"
    set -- --worker --step-ms "$STEP_MS" --min "$MIN" --max "$MAX"
    [ "$LOOP" -eq 0 ] || set -- "$@" --loop
    [ "$RANDOM_ORDER" -eq 0 ] || set -- "$@" --random
    [ "$DRY_RUN" -eq 0 ] || set -- "$@" --dry-run
    : > "$STATE/daemon.log"
    (
        trap '' HUP
        export PARTY_MODE_STATE_DIR="$STATE" PARTY_MODE_TOKEN="$token"
        exec "$SHELL_BIN" "$SELF" "$@"
    ) </dev/null >> "$STATE/daemon.log" 2>&1 &
    launched_pid=$!
    start_wait=0
    while [ "$start_wait" -lt 50 ]; do
        if [ -r "$STATE/ready" ] && running; then
            echo "Party mode started (PID $worker_pid); log: $STATE/daemon.log"
            return 0
        fi
        if [ -f "$STATE/last_exit" ] || ! kill -0 "$launched_pid" 2>/dev/null; then
            if [ -r "$STATE/last_exit" ]; then
                read -r completed_code completed_cleanup < "$STATE/last_exit"
                if [ "$completed_code" = 0 ] && [ "$completed_cleanup" = 1 ]; then
                    echo "Party mode completed; log: $STATE/daemon.log"
                    return 0
                fi
            fi
            cat "$STATE/daemon.log" >&2
            return 1
        fi
        sleep 0.1
        start_wait=$((start_wait + 1))
    done
    echo "Worker startup pending; use --status before retrying." >&2
    return 1
}

stop_worker() {
    if ! running; then
        rm -f "$STATE/run.pid" "$STATE/ready" "$STATE/launch.token"
        echo 'Party mode is stopped.'
        return 0
    fi
    stopping_pid=$worker_pid
    stopping_birth=$worker_birth
    kill -TERM "$stopping_pid" || return 1
    stop_wait=0
    while [ "$stop_wait" -lt 100 ]; do
        if [ "$(birth "$stopping_pid")" != "$stopping_birth" ]; then
            if [ -f "$STATE/last_exit" ]; then
                read -r stopped_code cleanup_ok < "$STATE/last_exit"
                [ "$cleanup_ok" = 1 ] || { echo 'Worker exited; brightness cleanup failed.' >&2; return 1; }
            else
                echo 'Worker disappeared without recording cleanup.' >&2
                return 1
            fi
            echo "Party mode stopped; cleanup complete (exit $stopped_code)."
            return 0
        fi
        sleep 0.1
        stop_wait=$((stop_wait + 1))
    done
    echo "Stop requested; cleanup still pending (PID $stopping_pid). No forced kill sent." >&2
    return 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --state-dir)
            [ "$#" -ge 2 ] || fail '--state-dir needs an absolute path'
            case "$2" in /*) STATE=$2 ;; *) fail '--state-dir must be absolute' ;; esac
            shift 2 ;;
        --start|--stop|--toggle|--status|--worker)
            [ "$CONTROL" = foreground ] || fail 'Choose one control operation'
            CONTROL=${1#--}; shift ;;
        --loop) LOOP=1; shift ;;
        --random) RANDOM_ORDER=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) usage; exit 0 ;;
        --step-ms|--min|--max)
            opt=$1
            [ "$#" -ge 2 ] || fail "$opt needs a value"
            uint "$2" || fail "$opt needs a nonnegative integer"
            # Normalize decimal input without shell octal interpretation.
            val=$2
            while [ "${val#0}" != "$val" ] && [ "${#val}" -gt 1 ]; do val=${val#0}; done
            [ "${#val}" -le 4 ] || fail "$opt value is too large"
            case "$opt" in
                --step-ms) STEP_MS=$val ;;
                --min) MIN=$val ;;
                --max) MAX=$val ;;
            esac
            shift 2 ;;
        *) fail "Unknown option: $1 (use --help)" ;;
    esac
done

[ "$MIN" -le 9 ] && [ "$MAX" -le 10 ] && [ "$MAX" -gt "$MIN" ] || fail 'Require 0 <= --min < --max <= 10'
[ "$STEP_MS" -le 5000 ] || fail '--step-ms must be at most 5000'
[ "$DRY_RUN" -eq 1 ] || [ "$STEP_MS" -ge 50 ] || fail 'Live --step-ms must be at least 50'
delay_ms=$((STEP_MS % 1000))
while [ "${#delay_ms}" -lt 3 ]; do delay_ms=0$delay_ms; done
STEP_DELAY=$((STEP_MS / 1000)).$delay_ms
if [ "$RANDOM_ORDER" -eq 1 ]; then
    case "$RANDOM" in
        ''|*[!0-9]*) fail '--random requires the Android shell RANDOM variable' ;;
    esac
fi

if [ "$CONTROL" != foreground ] && [ "$CONTROL" != worker ]; then
    umask 077
    [ ! -L "$STATE" ] || fail 'State directory must not be a symlink'
    mkdir -p "$STATE" || fail "Cannot create $STATE"
    chmod 700 "$STATE" || fail "Cannot secure $STATE"
    if [ "$CONTROL" = status ]; then
        if running; then
            if [ -f "$STATE/ready" ]; then echo "Party mode running (PID $worker_pid)."; exit 0; fi
            echo "Party mode starting (PID $worker_pid)."; exit 2
        fi
        if [ -f "$STATE/launch.token" ]; then echo 'Party mode starting or stale; use --stop to clear stale state.'; exit 2; fi
        echo 'Party mode is stopped.'; exit 3
    fi
    take_control
    case "$CONTROL" in
        start) start_worker; exit $? ;;
        stop) stop_worker; exit $? ;;
        toggle) if running; then stop_worker; else start_worker; fi; exit $? ;;
    esac
fi

if [ "$CONTROL" = worker ]; then
    [ -n "$PARTY_MODE_TOKEN" ] && [ -r "$STATE/launch.token" ] || fail 'Worker requires a controller token'
    read -r expected_token < "$STATE/launch.token"
    [ "$expected_token" = "$PARTY_MODE_TOKEN" ] || fail 'Worker token mismatch'
    DAEMON=1
fi

cancel_child() {
    if [ -n "$ACTIVE_PID" ]; then
        kill -TERM "$ACTIVE_PID" 2>/dev/null
        wait "$ACTIVE_PID" 2>/dev/null
        ACTIVE_PID=
    fi
}

on_signal() {
    trap '' INT TERM HUP
    echo >&2
    echo "Stopping party mode..." >&2
    cancel_child
    exit "$1"
}

binder_call() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "service call com.hkmc.micom.system $*"
        return 0
    fi
    service call com.hkmc.micom.system "$@" > "$WORK/reply" 2>&1 &
    ACTIVE_PID=$!
    wait "$ACTIVE_PID"
    call_rc=$?
    ACTIVE_PID=
    reply=$(cat "$WORK/reply")
    if [ "$call_rc" -ne 0 ]; then
        echo "Binder command failed: $reply" >&2
        return 1
    fi
    case "$reply" in
        *'Parcel(00000000'*) return 0 ;;
        *) echo "Unexpected Binder reply: $reply" >&2; return 1 ;;
    esac
}

brightness() { binder_call 77 i32 5 i32 "$(($1 + 1))"; }

finish() {
    finish_rc=$?
    trap - 0
    trap '' INT TERM HUP
    cancel_child
    cleanup_ok=1
    if [ "$TOUCHED" -eq 1 ]; then
        if ! brightness "$MIN"; then
            echo "Could not return brightness to $MIN." >&2
            [ "$finish_rc" -ne 0 ] || finish_rc=1
            cleanup_ok=0
        fi
    fi
    if [ "$DAEMON" -eq 1 ]; then
        echo "$finish_rc $cleanup_ok" > "$STATE/last_exit"
        rm -f "$STATE/run.pid" "$STATE/ready" "$STATE/launch.token"
    fi
    if [ -n "$WORK" ]; then
        rm -f "$WORK/reply"
        rmdir "$WORK" 2>/dev/null
    fi
    exit "$finish_rc"
}

trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'on_signal 129' HUP
[ "$DAEMON" -eq 0 ] || trap '' HUP
trap 'finish' 0

pause_step() {
    [ "$STEP_MS" -gt 0 ] || return 0
    sleep "$STEP_DELAY" &
    ACTIVE_PID=$!
    wait "$ACTIVE_PID"
    pause_rc=$?
    ACTIVE_PID=
    return "$pause_rc"
}

if [ "$DRY_RUN" -eq 0 ]; then
    command -v service >/dev/null 2>&1 || fail 'Android service command is required'
    # Check the legacy shell's fractional sleep before any lighting request.
    sleep 0.001 || fail 'Fractional sleep is unavailable'
    umask 077
    WORK=${TMPDIR:-/data/local/tmp}/ambient-party-$$
    mkdir "$WORK" || fail "Cannot create $WORK"
fi

if [ "$DAEMON" -eq 1 ]; then
    echo "$$ $(birth "$$")" > "$STATE/run.pid.next"
    mv "$STATE/run.pid.next" "$STATE/run.pid"
fi

# Raw RGB from the installed Hyundai custom wheel; no preset marker bit.
PALETTE='
247 255 182 F7FFB6
230 254 186 E6FEBA
210 255 188 D2FFBC
175 254 191 AFFEBF
119 254 196 77FEC4
58 255 198 3AFFC6
10 255 235 0AFFEB
0 217 245 00D9F5
0 180 255 00B4FF
0 161 255 00A1FF
0 140 255 008CFF
0 125 255 007DFF
0 115 254 0073FE
0 99 255 0063FF
0 85 255 0055FF
0 62 255 003EFF
25 0 255 1900FF
55 0 255 3700FF
81 0 255 5100FF
100 0 255 6400FF
109 42 255 6D2AFF
122 52 255 7A34FF
125 25 255 7D19FF
128 0 255 8000FF
130 0 255 8200FF
143 0 255 8F00FF
156 0 255 9C00FF
167 0 255 A700FF
176 0 255 B000FF
195 0 254 C300FE
205 0 254 CD00FE
232 0 254 E800FE
255 0 241 FF00F1
255 0 195 FF00C3
255 0 158 FF009E
255 0 137 FF0089
255 0 117 FF0075
255 0 111 FF006F
255 0 106 FF006A
255 0 101 FF0065
254 0 95 FE005F
255 0 72 FF0048
254 0 58 FE003A
254 0 30 FE001E
255 3 10 FF030A
254 34 0 FE2200
255 48 23 FF3017
255 60 42 FF3C2A
255 65 49 FF4131
255 73 73 FF4949
255 88 88 FF5858
255 96 106 FF606A
255 107 116 FF6B74
255 113 113 FF7171
255 125 115 FF7D73
255 137 107 FF896B
255 148 119 FF9477
255 160 111 FFA06F
255 172 113 FFAC71
255 177 108 FFB16C
255 191 123 FFBF7B
254 207 138 FECF8A
255 216 147 FFD893
254 237 165 FEEDA5
'

echo "Party mode: 64 colors, brightness $MIN..$MAX, $STEP_MS ms per step. Ctrl-C stops." >&2
TOUCHED=1
brightness "$MIN" || exit 1
[ "$DAEMON" -eq 0 ] || echo ready > "$STATE/ready"
cycle=0
last_hex=
while :; do
    cycle=$((cycle + 1))
    # The detached worker appends to this file; truncating at cycle boundaries
    # bounds output even in verbose dry-run mode, without a logging subprocess.
    [ "$DAEMON" -eq 0 ] || : > "$STATE/daemon.log"
    echo "Cycle $cycle" >&2
    # Deliberately split only our fixed numeric palette into shell arguments.
    set -- $PALETTE
    color_index=0
    while [ "$#" -gt 0 ]; do
        if [ "$RANDOM_ORDER" -eq 1 ]; then
            # Pick from remaining rows, rotating that row to the front.
            # Removing it below gives a shuffle without replacement.
            remaining=$(($# / 4))
            skip=$((RANDOM % remaining))
            while [ "$skip" -gt 0 ]; do
                set -- "$@" "$1" "$2" "$3" "$4"
                shift 4
                skip=$((skip - 1))
            done
            # Also avoid a duplicate at the boundary of two shuffled cycles.
            if [ "$color_index" -eq 0 ] && [ "$4" = "$last_hex" ] && [ "$remaining" -gt 1 ]; then
                set -- "$@" "$1" "$2" "$3" "$4"
                shift 4
            fi
        fi
        red=$1; green=$2; blue=$3; color_hex=$4
        shift 4
        last_hex=$color_hex
        color_index=$((color_index + 1))
        echo "Color $color_index/64: #$color_hex" >&2
        binder_call 78 i32 2 i32 "$((red * 256))" i32 2 i32 "$((green * 256))" i32 2 i32 "$((blue * 256))" || exit 1
        pause_step || exit 1
        level=$((MIN + 1))
        while [ "$level" -le "$MAX" ]; do
            brightness "$level" || exit 1
            pause_step || exit 1
            level=$((level + 1))
        done
        level=$((MAX - 1))
        while [ "$level" -ge "$MIN" ]; do
            brightness "$level" || exit 1
            pause_step || exit 1
            level=$((level - 1))
        done
    done
    [ "$LOOP" -eq 1 ] || break
done
echo "Completed $cycle cycle(s)." >&2
