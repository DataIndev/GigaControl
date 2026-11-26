"""Cliente D-Bus para el daemon del sistema gigactld."""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "io.github.smairio.gigactl"
OBJECT_PATH = "/io/github/smairio/gigactl"
INTERFACE = "io.github.smairio.gigactl.Control"


@dataclass(frozen=True)
class Telemetry:
    cpu_temp: int
    gpu_temp: int
    fan1_rpm: int
    fan2_rpm: int
    fan1_duty_pct: int
    fan2_duty_pct: int

    @classmethod
    def from_tuple(cls, values) -> Telemetry:
        if len(values) != 6:
            raise ValueError(f"se esperaban 6 campos de telemetría, se recibieron {len(values)}")
        return cls(*(int(v) for v in values))


@dataclass(frozen=True)
class KeyboardSnapshot:
    enabled: bool
    r: int
    g: int
    b: int
    brightness_pct: int

    @classmethod
    def from_tuple(cls, values) -> KeyboardSnapshot:
        if len(values) != 5:
            raise ValueError(f"se esperaban 5 campos de teclado, se recibieron {len(values)}")
        enabled, r, g, b, pct = values
        return cls(bool(enabled), int(r), int(g), int(b), int(pct))

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)

    @property
    def hex_color(self) -> str:
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"


@dataclass(frozen=True)
class CurveSnapshot:
    linked: bool
    cpu: list[tuple[int, int]]
    gpu: list[tuple[int, int]]

    @classmethod
    def from_tuple(cls, values) -> CurveSnapshot:
        if len(values) != 3:
            raise ValueError(f"se esperaban 3 campos de curvas, se recibieron {len(values)}")
        linked, cpu, gpu = values
        return cls(
            bool(linked),
            [(int(t), int(d)) for t, d in cpu],
            [(int(t), int(d)) for t, d in gpu],
        )


def translate_dbus_error(raw_message: str) -> str:
    msg = (raw_message or "").strip()
    low = msg.lower()
    if "notauthorized" in low or "not authorized" in low:
        return "Autorización denegada por PolicyKit para controlar el hardware."
    if "ecnotwritable" in low or "read-only" in low:
        return (
            "El controlador EC está en modo solo lectura. Recarga el módulo con "
            "'sudo modprobe -r ec_sys && sudo modprobe ec_sys write_support=1'."
        )
    if "writerejected" in low or "reverted" in low:
        return "El ventilador rechazó la velocidad indicada y volvió automáticamente al modo BIOS."
    if "serviceunknown" in low or "namehasnoowner" in low or "not provided by any .service" in low:
        return "El servicio gigactld no está en ejecución."
    if not msg:
        return "Error de comunicación con el servicio gigactld."
    if ":" in msg:
        # Extraer mensaje humano detrás del prefijo GDBus.Error:...
        parts = msg.split(":", 2)
        if len(parts) == 3 and parts[2].strip():
            return parts[2].strip()
    return msg


