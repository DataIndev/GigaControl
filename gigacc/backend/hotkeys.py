"""Acciones rápidas de iluminación del teclado, OSD y gestor de atajos COSMIC."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import gigactl_client  # noqa: E402

RGB = tuple[int, int, int]

RGB_PALETTE: tuple[tuple[str, RGB], ...] = (
    ("Naranja Gigabyte", (255, 107, 0)),
    ("Azul", (0, 0, 255)),
    ("Cian", (0, 210, 255)),
    ("Rojo", (255, 0, 0)),
    ("Verde", (0, 255, 0)),
    ("Lima", (140, 255, 0)),
    ("Amarillo", (255, 200, 0)),
    ("Púrpura", (160, 0, 255)),
    ("Rosa", (255, 0, 128)),
    ("Turquesa", (0, 220, 160)),
    ("Ámbar", (255, 150, 0)),
    ("Blanco", (255, 255, 255)),
)

_COLOR_ALIASES: dict[str, tuple[str, RGB]] = {
    "naranja": ("Naranja Gigabyte", (255, 107, 0)),
    "orange": ("Naranja Gigabyte", (255, 107, 0)),
    "gigabyte": ("Naranja Gigabyte", (255, 107, 0)),
    "azul": ("Azul", (0, 0, 255)),
    "blue": ("Azul", (0, 0, 255)),
    "cian": ("Cian", (0, 210, 255)),
    "cyan": ("Cian", (0, 210, 255)),
    "rojo": ("Rojo", (255, 0, 0)),
    "red": ("Rojo", (255, 0, 0)),
    "verde": ("Verde", (0, 255, 0)),
    "green": ("Verde", (0, 255, 0)),
    "lima": ("Lima", (140, 255, 0)),
    "lime": ("Lima", (140, 255, 0)),
    "amarillo": ("Amarillo", (255, 200, 0)),
    "yellow": ("Amarillo", (255, 200, 0)),
    "purpura": ("Púrpura", (160, 0, 255)),
    "púrpura": ("Púrpura", (160, 0, 255)),
    "purple": ("Púrpura", (160, 0, 255)),
    "rosa": ("Rosa", (255, 0, 128)),
    "pink": ("Rosa", (255, 0, 128)),
    "turquesa": ("Turquesa", (0, 220, 160)),
    "ambar": ("Ámbar", (255, 150, 0)),
    "ámbar": ("Ámbar", (255, 150, 0)),
    "blanco": ("Blanco", (255, 255, 255)),
    "white": ("Blanco", (255, 255, 255)),
}

BRIGHTNESS_STEPS: tuple[int, ...] = (0, 20, 40, 60, 80, 100)

COSMIC_CUSTOM_SHORTCUTS_PATH = (
    Path.home() / ".config" / "cosmic" / "com.system76.CosmicSettings.Shortcuts" / "v1" / "custom"
)

_GIGACC_START_MARKER = "// BEGIN GIGACONTROL SHORTCUTS"
_GIGACC_END_MARKER = "// END GIGACONTROL SHORTCUTS"

HOTKEY_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("Alternar encendido/apagado", "Fn + /  o  Super + Alt + /", "--kbd-toggle"),
    ("Subir brillo (+20%)", "Fn + +  o  Super + Alt + +", "--kbd-up"),
    ("Bajar brillo (-20%)", "Fn + -  o  Super + Alt + -", "--kbd-down"),
    ("Cambiar color RGB", "Fn + *  o  Super + Alt + *", "--kbd-color-next"),
)


def name_for_rgb(rgb: RGB) -> str:
    target = tuple(int(c) for c in rgb)
    for name, val in RGB_PALETTE:
        if val == target:
            return name
    return f"#{target[0]:02X}{target[1]:02X}{target[2]:02X}"


def compute_next_brightness_up(enabled: bool, current_pct: int) -> tuple[bool, int]:
    cur = max(0, min(100, int(current_pct)))
    if not enabled or cur == 0:
        return True, 20
    for step in BRIGHTNESS_STEPS:
        if step > cur:
            return True, step
    return True, 100


def compute_next_brightness_down(enabled: bool, current_pct: int) -> tuple[bool, int]:
    cur = max(0, min(100, int(current_pct)))
    if not enabled or cur <= 0:
        return False, 0
    for step in reversed(BRIGHTNESS_STEPS):
        if step < cur:
            return (step > 0), step
    return False, 0


def compute_toggle(enabled: bool, current_pct: int) -> tuple[bool, int]:
    cur = max(0, min(100, int(current_pct)))
    if enabled:
        return False, cur
    return True, (cur if cur > 0 else 60)


def compute_next_color(current_rgb: RGB) -> tuple[str, RGB]:
    cur = tuple(max(0, min(255, int(c))) for c in current_rgb)
    for idx, (_name, val) in enumerate(RGB_PALETTE):
        if val == cur:
            return RGB_PALETTE[(idx + 1) % len(RGB_PALETTE)]
    return RGB_PALETTE[0]


def parse_color_arg(value: str) -> tuple[str, RGB]:
    raw = (value or "").strip()
    low = raw.lower()
    if low in _COLOR_ALIASES:
        return _COLOR_ALIASES[low]
    for name, rgb in RGB_PALETTE:
        if name.lower() == low:
            return name, rgb
    cleaned = raw.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
        rgb = (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))
        return name_for_rgb(rgb), rgb
    raise ValueError(f"Color inválido '{value}'. Usa un nombre (ej. rojo, cian, naranja) o hex (#FF6B00).")


def _notify_osd(title: str, body: str) -> None:
    """Muestra notificación OSD reemplazable en sesión gráfica vía D-Bus."""
    id_file = Path(f"/tmp/gigacontrol-notify-{os.getuid()}.id")
    replaces_id = 0
    try:
        txt = id_file.read_text(encoding="utf-8").strip()
        if txt.isdigit():
            replaces_id = int(txt)
    except OSError:
        pass

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {
            "transient": GLib.Variant("b", True),
            "x-canonical-private-synchronous": GLib.Variant("s", "gigacontrol-kbd"),
        }
        res = bus.call_sync(
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "Notify",
            GLib.Variant(
                "(susssasa{sv}i)",
                (
                    "GigaControl Center",
                    replaces_id,
                    "keyboard-brightness-symbolic",
                    title,
                    body,
                    [],
                    hints,
                    1500,
                ),
            ),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        new_id = int(res.unpack()[0])
        try:
            id_file.write_text(str(new_id), encoding="utf-8")
        except OSError:
            pass
    except Exception:
        pass


def _dbus_call_gigactl(bus: Gio.DBusConnection, method: str, params: GLib.Variant | None) -> None:
    bus.call_sync(
        gigactl_client.BUS_NAME,
        gigactl_client.OBJECT_PATH,
        gigactl_client.INTERFACE,
        method,
        params,
        None,
        Gio.DBusCallFlags.NONE,
        3000,
        None,
    )


def run_hotkey_action(action: str, arg: str | None = None, notify: bool = True) -> tuple[bool, str]:
    """Ejecuta una acción rápida de iluminación contra gigactld en <60 ms."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        prop_res = bus.call_sync(
            gigactl_client.BUS_NAME,
            gigactl_client.OBJECT_PATH,
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", (gigactl_client.INTERFACE, "KeyboardState")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        kbd = gigactl_client.KeyboardSnapshot.from_tuple(prop_res.get_child_value(0).get_variant().unpack())
    except GLib.Error as exc:
        msg = gigactl_client.translate_dbus_error(exc.message)
        if notify:
            _notify_osd("Teclado RGB", msg)
        return False, msg
    except Exception as exc:
        msg = str(exc)
        if notify:
            _notify_osd("Teclado RGB", msg)
        return False, msg

    try:
        if action == "toggle":
            new_on, new_pct = compute_toggle(kbd.enabled, kbd.brightness_pct)
            if new_on:
                _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (True,)))
                if new_pct != kbd.brightness_pct:
                    _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (new_pct,)))
                msg = f"Iluminación encendida ({new_pct}% · {name_for_rgb(kbd.rgb)})"
            else:
                _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (False,)))
                msg = "Iluminación apagada"
        elif action == "up":
            new_on, new_pct = compute_next_brightness_up(kbd.enabled, kbd.brightness_pct)
            if not kbd.enabled:
                _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (True,)))
            _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (new_pct,)))
            msg = f"Brillo del teclado: {new_pct}%"
        elif action == "down":
            new_on, new_pct = compute_next_brightness_down(kbd.enabled, kbd.brightness_pct)
            if new_on:
                _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (new_pct,)))
                msg = f"Brillo del teclado: {new_pct}%"
            else:
                _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (0,)))
                _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (False,)))
                msg = "Iluminación apagada (0%)"
        elif action == "color-next":
            cname, (r, g, b) = compute_next_color(kbd.rgb)
            _dbus_call_gigactl(bus, "SetKeyboardColor", GLib.Variant("(uuu)", (r, g, b)))
            msg = f"Color del teclado: {cname} (#{r:02X}{g:02X}{b:02X})"
        elif action == "color":
            cname, (r, g, b) = parse_color_arg(arg or "")
            _dbus_call_gigactl(bus, "SetKeyboardColor", GLib.Variant("(uuu)", (r, g, b)))
            msg = f"Color del teclado: {cname} (#{r:02X}{g:02X}{b:02X})"
        elif action == "brightness":
            pct = max(0, min(100, int(arg or "0")))
            if pct == 0:
                _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (0,)))
                _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (False,)))
                msg = "Iluminación apagada (0%)"
            else:
                if not kbd.enabled:
                    _dbus_call_gigactl(bus, "SetKeyboardEnabled", GLib.Variant("(b)", (True,)))
                _dbus_call_gigactl(bus, "SetKeyboardBrightness", GLib.Variant("(u)", (pct,)))
                msg = f"Brillo del teclado: {pct}%"
        else:
            return False, f"Acción desconocida: {action}"
    except GLib.Error as exc:
        msg = gigactl_client.translate_dbus_error(exc.message)
        if notify:
            _notify_osd("Teclado RGB", msg)
        return False, msg
    except Exception as exc:
        msg = str(exc)
        if notify:
            _notify_osd("Teclado RGB", msg)
        return False, msg

    if notify:
        _notify_osd("Teclado RGB", msg)
    return True, msg


