"""Punto de entrada CLI y GUI de GigaControl Center."""
from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__
from .backend import curves_math, gigactl_client, hotkeys, power_client, sysinfo


def _print_status() -> int:
    hw = sysinfo.read_hardware_info()
    sys_m = sysinfo.read_system_metrics()
    gpu_m = sysinfo.read_nvidia_sync()
    giga = gigactl_client.read_snapshot_sync()
    pwr = power_client.read_power_summary_sync()

    print(f"=== {APP_NAME} v{__version__} ===")
    print(f"Equipo       : {hw.vendor} {hw.product_name} (soporte: {hw.support_level})")
    print(f"Procesador   : {hw.cpu_model} ({sys_m.cpu_freq_mhz:.0f} MHz, uso {sys_m.cpu_percent:.0f}%)")
    print(f"Memoria RAM  : {sys_m.ram_used_gb:.1f} / {sys_m.ram_total_gb:.1f} GB ({sys_m.ram_percent:.0f}%)")

    if giga.get("available"):
        tel = giga.get("telemetry")
        kbd = giga.get("keyboard")
        prof = giga.get("profile", "firmware")
        print(f"gigactld     : activo v{giga.get('version', '?')} | perfil ventiladores: {curves_math.profile_label_es(prof)}")
        if tel is not None:
            print(f"Termicas/Fan : CPU {tel.cpu_temp}°C ({tel.fan1_rpm} RPM, {tel.fan1_duty_pct}%) | GPU {tel.gpu_temp}°C ({tel.fan2_rpm} RPM, {tel.fan2_duty_pct}%)")
        if kbd is not None:
            st = "Encendido" if kbd.enabled else "Apagado"
            print(f"Teclado RGB  : {st} | color {kbd.hex_color} | brillo {kbd.brightness_pct}%")
        if giga.get("ec_status"):
            print(f"Estado EC    : {giga['ec_status']}")
    else:
        print("gigactld     : NO disponible en D-Bus")

    if gpu_m.available:
        print(f"GPU NVIDIA   : {gpu_m.name} | {gpu_m.temp_c}°C | {gpu_m.power_w:.1f} W | {gpu_m.clock_gfx_mhz} MHz | {gpu_m.pstate}")

    bl = pwr.get("backlight")
    bl_txt = f"{bl.percent}% ({bl.device})" if bl else "no detectado"
    cpu_p = pwr.get("cpu_power")
    turbo_txt = "ON" if (cpu_p and cpu_p.turbo_enabled) else "OFF"
    print(f"Energía OS   : perfil={pwr.get('power_profile')} | gráficos={pwr.get('graphics_mode')} | brillo={bl_txt}")
    if cpu_p and cpu_p.pstate_available:
        print(f"Intel PState : Turbo={turbo_txt} | max_perf={cpu_p.max_perf_pct}% | governor={cpu_p.governor} | EPP={cpu_p.epp}")

    cosmic_hk = "Activos" if hotkeys.are_cosmic_shortcuts_installed() else "No configurados"
    fn_drv = "Activo" if hotkeys.is_kernel_hotkey_driver_loaded() else "No cargado (opcional)"
    print(f"Teclas Rápid : Atajos COSMIC={cosmic_hk} | Driver Fn WMI={fn_drv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gigabyte-control-center", description=f"{APP_NAME} para laptops Gigabyte")
    parser.add_argument("--version", action="store_true", help="Muestra la versión e inmediatamente sale")
    parser.add_argument("--status", action="store_true", help="Muestra el estado completo del hardware en consola")
    parser.add_argument("--smoke-test", action="store_true", help="Abre la GUI, verifica las pantallas y sale")
    parser.add_argument(
        "--page",
        default="dashboard",
        choices=["dashboard", "keyboard", "fans", "performance", "power"],
        help="Página inicial al abrir la aplicación",
    )

    parser.add_argument("--kbd-toggle", action="store_true", help="Alterna encendido/apagado de la luz del teclado")
    parser.add_argument("--kbd-up", action="store_true", help="Sube el brillo del teclado un paso (+20%)")
    parser.add_argument("--kbd-down", action="store_true", help="Baja el brillo del teclado un paso (-20%)")
    parser.add_argument("--kbd-color-next", action="store_true", help="Cambia al siguiente color RGB del teclado")
    parser.add_argument("--kbd-color", metavar="COLOR", help="Fija un color RGB por nombre o hex (#FF6B00)")
    parser.add_argument("--kbd-brightness", type=int, metavar="PCT", help="Fija el brillo del teclado (0..100)")
    parser.add_argument("--no-notify", action="store_true", help="No mostrar notificación OSD al usar --kbd-*")
    parser.add_argument("--install-hotkeys", action="store_true", help="Configura los atajos globales de iluminación en COSMIC")
    parser.add_argument("--remove-hotkeys", action="store_true", help="Elimina los atajos de GigaControl en COSMIC")

    args, remaining = parser.parse_known_args(argv)

    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0
    if args.status:
        return _print_status()

    if args.install_hotkeys:
        p = hotkeys.install_cosmic_shortcuts()
        print(f"Atajos globales COSMIC instalados en: {p}")
        return 0
    if args.remove_hotkeys:
        removed = hotkeys.remove_cosmic_shortcuts()
        print("Atajos globales de GigaControl eliminados." if removed else "No existían atajos instalados.")
        return 0

    notify = not args.no_notify
    if args.kbd_toggle:
        ok, msg = hotkeys.run_hotkey_action("toggle", notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.kbd_up:
        ok, msg = hotkeys.run_hotkey_action("up", notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.kbd_down:
        ok, msg = hotkeys.run_hotkey_action("down", notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.kbd_color_next:
        ok, msg = hotkeys.run_hotkey_action("color-next", notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.kbd_color is not None:
        ok, msg = hotkeys.run_hotkey_action("color", arg=args.kbd_color, notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if args.kbd_brightness is not None:
        ok, msg = hotkeys.run_hotkey_action("brightness", arg=str(args.kbd_brightness), notify=notify)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    from .app import GigaControlApp

    app = GigaControlApp(initial_page=args.page, smoke_test=args.smoke_test)
    return app.run([sys.argv[0], *remaining])


if __name__ == "__main__":
    raise SystemExit(main())