class GigactlClient:
    """Cliente asíncrono sobre D-Bus del sistema para hablar con gigactld."""

    def __init__(
        self,
        on_telemetry: Callable[[Telemetry], None] | None = None,
        on_availability: Callable[[bool], None] | None = None,
        on_state: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_telemetry = on_telemetry
        self._on_availability = on_availability
        self._on_state = on_state
        self._on_error = on_error
        self._proxy: Gio.DBusProxy | None = None
        self._last_telemetry: Telemetry | None = None

    def start(self) -> None:
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            None,
            self._on_proxy_ready,
        )

    def _on_proxy_ready(self, _source, result) -> None:
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as exc:
            self._report(translate_dbus_error(exc.message))
            self._notify_availability()
            return

        self._proxy.connect("g-signal", self._on_signal)
        self._proxy.connect("notify::g-name-owner", self._on_owner_changed)
        self._proxy.connect("g-properties-changed", lambda *_: self._notify_state())

        self._notify_availability()
        self._pull_initial_telemetry()
        self._notify_state()

    def _on_owner_changed(self, *_args) -> None:
        self._notify_availability()
        if self.available:
            self._pull_initial_telemetry()
            self._notify_state()

    def _pull_initial_telemetry(self) -> None:
        if not self.available or self._proxy is None:
            return
        v = self._proxy.get_cached_property("Telemetry")
        if v is not None:
            try:
                t = Telemetry.from_tuple(v.unpack())
                self._last_telemetry = t
                if self._on_telemetry:
                    self._on_telemetry(t)
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return bool(self._proxy and self._proxy.get_name_owner())

    @property
    def last_telemetry(self) -> Telemetry | None:
        return self._last_telemetry

    def _notify_availability(self) -> None:
        if self._on_availability:
            try:
                self._on_availability(self.available)
            except Exception as exc:
                print(f"gigactl_client availability err: {exc}", flush=True)

    def _notify_state(self) -> None:
        if self._on_state:
            try:
                self._on_state()
            except Exception as exc:
                print(f"gigactl_client state err: {exc}", flush=True)

    def daemon_version(self) -> str:
        if not self._proxy:
            return ""
        v = self._proxy.get_cached_property("DaemonVersion")
        return v.get_string() if v is not None else ""

    def active_profile(self) -> str | None:
        if not self._proxy:
            return None
        v = self._proxy.get_cached_property("ActiveProfile")
        return v.get_string() if v is not None else None

    def ec_status(self) -> str:
        if not self._proxy:
            return ""
        v = self._proxy.get_cached_property("EcStatus")
        return v.get_string() if v is not None else ""

    def keyboard_state(self) -> KeyboardSnapshot | None:
        if not self._proxy:
            return None
        v = self._proxy.get_cached_property("KeyboardState")
        if v is None:
            return None
        try:
            return KeyboardSnapshot.from_tuple(v.unpack())
        except (ValueError, TypeError):
            return None

    def curves(self) -> CurveSnapshot | None:
        if not self._proxy:
            return None
        v = self._proxy.get_cached_property("Curves")
        if v is None:
            return None
        try:
            return CurveSnapshot.from_tuple(v.unpack())
        except (ValueError, TypeError):
            return None

    def set_profile(self, name: str) -> None:
        self._call("SetProfile", GLib.Variant("(s)", (name,)))

    def set_fan_duty(self, fan: int, percent: int) -> None:
        self._call("SetFanDuty", GLib.Variant("(uu)", (int(fan), int(percent))))

    def set_curve(self, which: str, points: list[tuple[int, int]], linked: bool) -> None:
        self._call("SetCurve", GLib.Variant("(sa(uu)b)", (which, points, linked)))

    def restore_firmware(self) -> None:
        self._call("RestoreFirmware", None)

    def set_keyboard_color(self, r: int, g: int, b: int) -> None:
        self._call("SetKeyboardColor", GLib.Variant("(uuu)", (int(r), int(g), int(b))))

    def set_keyboard_brightness(self, percent: int) -> None:
        self._call("SetKeyboardBrightness", GLib.Variant("(u)", (int(percent),)))

    def set_keyboard_enabled(self, on: bool) -> None:
        self._call("SetKeyboardEnabled", GLib.Variant("(b)", (bool(on),)))

    def start_service(self, on_done: Callable[[bool, str], None] | None = None) -> None:
        """Intenta iniciar gigactl.service usando pkexec systemctl start gigactl."""
        def worker() -> None:
            try:
                proc = subprocess.run(
                    ["pkexec", "systemctl", "start", "gigactl"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                ok = proc.returncode == 0
                msg = "" if ok else (proc.stderr.strip() or "No se pudo iniciar gigactl.service.")
            except Exception as exc:
                ok = False
                msg = str(exc)
            if on_done:
                GLib.idle_add(on_done, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _call(self, method: str, params: GLib.Variant | None) -> None:
        if not self.available or self._proxy is None:
            self._report("El servicio gigactld no está activo. Inícialo para controlar ventiladores y teclado.")
            return
        self._proxy.call(
            method,
            params,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_call_done,
            method,
        )

    def _on_call_done(self, proxy, result, _method) -> None:
        try:
            proxy.call_finish(result)
        except GLib.Error as exc:
            self._report(translate_dbus_error(exc.message))
        except Exception as exc:
            self._report(str(exc))

    def _report(self, message: str) -> None:
        if self._on_error:
            self._on_error(message)

    def _on_signal(self, _proxy, _sender, signal_name, params) -> None:
        if signal_name != "Telemetry":
            return
        try:
            t = Telemetry.from_tuple(params.unpack())
            self._last_telemetry = t
            if self._on_telemetry:
                self._on_telemetry(t)
        except Exception:
            pass


def read_snapshot_sync() -> dict:
    """Lee el estado completo del daemon gigactl de forma síncrona (para --status)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            None,
        )
        if not proxy.get_name_owner():
            return {"available": False}
        tel_v = proxy.get_cached_property("Telemetry")
        if tel_v is None:
            res = bus.call_sync(
                BUS_NAME,
                OBJECT_PATH,
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", (INTERFACE, "Telemetry")),
                GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            tel_v = res.get_child_value(0).get_variant()
        telemetry = Telemetry.from_tuple(tel_v.unpack()) if tel_v else None
        kbd_v = proxy.get_cached_property("KeyboardState")
        prof_v = proxy.get_cached_property("ActiveProfile")
        ec_v = proxy.get_cached_property("EcStatus")
        ver_v = proxy.get_cached_property("DaemonVersion")
        curves_v = proxy.get_cached_property("Curves")
        return {
            "available": True,
            "version": ver_v.get_string() if ver_v else "",
            "profile": prof_v.get_string() if prof_v else "firmware",
            "ec_status": ec_v.get_string() if ec_v else "",
            "telemetry": telemetry,
            "keyboard": KeyboardSnapshot.from_tuple(kbd_v.unpack()) if kbd_v else None,
            "curves": CurveSnapshot.from_tuple(curves_v.unpack()) if curves_v else None,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}