def _default_binary_path() -> str:
    local_bin = Path.home() / ".local" / "bin" / "gigabyte-control-center"
    if local_bin.is_file():
        return str(local_bin)
    found = shutil.which("gigabyte-control-center")
    if found:
        return found
    return str(local_bin)


def _cosmic_entries_block(binary_path: str) -> list[str]:
    esc_bin = binary_path.replace("\\", "\\\\").replace('"', '\\"')
    entries = [
        ([], "XF86KbdLightOnOff", "GigaControl: Alternar luz del teclado", "--kbd-toggle"),
        ([], "XF86KbdBrightnessUp", "GigaControl: Subir brillo del teclado", "--kbd-up"),
        ([], "XF86KbdBrightnessDown", "GigaControl: Bajar brillo del teclado", "--kbd-down"),
        ([], "XF86Launch1", "GigaControl: Cambiar color RGB del teclado", "--kbd-color-next"),
        (["Super", "Alt"], "KP_Divide", "GigaControl: Alternar luz del teclado (NumPad)", "--kbd-toggle"),
        (["Super", "Alt"], "KP_Add", "GigaControl: Subir brillo del teclado (NumPad)", "--kbd-up"),
        (["Super", "Alt"], "KP_Subtract", "GigaControl: Bajar brillo del teclado (NumPad)", "--kbd-down"),
        (["Super", "Alt"], "KP_Multiply", "GigaControl: Cambiar color RGB del teclado (NumPad)", "--kbd-color-next"),
    ]
    lines = [f"    {_GIGACC_START_MARKER}"]
    for mods, key, desc, flag in entries:
        mods_str = ", ".join(mods)
        lines.append(
            f'    (modifiers: [{mods_str}], key: "{key}", description: Some("{desc}")): '
            f'Spawn("{esc_bin} {flag}"),'
        )
    lines.append(f"    {_GIGACC_END_MARKER}")
    return lines


