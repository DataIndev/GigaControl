"""Página Panel General (Dashboard): vista rápida estilo Gigabyte Control Center."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from ..backend import curves_math  # noqa: E402
from ..backend.gigactl_client import GigactlClient, Telemetry  # noqa: E402
from ..backend.power_client import BacklightInfo, PowerClient  # noqa: E402
from ..backend.sysinfo import HardwareInfo, NvidiaMetrics, SystemMetrics  # noqa: E402
from ..widgets.gauge import RadialGauge  # noqa: E402

# (id_escenario, titulo, subtitulo, icono, perfil_fan, perfil_energia)
SCENARIOS = [
    ("quiet", "Silencioso", "Mínimo ruido", "weather-clear-night-symbolic", "quiet", "battery"),
    ("balanced", "Equilibrado", "Uso diario", "power-profile-balanced-symbolic", "balanced", "balanced"),
    ("gaming", "Gaming", "Refrigeración activa", "power-profile-performance-symbolic", "performance", "performance"),
    ("turbo", "Turbo Máx", "Ventiladores 100%", "weather-windy-symbolic", "max", "performance"),
    ("firmware", "Auto BIOS", "Control de fábrica", "emblem-system-symbolic", "firmware", "balanced"),
]


class DashboardPage(Gtk.ScrolledWindow):
    """Vista resumen con telemetría en tiempo real y accesos rápidos."""

    def __init__(
        self,
        gigactl: GigactlClient,
        power: PowerClient,
        hw: HardwareInfo,
        on_toast: Callable[[str], None],
        on_navigate: Callable[[str], None],
    ) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._gigactl = gigactl
        self._power = power
        self._hw = hw
        self._on_toast = on_toast
        self._on_navigate = on_navigate
        self._syncing = False
        self._brightness_debounce = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20)
        root.set_margin_bottom(22)
        root.set_margin_start(22)
        root.set_margin_end(22)

        # Cabecera
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label="Panel General", xalign=0.0)
        title.add_css_class("gcc-page-title")
        sub = Gtk.Label(
            label=f"{hw.vendor} {hw.product_name}  ·  {hw.cpu_model}",
            xalign=0.0,
            wrap=True,
        )
        sub.add_css_class("gcc-muted")
        title_box.append(title)
        title_box.append(sub)
        header.append(title_box)

        self._daemon_pill = Gtk.Label(label="Conectando…", valign=Gtk.Align.CENTER)
        self._daemon_pill.add_css_class("gcc-pill")
        self._daemon_pill.add_css_class("gcc-pill-warn")
        header.append(self._daemon_pill)
        root.append(header)

        # Banner condicional de advertencia / servicio caído
        self._banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._banner.add_css_class("gcc-banner-warn")
        self._banner.set_visible(False)
        banner_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self._banner_label = Gtk.Label(xalign=0.0, wrap=True, hexpand=True)
        self._start_daemon_btn = Gtk.Button(label="Iniciar gigactld")
        self._start_daemon_btn.add_css_class("gcc-accent-btn")
        self._start_daemon_btn.connect("clicked", self._on_start_daemon_clicked)
        self._banner.append(banner_icon)
        self._banner.append(self._banner_label)
        self._banner.append(self._start_daemon_btn)
        root.append(self._banner)

        # Escenarios rápidos tipo Gigabyte Control Center
        scen_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scen_card.add_css_class("gcc-card")
        scen_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        scen_title = Gtk.Label(label="ESCENARIOS RÁPIDOS DE CONTROL", xalign=0.0, hexpand=True)
        scen_title.add_css_class("gcc-eyebrow")
        scen_hint = Gtk.Label(label="Combina ventiladores y perfil de energía", xalign=1.0)
        scen_hint.add_css_class("gcc-muted")
        scen_hdr.append(scen_title)
        scen_hdr.append(scen_hint)
        scen_card.append(scen_hdr)

        scen_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        self._scenario_buttons: dict[str, Gtk.ToggleButton] = {}
        group: Gtk.ToggleButton | None = None
        for sid, label, desc, icon_name, fan_prof, pwr_prof in SCENARIOS:
            btn = Gtk.ToggleButton()
            btn.add_css_class("gcc-mode-btn")
            if sid == "firmware":
                btn.add_css_class("firmware")
            if group is None:
                group = btn
            else:
                btn.set_group(group)

            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.set_halign(Gtk.Align.CENTER)
            ico = Gtk.Image.new_from_icon_name(icon_name)
            ico.set_pixel_size(22)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("gcc-section-title")
            sub_lbl = Gtk.Label(label=desc)
            sub_lbl.add_css_class("gcc-muted")
            inner.append(ico)
            inner.append(lbl)
            inner.append(sub_lbl)
            btn.set_child(inner)
            btn.connect("toggled", self._on_scenario_toggled, sid, fan_prof, pwr_prof)
            scen_row.append(btn)
            self._scenario_buttons[sid] = btn
        scen_card.append(scen_row)
        root.append(scen_card)

        # 3 Tarjetas de telemetría principal
        grid_cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, homogeneous=True)

        # Tarjeta CPU
        cpu_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        cpu_card.add_css_class("gcc-card")
        cpu_eyebrow = Gtk.Label(label="PROCESADOR (CPU)", xalign=0.0)
        cpu_eyebrow.add_css_class("gcc-eyebrow")
        self._cpu_gauge = RadialGauge("CPU", "°C", max_value=100.0, semantic_temp=True)
        self._cpu_usage_lbl = Gtk.Label(label="Uso: — %  ·  Frecuencia: — MHz", xalign=0.5)
        self._cpu_usage_lbl.add_css_class("gcc-muted")
        self._cpu_fan_lbl = Gtk.Label(label="Ventilador 1: — RPM (— %)", xalign=0.5)
        self._cpu_fan_lbl.add_css_class("gcc-value-chip")
        cpu_card.append(cpu_eyebrow)
        cpu_card.append(self._cpu_gauge)
        cpu_card.append(self._cpu_usage_lbl)
        cpu_card.append(self._cpu_fan_lbl)
        grid_cards.append(cpu_card)

        # Tarjeta GPU
        gpu_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        gpu_card.add_css_class("gcc-card")
        gpu_eyebrow = Gtk.Label(label="GRÁFICOS (GPU)", xalign=0.0)
        gpu_eyebrow.add_css_class("gcc-eyebrow")
        self._gpu_gauge = RadialGauge("GPU", "°C", max_value=100.0, semantic_temp=True)
        self._gpu_stats_lbl = Gtk.Label(label="Carga: — %  ·  Consumo: — W", xalign=0.5)
        self._gpu_stats_lbl.add_css_class("gcc-muted")
        self._gpu_fan_lbl = Gtk.Label(label="Ventilador 2: — RPM (— %)", xalign=0.5)
        self._gpu_fan_lbl.add_css_class("gcc-value-chip")
        gpu_card.append(gpu_eyebrow)
        gpu_card.append(self._gpu_gauge)
        gpu_card.append(self._gpu_stats_lbl)
        gpu_card.append(self._gpu_fan_lbl)
        grid_cards.append(gpu_card)

        # Tarjeta Sistema + Accesos Rápidos
        sys_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sys_card.add_css_class("gcc-card")
        sys_eyebrow = Gtk.Label(label="SISTEMA Y ACCESOS RÁPIDOS", xalign=0.0)
        sys_eyebrow.add_css_class("gcc-eyebrow")
        sys_card.append(sys_eyebrow)

        self._ram_lbl = Gtk.Label(label="Memoria RAM: — / — GB", xalign=0.0)
        self._ram_lbl.add_css_class("gcc-muted")
        self._ram_bar = Gtk.ProgressBar()
        self._ram_bar.add_css_class("gcc-ram-bar")
        sys_card.append(self._ram_lbl)
        sys_card.append(self._ram_bar)

        self._profiles_summary = Gtk.Label(label="Ventiladores: —  ·  Energía: —", xalign=0.0, wrap=True)
        self._profiles_summary.add_css_class("gcc-muted")
        sys_card.append(self._profiles_summary)

        # Toggle rápido de teclado RGB
        kbd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        kbd_lbl = Gtk.Label(label="Luz teclado RGB", xalign=0.0, hexpand=True)
        self._kbd_color_chip = Gtk.Label(label="#0000FF")
        self._kbd_color_chip.add_css_class("gcc-value-chip")
        self._kbd_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._kbd_switch.connect("notify::active", self._on_quick_kbd_toggled)
        kbd_row.append(kbd_lbl)
        kbd_row.append(self._kbd_color_chip)
        kbd_row.append(self._kbd_switch)
        sys_card.append(kbd_row)

        # Slider rápido de brillo pantalla
        br_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        br_lbl = Gtk.Label(label="Brillo de pantalla", xalign=0.0, hexpand=True)
        self._br_val_lbl = Gtk.Label(label="— %")
        self._br_val_lbl.add_css_class("gcc-value-chip")
        br_hdr.append(br_lbl)
        br_hdr.append(self._br_val_lbl)
        sys_card.append(br_hdr)

        self._br_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self._br_scale.set_draw_value(False)
        self._br_scale.connect("value-changed", self._on_quick_brightness_changed)
        sys_card.append(self._br_scale)

        # Botones de acceso directo inferior
        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        btn_rgb = Gtk.Button(label="Configurar RGB")
        btn_rgb.connect("clicked", lambda *_: self._on_navigate("keyboard"))
        btn_fans = Gtk.Button(label="Curva Ventiladores")
        btn_fans.connect("clicked", lambda *_: self._on_navigate("fans"))
        actions_row.append(btn_rgb)
        actions_row.append(btn_fans)
        sys_card.append(actions_row)

        grid_cards.append(sys_card)
        root.append(grid_cards)

        # Barra inferior de seguridad
        footer_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer_card.add_css_class("gcc-card")
        foot_txt = Gtk.Label(
            label="Modo seguro: ante cualquier fallo o cierre, puedes devolver el control térmico al firmware del portátil con un clic.",
            xalign=0.0,
            wrap=True,
            hexpand=True,
        )
        foot_txt.add_css_class("gcc-muted")
        fw_btn = Gtk.Button(label="Restaurar Firmware Auto")
        fw_btn.connect("clicked", lambda *_: self._gigactl.restore_firmware())
        footer_card.append(foot_txt)
        footer_card.append(fw_btn)
        root.append(footer_card)

        self.set_child(root)

    def _on_start_daemon_clicked(self, btn: Gtk.Button) -> None:
        btn.set_sensitive(False)
        btn.set_label("Iniciando…")

        def done(ok: bool, msg: str) -> bool:
            btn.set_sensitive(True)
            btn.set_label("Iniciar gigactld")
            if ok:
                self._on_toast("Servicio gigactld iniciado correctamente.")
            else:
                self._on_toast(msg or "No se pudo iniciar gigactld.")
            return False

        self._gigactl.start_service(done)

    def _on_scenario_toggled(self, btn: Gtk.ToggleButton, _sid: str, fan_prof: str, pwr_prof: str) -> None:
        if self._syncing or not btn.get_active():
            return
        self._gigactl.set_profile(fan_prof)
        self._power.set_power_profile(pwr_prof)
        self._on_toast(f"Escenario aplicado: ventiladores '{curves_math.profile_label_es(fan_prof)}', energía '{pwr_prof}'.")

    def _on_quick_kbd_toggled(self, sw: Gtk.Switch, _pspec) -> None:
        if self._syncing:
            return
        self._gigactl.set_keyboard_enabled(sw.get_active())

    def _on_quick_brightness_changed(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        pct = int(round(scale.get_value()))
        self._br_val_lbl.set_label(f"{pct} %")
        if self._brightness_debounce:
            from gi.repository import GLib
            GLib.source_remove(self._brightness_debounce)
        from gi.repository import GLib

        def fire() -> bool:
            self._brightness_debounce = 0
            self._power.set_screen_brightness(pct)
            return False

        self._brightness_debounce = GLib.timeout_add(90, fire)

    def update_status(self, *, gigactl_ok: bool, ec_status: str, fan_profile: str | None, power_profile: str) -> None:
        if not gigactl_ok:
            self._daemon_pill.set_label("Servicio gigactl detenido")
            self._daemon_pill.set_css_classes(["gcc-pill", "gcc-pill-err"])
            self._banner_label.set_label(
                "El servicio del sistema gigactld no está activo. Inícialo para controlar los ventiladores y el teclado RGB."
            )
            self._start_daemon_btn.set_visible(True)
            self._banner.set_visible(True)
        elif ec_status:
            self._daemon_pill.set_label("Advertencia EC")
            self._daemon_pill.set_css_classes(["gcc-pill", "gcc-pill-warn"])
            self._banner_label.set_label(ec_status)
            self._start_daemon_btn.set_visible(False)
            self._banner.set_visible(True)
        else:
            self._daemon_pill.set_label("Hardware EC conectado")
            self._daemon_pill.set_css_classes(["gcc-pill", "gcc-pill-ok"])
            self._banner.set_visible(False)

        fan_txt = curves_math.profile_label_es(fan_profile) if fan_profile else "No disponible"
        pwr_map = {"battery": "Ahorro", "balanced": "Equilibrado", "performance": "Alto Rendimiento"}
        pwr_txt = pwr_map.get(power_profile, power_profile)
        self._profiles_summary.set_label(f"Ventiladores: {fan_txt}  ·  Energía: {pwr_txt}")

        # Sincronizar botón de escenario correspondiente si coincide
        self._syncing = True
        try:
            matched = None
            for sid, _lbl, _desc, _ico, f_p, _p_p in SCENARIOS:
                if fan_profile == f_p:
                    matched = sid
                    break
            for sid, btn in self._scenario_buttons.items():
                btn.set_active(sid == matched)

            kbd = self._gigactl.keyboard_state()
            if kbd is not None:
                self._kbd_switch.set_active(kbd.enabled)
                self._kbd_color_chip.set_label(f"{kbd.hex_color} · {kbd.brightness_pct}%" if kbd.enabled else "Apagado")
        finally:
            self._syncing = False

    def update_telemetry(self, t: Telemetry | None, sys_m: SystemMetrics, gpu_m: NvidiaMetrics) -> None:
        cpu_temp = t.cpu_temp if t is not None else sys_m.cpu_temp_fallback
        gpu_temp = t.gpu_temp if t is not None else (gpu_m.temp_c if gpu_m.available else None)

        self._cpu_gauge.set_reading(cpu_temp, f"{sys_m.cpu_percent:.0f}% uso")
        freq_txt = f"{sys_m.cpu_freq_mhz:.0f} MHz" if sys_m.cpu_freq_mhz > 0 else "— MHz"
        self._cpu_usage_lbl.set_label(f"Uso: {sys_m.cpu_percent:.0f} %  ·  {freq_txt}")

        if t is not None:
            self._cpu_fan_lbl.set_label(f"Ventilador 1: {t.fan1_rpm} RPM ({t.fan1_duty_pct} %)")
            self._gpu_fan_lbl.set_label(f"Ventilador 2: {t.fan2_rpm} RPM ({t.fan2_duty_pct} %)")
        else:
            self._cpu_fan_lbl.set_label("Ventilador 1: sin conexión EC")
            self._gpu_fan_lbl.set_label("Ventilador 2: sin conexión EC")

        if gpu_m.available:
            self._gpu_gauge.set_reading(gpu_temp, f"{gpu_m.util_pct}% carga")
            self._gpu_stats_lbl.set_label(f"{gpu_m.power_w:.1f} W  ·  VRAM {gpu_m.mem_used_mib}/{gpu_m.mem_total_mib} MiB")
        else:
            self._gpu_gauge.set_reading(gpu_temp, "Monitor EC")
            self._gpu_stats_lbl.set_label("GPU dedicada inactiva o sin datos nvidia-smi")

        self._ram_lbl.set_label(
            f"Memoria RAM: {sys_m.ram_used_gb:.1f} / {sys_m.ram_total_gb:.1f} GB ({sys_m.ram_percent:.0f} %)"
        )
        self._ram_bar.set_fraction(max(0.0, min(1.0, sys_m.ram_percent / 100.0)))

    def update_backlight(self, info: BacklightInfo | None) -> None:
        if info is None or self._brightness_debounce:
            return
        self._syncing = True
        try:
            pct = max(5, min(100, info.percent))
            self._br_scale.set_value(pct)
            self._br_val_lbl.set_label(f"{pct} %")
        finally:
            self._syncing = False

    def cancel_pending(self) -> None:
        if self._brightness_debounce:
            from gi.repository import GLib
            GLib.source_remove(self._brightness_debounce)
            self._brightness_debounce = 0
