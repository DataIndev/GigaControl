#!/usr/bin/env bash
set -euo pipefail

PKG_NAME="gigactl-hotkeys"
PKG_VER="1.0.0"
SRC_DEST="/usr/src/${PKG_NAME}-${PKG_VER}"
MOD_CONF="/etc/modules-load.d/gigactl-hotkeys.conf"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "${SCRIPT_DIR}/kernel/gigactl-hotkeys" ]]; then
    MOD_SRC="${SCRIPT_DIR}/kernel/gigactl-hotkeys"
elif [[ -d "${SCRIPT_DIR}/../kernel/gigactl-hotkeys" ]]; then
    MOD_SRC="${SCRIPT_DIR}/../kernel/gigactl-hotkeys"
else
    echo "Error: no se encontró el código fuente de gigactl-hotkeys." >&2
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "Este script debe ejecutarse como root (ej. mediante pkexec o sudo)." >&2
    exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
    modprobe -r gigactl_hotkeys 2>/dev/null || true
    rm -f "${MOD_CONF}"
    if command -v dkms >/dev/null 2>&1; then
        dkms remove -m "${PKG_NAME}" -v "${PKG_VER}" --all 2>/dev/null || true
    fi
    rm -rf "${SRC_DEST}"
    echo "Driver gigactl_hotkeys desinstalado."
    exit 0
fi

KVER="$(uname -r)"
if [[ ! -d "/lib/modules/${KVER}/build" ]]; then
    echo "Error: faltan los linux-headers para el kernel ${KVER}." >&2
    exit 1
fi

rm -rf "${SRC_DEST}"
mkdir -p "${SRC_DEST}"
cp -r "${MOD_SRC}/." "${SRC_DEST}/"

if command -v dkms >/dev/null 2>&1; then
    dkms remove -m "${PKG_NAME}" -v "${PKG_VER}" --all 2>/dev/null || true
    dkms add -m "${PKG_NAME}" -v "${PKG_VER}"
    dkms build -m "${PKG_NAME}" -v "${PKG_VER}" -k "${KVER}"
    dkms install -m "${PKG_NAME}" -v "${PKG_VER}" -k "${KVER}"
else
    make -C "${SRC_DEST}" KVER="${KVER}"
    install -D -m 0644 "${SRC_DEST}/gigactl_hotkeys.ko" "/lib/modules/${KVER}/extra/gigactl_hotkeys.ko"
    depmod -a "${KVER}"
fi

printf 'gigactl_hotkeys\n' > "${MOD_CONF}"
modprobe -r gigactl_hotkeys 2>/dev/null || true
modprobe gigactl_hotkeys
echo "Driver gigactl_hotkeys instalado y cargado correctamente."