def _strip_gigacontrol_ron_entries(existing_text: str) -> list[str]:
    """Devuelve las líneas internas de un mapa RON sin las entradas de GigaControl."""
    text = (existing_text or "").strip()
    if not text:
        return []
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1]
    else:
        inner = text

    kept: list[str] = []
    in_block = False
    for raw_line in inner.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == _GIGACC_START_MARKER:
            in_block = True
            continue
        if stripped == _GIGACC_END_MARKER:
            in_block = False
            continue
        if in_block:
            continue
        if not stripped:
            continue
        if "GigaControl:" in line or "gigabyte-control-center --kbd-" in line:
            continue
        kept.append(line)

    # Asegurar coma final en la última entrada de usuario si se van a añadir más
    return kept


def merge_cosmic_shortcuts_ron(existing_text: str, binary_path: str) -> str:
    kept = _strip_gigacontrol_ron_entries(existing_text)
    if kept:
        # Asegurar coma al final de la última línea no-comentario
        for i in range(len(kept) - 1, -1, -1):
            s = kept[i].strip()
            if s and not s.startswith("//"):
                if not s.endswith(","):
                    kept[i] = kept[i] + ","
                break
    block = _cosmic_entries_block(binary_path)
    all_lines = ["{", *kept, *block, "}"]
    return "\n".join(all_lines) + "\n"


