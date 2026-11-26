"""Control de perfiles de energía, gráficos (system76-power), brillo (logind)
y ajuste avanzado de intel_pstate / EPP."""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

SYS_POWER_BUS = "com.system76.PowerDaemon"
SYS_POWER_PATH = "/com/system76/PowerDaemon"
SYS_POWER_IFACE = "com.system76.PowerDaemon"

UPOWER_PROFILES_BUS = "org.freedesktop.UPower.PowerProfiles"
UPOWER_PROFILES_PATH = "/org/freedesktop/UPower/PowerProfiles"
UPOWER_PROFILES_IFACE = "org.freedesktop.UPower.PowerProfiles"

LOGIN1_BUS = "org.freedesktop.login1"
LOGIN1_SESSION_PATH = "/org/freedesktop/login1/session/auto"
LOGIN1_SESSION_IFACE = "org.freedesktop.login1.Session"

INTEL_PSTATE_DIR = Path("/sys/devices/system/cpu/intel_pstate")
CPU0_FREQ_DIR = Path("/sys/devices/system/cpu/cpu0/cpufreq")
BACKLIGHT_DIR = Path("/sys/class/backlight")


@dataclass(frozen=True)
class BacklightInfo:
    device: str
    current: int
    maximum: int

    @property
    def percent(self) -> int:
        if self.maximum <= 0:
            return 100
        return max(0, min(100, round(self.current * 100 / self.maximum)))


@dataclass(frozen=True)
class CpuPowerState:
    pstate_available: bool
    turbo_enabled: bool
    max_perf_pct: int
    min_perf_pct: int
    hwp_dynamic_boost: bool
    governor: str
    epp: str
    available_epps: tuple[str, ...]


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def find_backlight_device() -> BacklightInfo | None:
    if not BACKLIGHT_DIR.is_dir():
        return None
    candidates = sorted(BACKLIGHT_DIR.iterdir(), key=lambda p: (0 if "intel" in p.name else 1, p.name))
    for dev in candidates:
        max_s = _read_text(dev / "max_brightness")
        cur_s = _read_text(dev / "actual_brightness") or _read_text(dev / "brightness")
        if max_s.isdigit() and cur_s.isdigit():
            return BacklightInfo(device=dev.name, current=int(cur_s), maximum=int(max_s))
    return None


def read_cpu_power_state() -> CpuPowerState:
    pstate_ok = (INTEL_PSTATE_DIR / "no_turbo").exists()
    no_turbo = _read_text(INTEL_PSTATE_DIR / "no_turbo", "0") == "1"
    max_perf_s = _read_text(INTEL_PSTATE_DIR / "max_perf_pct", "100")
    min_perf_s = _read_text(INTEL_PSTATE_DIR / "min_perf_pct", "17")
    hwp_s = _read_text(INTEL_PSTATE_DIR / "hwp_dynamic_boost", "0")
    gov = _read_text(CPU0_FREQ_DIR / "scaling_governor", "")
    epp = _read_text(CPU0_FREQ_DIR / "energy_performance_preference", "")
    avail_epp_raw = _read_text(CPU0_FREQ_DIR / "energy_performance_available_preferences", "")
    avail_epps = tuple(x for x in avail_epp_raw.split() if x and x != "default")
    return CpuPowerState(
        pstate_available=pstate_ok,
        turbo_enabled=not no_turbo,
        max_perf_pct=int(max_perf_s) if max_perf_s.isdigit() else 100,
        min_perf_pct=int(min_perf_s) if min_perf_s.isdigit() else 0,
        hwp_dynamic_boost=(hwp_s == "1"),
        governor=gov,
        epp=epp,
        available_epps=avail_epps,
    )


def normalize_power_profile(name: str) -> str:
    low = (name or "").strip().lower()
    if low in ("battery", "power-saver", "saver"):
        return "battery"
    if low in ("performance", "perf"):
        return "performance"
    return "balanced"


