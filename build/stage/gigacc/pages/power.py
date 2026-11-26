"""Página Optimización de Energía: presets 1-clic y ajuste fino intel_pstate."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..backend.gigactl_client import GigactlClient  # noqa: E402
from ..backend.power_client import BacklightInfo, CpuPowerState, PowerClient  # noqa: E402
from ..backend.sysinfo import NvidiaMetrics, SystemMetrics  # noqa: E402

EPP_LABELS = (
    ("power", "Máximo ahorro (power)"),
    ("balance_power", "Ahorro equilibrado (balance_power)"),
    ("balance_performance", "Rendimiento equilibrado (balance_performance)"),
    ("performance", "Máximo rendimiento (performance)"),
)


class PowerPage(Gtk.ScrolledWindow):
    """Gestión de consumo eléctrico, optimizaciones en 1 clic y límites Intel P-State."""

    def __init__(
        self,
        gigactl: GigactlClient,
        power: PowerClient,
        on_toast: Callable[[str], None],
    ) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._gigactl = gigactl
        self._power = power
        self._on_toast = on_toast
        self._syncing = False
        self._epp_keys: list[str] = [k for k, _ in EPP_LABELS]
        self._advanced_dirty = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20)
        root.set_margin_bottom(22)
        root.set_margin_start(22)
        root.set_margin_end(22)

        title = Gtk.Label(label="Optimización de Energía", xalign=0.0)
        title.add_css_class("gcc-page-title")
        sub = Gtk.Label(
            label="Optimiza autonomía, temperatura y consumo combinando perfil eléctrico, brillo, teclado y límites de CPU.",
            xalign=0.0,
            wrap=True,
        )
        sub.add_css_class("gcc-muted")
        root.append(title)
        root.append(sub)

        # Resumen energético
        sum_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
        self._supply_lbl = self._make_kpi_card(sum_card, "ALIMENTACIÓN")
        self._gpu_pwr_lbl = self._make_kpi_card(sum_card, "CONSUMO GPU")
        self._screen_lbl = self._make_kpi_card(sum_card, "BRILLO PANTALLA")
        self._turbo_lbl = self._make_kpi_card(sum_card, "TURBO BOOST CPU")
        root.append(sum_card)

        # Optimizaciones en 1 clic (sin contraseña)
        quick_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        quick_card.add_css_class("gcc-card")
        q_title = Gtk.Label(label="MODOS DE OPTIMIZACIÓN INSTANTÁNEA (SIN CONTRASEÑA)", xalign=0.0)
        q_title.add_css_class("gcc-eyebrow")
        quick_card.append(q_title)

        q_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)

        presets = (
            ("Máximo Ahorro", "Perfil ahorro + brillo 35% + teclado 20% + ventiladores silenciosos.", "battery", 35, 20, "quiet"),
            ("Oficina / Estudio", "Perfil equilibrado + brillo 65% + teclado 60% + ventiladores equilibrados.", "balanced", 65, 60, "balanced"),
            ("Máxima Potencia", "Alto rendimiento + brillo 85% + teclado 100% + ventiladores rendimiento.", "performance", 85, 100, "performance"),
        )
        for pname, pdesc, pwr_p, scr_p, kbd_p, fan_p in presets:
            btn = Gtk.Button()
            btn.add_css_class("gcc-mode-btn")
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            l1 = Gtk.Label(label=pname, xalign=0.0)
            l1.add_css_class("gcc-section-title")
            l2 = Gtk.Label(label=pdesc, xalign=0.0, wrap=True)
            l2.add_css_class("gcc-muted")
            bx.append(l1)
            bx.append(l2)
            btn.set_child(bx)
            btn.connect("clicked", self._apply_quick_preset, pname, pwr_p, scr_p, kbd_p, fan_p)
            q_row.append(btn)

        quick_card.append(q_row)
        root.append(quick_card)

        # Ajuste fino de Intel P-State (requiere pkexec al aplicar)
        adv_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        adv_card.add_css_class("gcc-card")
        adv_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        adv_title = Gtk.Label(label="AJUSTE FINO DE CPU (INTEL P-STATE)", xalign=0.0, hexpand=True)
        adv_title.add_css_class("gcc-eyebrow")
        adv_badge = Gtk.Label(label="Requiere autorización al aplicar")
        adv_badge.add_css_class("gcc-pill")
        adv_badge.add_css_class("gcc-pill-warn")
        adv_hdr.append(adv_title)
        adv_hdr.append(adv_badge)
        adv_card.append(adv_hdr)

        # Switch Intel Turbo Boost
        turbo_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        turbo_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        t_l1 = Gtk.Label(label="Intel Turbo Boost", xalign=0.0)
        t_l1.add_css_class("gcc-section-title")
        t_l2 = Gtk.Label(
            label="Desactivarlo reduce drásticamente picos de calor y ruido de ventiladores manteniendo la frecuencia base.",
            xalign=0.0,
            wrap=True,
        )
        t_l2.add_css_class("gcc-muted")
        turbo_txt.append(t_l1)
        turbo_txt.append(t_l2)
        self._turbo_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._turbo_switch.connect("notify::active", self._mark_dirty)
        turbo_row.append(turbo_txt)
        turbo_row.append(self._turbo_switch)
        adv_card.append(turbo_row)

        # Slider Límite máximo CPU
        maxp_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        maxp_lbl = Gtk.Label(label="Límite máximo de rendimiento CPU", xalign=0.0, hexpand=True)
        self._max_perf_val = Gtk.Label(label="100 %")
        self._max_perf_val.add_css_class("gcc-value-chip")
        maxp_hdr.append(maxp_lbl)
        maxp_hdr.append(self._max_perf_val)
        adv_card.append(maxp_hdr)

        self._max_perf_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 40, 100, 5)
        self._max_perf_scale.set_draw_value(False)
        self._max_perf_scale.connect("value-changed", self._on_max_perf_changed)
        adv_card.append(self._max_perf_scale)

        # Selector EPP
        epp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        epp_lbl = Gtk.Label(label="Preferencia de eficiencia energética (EPP)", xalign=0.0, hexpand=True)
        self._epp_dropdown = Gtk.DropDown.new_from_strings([lbl for _, lbl in EPP_LABELS])
        self._epp_dropdown.connect("notify::selected", self._mark_dirty)
        epp_row.append(epp_lbl)
        epp_row.append(self._epp_dropdown)
        adv_card.append(epp_row)

        # Switch HWP Dynamic Boost
        hwp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hwp_lbl = Gtk.Label(label="HWP Dynamic Boost (aceleración dinámica)", xalign=0.0, hexpand=True)
        self._hwp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._hwp_switch.connect("notify::active", self._mark_dirty)
        hwp_row.append(hwp_lbl)
        hwp_row.append(self._hwp_switch)
        adv_card.append(hwp_row)

        # Botones aplicar / restablecer
        adv_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        adv_btns.set_halign(Gtk.Align.END)
        reset_btn = Gtk.Button(label="Restablecer valores por defecto")
        reset_btn.connect("clicked", self._on_reset_defaults)
        self._apply_adv_btn = Gtk.Button(label="Aplicar ajustes avanzados")
        self._apply_adv_btn.add_css_class("gcc-accent-btn")
        self._apply_adv_btn.connect("clicked", self._on_apply_advanced)
        adv_btns.append(reset_btn)
        adv_btns.append(self._apply_adv_btn)
        adv_card.append(adv_btns)

        root.append(adv_card)
        self.set_child(root)

    def _make_kpi_card(self, parent: Gtk.Box, heading: str) -> Gtk.Label:
        bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bx.add_css_class("gcc-card")
        ey = Gtk.Label(label=heading, xalign=0.0)
        ey.add_css_class("gcc-eyebrow")
        val = Gtk.Label(label="—", xalign=0.0)
        val.add_css_class("gcc-kpi-big")
        bx.append(ey)
        bx.append(val)
        parent.append(bx)
        return val

    def _mark_dirty(self, *_args) -> None:
        if not self._syncing:
            self._advanced_dirty = True

    def _on_max_perf_changed(self, scale: Gtk.Scale) -> None:
        pct = int(round(scale.get_value()))
        self._max_perf_val.set_label(f"{pct} %")
        if not self._syncing:
            self._advanced_dirty = True

    def _apply_quick_preset(self, _btn, name: str, pwr_p: str, scr_p: int, kbd_p: int, fan_p: str) -> None:
        self._power.set_power_profile(pwr_p)
        self._power.set_screen_brightness(scr_p)
        self._gigactl.set_profile(fan_p)
        self._gigactl.set_keyboard_brightness(kbd_p)
        self._on_toast(f"Modo '{name}' aplicado (energía {pwr_p}, pantalla {scr_p}%, teclado {kbd_p}%).")

    def _on_apply_advanced(self, _btn) -> None:
        turbo = self._turbo_switch.get_active()
        max_perf = int(round(self._max_perf_scale.get_value()))
        hwp = self._hwp_switch.get_active()
        sel_idx = self._epp_dropdown.get_selected()
        epp = self._epp_keys[sel_idx] if 0 <= sel_idx < len(self._epp_keys) else "balance_performance"
        self._send_tuning(turbo, max_perf, hwp, epp)

    def _on_reset_defaults(self, _btn) -> None:
        self._send_tuning(True, 100, True, "balance_performance")

    def _send_tuning(self, turbo: bool, max_perf: int, hwp: bool, epp: str) -> None:
        self._apply_adv_btn.set_sensitive(False)

        def done(ok: bool, msg: str) -> bool:
            self._apply_adv_btn.set_sensitive(True)
            if ok:
                self._advanced_dirty = False
            self._on_toast(msg)
            return False

        self._power.apply_cpu_tuning(
            turbo_enabled=turbo,
            max_perf_pct=max_perf,
            hwp_boost=hwp,
            epp=epp,
            on_done=done,
        )

    def update_metrics(
        self,
        sys_m: SystemMetrics,
        gpu_m: NvidiaMetrics,
        backlight: BacklightInfo | None,
        cpu_pwr: CpuPowerState,
    ) -> None:
        if sys_m.battery_percent is not None:
            ac_txt = "Cargando (AC)" if sys_m.ac_online else "En batería"
            self._supply_lbl.set_label(f"{sys_m.battery_percent}% · {ac_txt}")
        elif sys_m.ac_online is True:
            self._supply_lbl.set_label("Corriente AC")
        elif sys_m.ac_online is False:
            self._supply_lbl.set_label("Batería")
        else:
            self._supply_lbl.set_label("AC conectado")

        self._gpu_pwr_lbl.set_label(f"{gpu_m.power_w:.1f} W" if gpu_m.available else "— W")
        self._screen_lbl.set_label(f"{backlight.percent} %" if backlight else "— %")
        self._turbo_lbl.set_label("Activo" if cpu_pwr.turbo_enabled else "Desactivado")

        if not self._advanced_dirty and cpu_pwr.pstate_available:
            self._syncing = True
            try:
                self._turbo_switch.set_active(cpu_pwr.turbo_enabled)
                self._max_perf_scale.set_value(cpu_pwr.max_perf_pct)
                self._max_perf_val.set_label(f"{cpu_pwr.max_perf_pct} %")
                self._hwp_switch.set_active(cpu_pwr.hwp_dynamic_boost)
                if cpu_pwr.epp in self._epp_keys:
                    self._epp_dropdown.set_selected(self._epp_keys.index(cpu_pwr.epp))
            finally:
                self._syncing = False