def remove_cosmic_shortcuts_ron(existing_text: str) -> str:
    kept = _strip_gigacontrol_ron_entries(existing_text)
    if not kept:
        return "{\n}\n"
    return "{\n" + "\n".join(kept) + "\n}\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".custom-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def install_cosmic_shortcuts(
    binary_path: str | None = None,
    shortcuts_path: Path = COSMIC_CUSTOM_SHORTCUTS_PATH,
) -> Path:
    existing = ""
    if shortcuts_path.is_file():
        existing = shortcuts_path.read_text(encoding="utf-8", errors="ignore")
    bin_path = binary_path or _default_binary_path()
    merged = merge_cosmic_shortcuts_ron(existing, bin_path)
    _atomic_write(shortcuts_path, merged)
    return shortcuts_path


def remove_cosmic_shortcuts(shortcuts_path: Path = COSMIC_CUSTOM_SHORTCUTS_PATH) -> bool:
    if not shortcuts_path.is_file():
        return False
    existing = shortcuts_path.read_text(encoding="utf-8", errors="ignore")
    cleaned = remove_cosmic_shortcuts_ron(existing)
    _atomic_write(shortcuts_path, cleaned)
    return True


def are_cosmic_shortcuts_installed(shortcuts_path: Path = COSMIC_CUSTOM_SHORTCUTS_PATH) -> bool:
    if not shortcuts_path.is_file():
        return False
    text = shortcuts_path.read_text(encoding="utf-8", errors="ignore")
    return _GIGACC_START_MARKER in text or "gigabyte-control-center --kbd-" in text


def is_kernel_hotkey_driver_loaded() -> bool:
    return Path("/sys/module/gigactl_hotkeys").is_dir()


def find_hotkey_driver_installer() -> Path | None:
    env_dir = os.environ.get("GIGACC_DATA_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir) / "install-hotkeys-driver.sh")
    candidates.extend([
        Path.home() / ".local" / "share" / "gigabyte-control-center" / "install-hotkeys-driver.sh",
        Path(__file__).resolve().parents[2] / "scripts" / "install-hotkeys-driver.sh",
    ])
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def install_kernel_hotkey_driver_async(on_done: Callable[[bool, str], None]) -> None:
    installer = find_hotkey_driver_installer()
    if installer is None:
        GLib.idle_add(on_done, False, "No se encontró scripts/install-hotkeys-driver.sh.")
        return

    def worker() -> None:
        try:
            proc = subprocess.run(
                ["pkexec", "bash", str(installer)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            ok = proc.returncode == 0
            msg = (
                "Driver WMI gigactl_hotkeys instalado y activo. Ya puedes usar Fn + teclado numérico."
                if ok
                else (proc.stderr.strip() or proc.stdout.strip() or "No se pudo instalar el driver Fn.")
            )
        except Exception as exc:
            ok = False
            msg = str(exc)
        GLib.idle_add(on_done, ok, msg)

    threading.Thread(target=worker, daemon=True).start()