def find_tuning_helper() -> Path | None:
    env_dir = os.environ.get("GIGACC_DATA_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir) / "apply_power_tuning.sh")
    candidates.extend([
        Path.home() / ".local" / "share" / "gigabyte-control-center" / "apply_power_tuning.sh",
        Path(__file__).resolve().parents[2] / "scripts" / "apply_power_tuning.sh",
        Path(__file__).resolve().parents[2] / "build" / "apply_power_tuning.sh",
    ])
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


class PowerClient:
    """Gestiona perfiles System76/UPower, modo de gráficos, brillo y intel_pstate."""

    def __init__(
        self,
        on_profile_changed: Callable[[str], None] | None = None,
        on_graphics_changed: Callable[[str, bool, bool], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_profile_changed = on_profile_changed
        self._on_graphics_changed = on_graphics_changed
        self._on_error = on_error
        self._s76_proxy: Gio.DBusProxy | None = None
        self._upower_proxy: Gio.DBusProxy | None = None
        self._login_proxy: Gio.DBusProxy | None = None

        self.power_profile: str = "balanced"
        self.graphics_mode: str = "unknown"
        self.switchable_graphics: bool = False
        self.graphics_power: bool = True

    def start(self) -> None:
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            SYS_POWER_BUS,
            SYS_POWER_PATH,
            SYS_POWER_IFACE,
            None,
            self._on_s76_ready,
        )
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            UPOWER_PROFILES_BUS,
            UPOWER_PROFILES_PATH,
            UPOWER_PROFILES_IFACE,
            None,
            self._on_upower_ready,
        )
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            LOGIN1_BUS,
            LOGIN1_SESSION_PATH,
            LOGIN1_SESSION_IFACE,
            None,
            self._on_login_ready,
        )

    @property
    def s76_available(self) -> bool:
        return bool(self._s76_proxy and self._s76_proxy.get_name_owner())

    @property
    def upower_available(self) -> bool:
        return bool(self._upower_proxy and self._upower_proxy.get_name_owner())

    def _on_s76_ready(self, _src, result) -> None:
        try:
            self._s76_proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            self._s76_proxy = None
            return
        self._s76_proxy.connect("g-signal", self._on_s76_signal)
        self.refresh_s76_state()

    def _on_upower_ready(self, _src, result) -> None:
        try:
            self._upower_proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            self._upower_proxy = None
            return
        if not self.s76_available and self.upower_available:
            v = self._upower_proxy.get_cached_property("ActiveProfile")
            if v is not None:
                self.power_profile = normalize_power_profile(v.get_string())
                if self._on_profile_changed:
                    self._on_profile_changed(self.power_profile)

    def _on_login_ready(self, _src, result) -> None:
        try:
            self._login_proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            self._login_proxy = None

    def _on_s76_signal(self, _proxy, _sender, signal_name, params) -> None:
        if signal_name == "PowerProfileSwitch":
            (prof,) = params.unpack()
            self.power_profile = normalize_power_profile(prof)
            if self._on_profile_changed:
                self._on_profile_changed(self.power_profile)

    def refresh_s76_state(self) -> None:
        if not self.s76_available or self._s76_proxy is None:
            return
        self._s76_proxy.call("GetProfile", None, Gio.DBusCallFlags.NONE, 2000, None, self._got_profile)
        self._s76_proxy.call("GetGraphics", None, Gio.DBusCallFlags.NONE, 2000, None, self._got_graphics)
        self._s76_proxy.call("GetSwitchable", None, Gio.DBusCallFlags.NONE, 2000, None, self._got_switchable)
        self._s76_proxy.call("GetGraphicsPower", None, Gio.DBusCallFlags.NONE, 2000, None, self._got_gfx_power)

    def _got_profile(self, proxy, res) -> None:
        try:
            (prof,) = proxy.call_finish(res).unpack()
            self.power_profile = normalize_power_profile(prof)
            if self._on_profile_changed:
                self._on_profile_changed(self.power_profile)
        except Exception:
            pass

    def _got_graphics(self, proxy, res) -> None:
        try:
            (mode,) = proxy.call_finish(res).unpack()
            self.graphics_mode = str(mode)
            if self._on_graphics_changed:
                self._on_graphics_changed(self.graphics_mode, self.switchable_graphics, self.graphics_power)
        except Exception:
            pass

    def _got_switchable(self, proxy, res) -> None:
        try:
            (sw,) = proxy.call_finish(res).unpack()
            self.switchable_graphics = bool(sw)
            if self._on_graphics_changed:
                self._on_graphics_changed(self.graphics_mode, self.switchable_graphics, self.graphics_power)
        except Exception:
            pass

    def _got_gfx_power(self, proxy, res) -> None:
        try:
            (pwr,) = proxy.call_finish(res).unpack()
            self.graphics_power = bool(pwr)
            if self._on_graphics_changed:
                self._on_graphics_changed(self.graphics_mode, self.switchable_graphics, self.graphics_power)
        except Exception:
            pass

    def set_power_profile(self, profile: str) -> None:
        norm = normalize_power_profile(profile)
        if self.s76_available and self._s76_proxy is not None:
            method = {"battery": "Battery", "balanced": "Balanced", "performance": "Performance"}[norm]
            self._s76_proxy.call(method, None, Gio.DBusCallFlags.NONE, 5000, None, self._on_set_profile_done, norm)
            return
        if self.upower_available and self._upower_proxy is not None:
            upower_name = {"battery": "power-saver", "balanced": "balanced", "performance": "performance"}[norm]
            bus = self._upower_proxy.get_connection()
            bus.call(
                UPOWER_PROFILES_BUS,
                UPOWER_PROFILES_PATH,
                "org.freedesktop.DBus.Properties",
                "Set",
                GLib.Variant("(ssv)", (UPOWER_PROFILES_IFACE, "ActiveProfile", GLib.Variant("s", upower_name))),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
                self._on_set_profile_done,
                norm,
            )
            return
        if self._on_error:
            self._on_error("No se encontró system76-power ni power-profiles-daemon en D-Bus.")

    def _on_set_profile_done(self, source, res, norm: str) -> None:
        try:
            source.call_finish(res)
            self.power_profile = norm
            if self._on_profile_changed:
                self._on_profile_changed(norm)
        except GLib.Error as exc:
            if self._on_error:
                self._on_error(f"Error al cambiar el perfil de energía: {exc.message}")

    def set_graphics_mode(self, mode: str, on_done: Callable[[bool, str], None] | None = None) -> None:
        if not self.s76_available or self._s76_proxy is None:
            if on_done:
                on_done(False, "system76-power no está disponible.")
            return

        def finish(proxy, res) -> None:
            try:
                proxy.call_finish(res)
                self.graphics_mode = mode
                if self._on_graphics_changed:
                    self._on_graphics_changed(self.graphics_mode, self.switchable_graphics, self.graphics_power)
                if on_done:
                    on_done(True, mode)
            except GLib.Error as exc:
                if on_done:
                    on_done(False, exc.message)

        self._s76_proxy.call(
            "SetGraphics",
            GLib.Variant("(s)", (mode,)),
            Gio.DBusCallFlags.NONE,
            30000,
            None,
            finish,
        )

    def set_screen_brightness(self, percent: int) -> None:
        info = find_backlight_device()
        if info is None or info.maximum <= 0:
            if self._on_error:
                self._on_error("No se detectó dispositivo de retroiluminación de pantalla.")
            return
        pct = max(5, min(100, int(percent)))
        raw = max(1, min(info.maximum, round(info.maximum * pct / 100)))
        if self._login_proxy is None or not self._login_proxy.get_name_owner():
            if self._on_error:
                self._on_error("El servicio systemd-logind no respondió para ajustar el brillo.")
            return
        self._login_proxy.call(
            "SetBrightness",
            GLib.Variant("(ssu)", ("backlight", info.device, raw)),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
            self._on_brightness_done,
        )

    def _on_brightness_done(self, proxy, res) -> None:
        try:
            proxy.call_finish(res)
        except GLib.Error as exc:
            if self._on_error:
                self._on_error(f"No se pudo cambiar el brillo de pantalla: {exc.message}")

    def apply_cpu_tuning(
        self,
        *,
        turbo_enabled: bool | None = None,
        max_perf_pct: int | None = None,
        hwp_boost: bool | None = None,
        epp: str | None = None,
        on_done: Callable[[bool, str], None] | None = None,
    ) -> None:
        helper = find_tuning_helper()
        if helper is None:
            if on_done:
                on_done(False, "No se encontró el script auxiliar apply_power_tuning.sh.")
            return
        cmd = ["pkexec", str(helper)]
        if turbo_enabled is not None:
            cmd.extend(["--no-turbo", "0" if turbo_enabled else "1"])
        if max_perf_pct is not None:
            cmd.extend(["--max-perf", str(max(30, min(100, int(max_perf_pct))))])
        if hwp_boost is not None:
            cmd.extend(["--hwp-boost", "1" if hwp_boost else "0"])
        if epp:
            cmd.extend(["--epp", epp])

        def worker() -> None:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                ok = proc.returncode == 0
                if ok:
                    msg = "Ajustes avanzados de CPU aplicados."
                else:
                    msg = proc.stderr.strip() or "Autorización cancelada o fallida al aplicar ajustes de CPU."
            except Exception as exc:
                ok = False
                msg = str(exc)
            if on_done:
                GLib.idle_add(on_done, ok, msg)

        threading.Thread(target=worker, daemon=True).start()


def read_power_summary_sync() -> dict:
    """Lee perfil, gráficos y brillo de pantalla de forma síncrona (para --status)."""
    summary: dict = {
        "power_profile": "desconocido",
        "graphics_mode": "desconocido",
        "backlight": find_backlight_device(),
        "cpu_power": read_cpu_power_state(),
    }
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        res = bus.call_sync(
            SYS_POWER_BUS,
            SYS_POWER_PATH,
            SYS_POWER_IFACE,
            "GetProfile",
            None,
            GLib.VariantType("(s)"),
            Gio.DBusCallFlags.NONE,
            1500,
            None,
        )
        summary["power_profile"] = normalize_power_profile(res.unpack()[0])
        res_g = bus.call_sync(
            SYS_POWER_BUS,
            SYS_POWER_PATH,
            SYS_POWER_IFACE,
            "GetGraphics",
            None,
            GLib.VariantType("(s)"),
            Gio.DBusCallFlags.NONE,
            1500,
            None,
        )
        summary["graphics_mode"] = res_g.unpack()[0]
    except Exception:
        pass
    return summary
