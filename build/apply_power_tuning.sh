#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Uso: $0 [--no-turbo 0|1] [--max-perf 30..100] [--hwp-boost 0|1] [--epp <modo>]" >&2
    exit 2
}

NO_TURBO=""
MAX_PERF=""
HWP_BOOST=""
EPP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-turbo)
            [[ $# -ge 2 ]] || usage
            if [[ ! "$2" =~ ^[01]$ ]]; then
                echo "Error: --no-turbo debe ser 0 o 1" >&2
                exit 2
            fi
            NO_TURBO="$2"
            shift 2
            ;;
        --max-perf)
            [[ $# -ge 2 ]] || usage
            if [[ ! "$2" =~ ^[0-9]+$ ]] || (( "$2" < 30 || "$2" > 100 )); then
                echo "Error: --max-perf debe estar entre 30 y 100" >&2
                exit 2
            fi
            MAX_PERF="$2"
            shift 2
            ;;
        --hwp-boost)
            [[ $# -ge 2 ]] || usage
            if [[ ! "$2" =~ ^[01]$ ]]; then
                echo "Error: --hwp-boost debe ser 0 o 1" >&2
                exit 2
            fi
            HWP_BOOST="$2"
            shift 2
            ;;
        --epp)
            [[ $# -ge 2 ]] || usage
            case "$2" in
                default|performance|balance_performance|balance_power|power)
                    EPP="$2"
                    ;;
                *)
                    echo "Error: --epp inválido: $2" >&2
                    exit 2
                    ;;
            esac
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

if [[ -z "$NO_TURBO" && -z "$MAX_PERF" && -z "$HWP_BOOST" && -z "$EPP" ]]; then
    usage
fi

if [[ -n "$NO_TURBO" && -w /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    printf '%s' "$NO_TURBO" > /sys/devices/system/cpu/intel_pstate/no_turbo
fi

if [[ -n "$MAX_PERF" && -w /sys/devices/system/cpu/intel_pstate/max_perf_pct ]]; then
    printf '%s' "$MAX_PERF" > /sys/devices/system/cpu/intel_pstate/max_perf_pct
fi

if [[ -n "$HWP_BOOST" && -w /sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost ]]; then
    printf '%s' "$HWP_BOOST" > /sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost
fi

if [[ -n "$EPP" ]]; then
    for path in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
        if [[ -w "$path" ]]; then
            printf '%s' "$EPP" > "$path"
        fi
    done
fi
