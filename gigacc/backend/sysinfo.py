"""Información de hardware DMI, métricas de CPU/RAM/sysfs y telemetría NVIDIA."""
from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psutil

DMI_DIR = Path("/sys/class/dmi/id")
HWMON_DIR = Path("/sys/class/hwmon")
POWER_SUPPLY_DIR = Path("/sys/class/power_supply")
CPUINFO_PATH = Path("/proc/cpuinfo")

_SUPPORTED_PREFIXES = ("G5", "G6", "G7")


@dataclass(frozen=True)
class HardwareInfo:
    vendor: str
    product_name: str
    support_level: str  # "verified", "expected", "unsupported"
    cpu_model: str
    cpu_threads: int
    ram_total_gb: float


@dataclass(frozen=True)
class NvidiaMetrics:
    available: bool
    name: str = ""
    driver: str = ""
    temp_c: int = 0
    util_pct: int = 0
    mem_used_mib: int = 0
    mem_total_mib: int = 0
    power_w: float = 0.0
    clock_gfx_mhz: int = 0
    pstate: str = ""


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float
    cpu_freq_mhz: float
    cpu_max_mhz: float
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    ac_online: bool | None
    battery_percent: int | None
    battery_status: str
    cpu_temp_fallback: int | None
    nvme_temp_c: int | None


def _read_str(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return default


def classify_model(vendor: str, product_name: str) -> str:
    v = vendor.upper()
    p = product_name.upper()
    if "GIGABYTE" not in v:
        return "unsupported"
    if p.startswith("G6 KF"):
        return "verified"
    if any(p.startswith(pref) for pref in _SUPPORTED_PREFIXES):
        return "expected"
    return "unsupported"


def read_cpu_model() -> str:
    try:
        for line in CPUINFO_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "Procesador Intel/AMD"


def read_hardware_info() -> HardwareInfo:
    vendor = _read_str(DMI_DIR / "sys_vendor", "Desconocido")
    product = _read_str(DMI_DIR / "product_name", "Equipo Linux")
    mem = psutil.virtual_memory()
    return HardwareInfo(
        vendor=vendor,
        product_name=product,
        support_level=classify_model(vendor, product),
        cpu_model=read_cpu_model(),
        cpu_threads=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=mem.total / (1024 ** 3),
    )


def _read_hwmon_temps() -> tuple[int | None, int | None]:
    cpu_t: int | None = None
    nvme_t: int | None = None
    if not HWMON_DIR.is_dir():
        return None, None
    for h in HWMON_DIR.iterdir():
        name = _read_str(h / "name").lower()
        val_s = _read_str(h / "temp1_input")
        if not val_s.isdigit():
            continue
        temp_c = round(int(val_s) / 1000)
        if name in ("coretemp", "k10temp", "zenpower") and cpu_t is None:
            cpu_t = temp_c
        elif name == "nvme" and nvme_t is None:
            nvme_t = temp_c
    return cpu_t, nvme_t


def _read_power_supply() -> tuple[bool | None, int | None, str]:
    ac_online: bool | None = None
    bat_pct: int | None = None
    bat_status = ""
    if not POWER_SUPPLY_DIR.is_dir():
        return None, None, ""
    for ps in POWER_SUPPLY_DIR.iterdir():
        ps_type = _read_str(ps / "type")
        if ps_type == "Mains":
            online = _read_str(ps / "online")
            if online in ("0", "1"):
                ac_online = (online == "1")
        elif ps_type == "Battery":
            cap = _read_str(ps / "capacity")
            if cap.isdigit():
                bat_pct = int(cap)
            bat_status = _read_str(ps / "status")
    return ac_online, bat_pct, bat_status


def read_system_metrics() -> SystemMetrics:
    cpu_pct = float(psutil.cpu_percent(interval=None))
    freq = psutil.cpu_freq()
    cur_mhz = float(freq.current) if freq else 0.0
    max_mhz = float(freq.max) if freq and freq.max else 0.0
    if max_mhz <= 0:
        max_s = _read_str(Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"))
        if max_s.isdigit():
            max_mhz = int(max_s) / 1000.0
    mem = psutil.virtual_memory()
    ac_online, bat_pct, bat_status = _read_power_supply()
    cpu_t, nvme_t = _read_hwmon_temps()
    return SystemMetrics(
        cpu_percent=cpu_pct,
        cpu_freq_mhz=cur_mhz,
        cpu_max_mhz=max_mhz,
        ram_used_gb=mem.used / (1024 ** 3),
        ram_total_gb=mem.total / (1024 ** 3),
        ram_percent=float(mem.percent),
        ac_online=ac_online,
        battery_percent=bat_pct,
        battery_status=bat_status,
        cpu_temp_fallback=cpu_t,
        nvme_temp_c=nvme_t,
    )


def parse_nvidia_smi_csv(line: str) -> NvidiaMetrics:
    parts = [p.strip() for p in line.strip().split(",")]
    if len(parts) < 10:
        return NvidiaMetrics(available=False)

    def to_int(val: str, default: int = 0) -> int:
        digits = "".join(ch for ch in val.split(".")[0] if ch.isdigit())
        return int(digits) if digits else default

    def to_float(val: str, default: float = 0.0) -> float:
        cleaned = "".join(ch for ch in val if ch.isdigit() or ch == ".")
        try:
            return float(cleaned) if cleaned else default
        except ValueError:
            return default

    return NvidiaMetrics(
        available=True,
        name=parts[0],
        driver=parts[1],
        temp_c=to_int(parts[2]),
        util_pct=to_int(parts[3]),
        mem_used_mib=to_int(parts[4]),
        mem_total_mib=to_int(parts[5]),
        power_w=to_float(parts[6]),
        clock_gfx_mhz=to_int(parts[7]),
        pstate=parts[8],
    )


def read_nvidia_sync() -> NvidiaMetrics:
    if not shutil.which("nvidia-smi"):
        return NvidiaMetrics(available=False)
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,clocks.current.graphics,pstate,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return NvidiaMetrics(available=False)
        first_line = proc.stdout.strip().splitlines()[0]
        return parse_nvidia_smi_csv(first_line)
    except Exception:
        return NvidiaMetrics(available=False)


def read_nvidia_async(callback: Callable[[NvidiaMetrics], None]) -> None:
    from gi.repository import GLib

    def worker() -> None:
        metrics = read_nvidia_sync()
        GLib.idle_add(callback, metrics)

    threading.Thread(target=worker, daemon=True).start()
