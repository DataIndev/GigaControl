"""Página Control de Ventiladores: perfiles, manual directo y curva personalizada."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..backend import curves_math  # noqa: E402
from ..backend.gigactl_client import GigactlClient, Telemetry  # noqa: E402
from ..widgets.curve_editor import FanCurveEditor  # noqa: E402

FAN_PROFILES = (
    ("quiet", "Silencioso", "Bajo ruido"),
    ("balanced", "Equilibrado", "Recomendado"),
    ("performance", "Rendimiento", "Más fresco"),
    ("max", "Máximo", "100 % fijo"),
    ("firmware", "Firmware Auto", "Control BIOS"),
)


class FansPage(Gtk.ScrolledWindow):
    """Control completo de los ventiladores CPU (Fan1) y GPU (Fan2)."""

    def __init__(self, gigactl: GigactlClient, on_toast: Callable[[str], None]) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._gigactl = gigactl
        self._on_toast = on_toast
        self._syncing = False
        self._last_cpu_temp: int = 0
        self._last_gpu_temp: int = 0
        self._editing_which: str = "cpu"
        self._linked_curves: bool = True
        self._cpu_curve: curves_math.Curve = list(curves_math.BUILTIN_PROFILES["balanced"])
        self._gpu_curve: curves_math.Curve = list(curves_math.BUILTIN_PROFILES["balanced"])
        self._manual_touched = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20)
        root.set_margin_bottom(22)
        root.set_margin_start(22)
        root.set_margin_end(22)

        # Cabecera con botón de escape Firmware
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label="Control de Ventiladores", xalign=0.0)
        title.add_css_class("gcc-page-title")
        sub = Gtk.Label(
            label="Ajusta perfiles inteligentes, fija velocidad manual por ventilador o dibuja tu propia curva térmica.",
            xalign=0.0,
            wrap=True,
        )
        sub.add_css_class("gcc-muted")
        tbox.append(title)
        tbox.append(sub)
        hdr.append(tbox)

        fw_escape = Gtk.Button(label="Restaurar Firmware Auto")
        fw_escape.set_valign(Gtk.Align.CENTER)
        fw_escape.connect("clicked", lambda *_: self._gigactl.restore_firmware())
        hdr.append(fw_escape)
        root.append(hdr)

        # Tira de telemetría en vivo
        live_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, homogeneous=True)
        self._cpu_live_lbl = self._make_fan_live_card(live_strip, "VENTILADOR CPU (FAN 1)")
        self._gpu_live_lbl = self._make_fan_live_card(live_strip, "VENTILADOR GPU (FAN 2)")
        root.append(live_strip)

        # Sección 1: Perfiles predefinidos
        prof_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        prof_card.add_css_class("gcc-card")
        prof_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prof_lbl = Gtk.Label(label="PERFILES DE VENTILACIÓN", xalign=0.0, hexpand=True)
        prof_lbl.add_css_class("gcc-eyebrow")
        self._active_prof_chip = Gtk.Label(label="Activo: —")
        self._active_prof_chip.add_css_class("gcc-value-chip")
        prof_hdr.append(prof_lbl)
        prof_hdr.append(self._active_prof_chip)
        prof_card.append(prof_hdr)

        prof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        self._prof_buttons: dict[str, Gtk.ToggleButton] = {}
        grp: Gtk.ToggleButton | None = None
        for pid, pname, psub in FAN_PROFILES:
            btn = Gtk.ToggleButton()
            btn.add_css_class("gcc-mode-btn")
            if pid == "firmware":
                btn.add_css_class("firmware")
            if grp is None:
                grp = btn
            else:
                btn.set_group(grp)
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            bx.set_halign(Gtk.Align.CENTER)
            l1 = Gtk.Label(label=pname)
            l1.add_css_class("gcc-section-title")
            l2 = Gtk.Label(label=psub)
            l2.add_css_class("gcc-muted")
            bx.append(l1)
            bx.append(l2)
            btn.set_child(bx)
            btn.connect("toggled", self._on_profile_toggled, pid)
            prof_row.append(btn)
            self._prof_buttons[pid] = btn
        prof_card.append(prof_row)
        root.append(prof_card)

        # Sección 2: Control manual directo (RPM/%)
        man_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        man_card.add_css_class("gcc-card")
        man_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        man_lbl = Gtk.Label(label="CONTROL MANUAL DIRECTO (%)", xalign=0.0, hexpand=True)
        man_lbl.add_css_class("gcc-eyebrow")
        link_lbl = Gtk.Label(label="Vincular CPU y GPU")
        link_lbl.add_css_class("gcc-muted")
        self._link_manual_sw = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        self._link_manual_sw.connect("notify::active", self._on_link_manual_toggled)
        man_hdr.append(man_lbl)
        man_hdr.append(link_lbl)
        man_hdr.append(self._link_manual_sw)
        man_card.append(man_hdr)

        # Slider CPU
        cpu_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cpu_row_lbl = Gtk.Label(label="Ventilador CPU", width_chars=15, xalign=0.0)
        self._cpu_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._cpu_slider.set_draw_value(False)
        self._cpu_slider.set_hexpand(True)
        self._cpu_slider.set_value(50)
        self._cpu_slider.connect("value-changed", self._on_manual_slider_changed, "cpu")
        self._cpu_slider_val = Gtk.Label(label="50 %", width_chars=6)
        self._cpu_slider_val.add_css_class("gcc-value-chip")
        cpu_row.append(cpu_row_lbl)
        cpu_row.append(self._cpu_slider)
        cpu_row.append(self._cpu_slider_val)
        man_card.append(cpu_row)

        # Slider GPU
        gpu_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gpu_row_lbl = Gtk.Label(label="Ventilador GPU", width_chars=15, xalign=0.0)
        self._gpu_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._gpu_slider.set_draw_value(False)
        self._gpu_slider.set_hexpand(True)
        self._gpu_slider.set_value(50)
        self._gpu_slider.set_sensitive(False)
        self._gpu_slider.connect("value-changed", self._on_manual_slider_changed, "gpu")
        self._gpu_slider_val = Gtk.Label(label="50 %", width_chars=6)
        self._gpu_slider_val.add_css_class("gcc-value-chip")
        gpu_row.append(gpu_row_lbl)
        gpu_row.append(self._gpu_slider)
        gpu_row.append(self._gpu_slider_val)
        man_card.append(gpu_row)

        man_footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        man_note = Gtk.Label(
            label="Protección térmica: no se permite fijar menos de 30 % cuando la CPU supera 85 °C.",
            xalign=0.0,
            wrap=True,
            hexpand=True,
        )
        man_note.add_css_class("gcc-muted")
        apply_man_btn = Gtk.Button(label="Aplicar velocidad manual")
        apply_man_btn.add_css_class("gcc-accent-btn")
        apply_man_btn.connect("clicked", self._on_apply_manual_clicked)
        man_footer.append(man_note)
        man_footer.append(apply_man_btn)
        man_card.append(man_footer)
        root.append(man_card)

        # Sección 3: Editor interactivo de curva personalizada
        curve_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        curve_card.add_css_class("gcc-card")

        curve_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        curve_title = Gtk.Label(label="EDITOR DE CURVA PERSONALIZADA", xalign=0.0, hexpand=True)
        curve_title.add_css_class("gcc-eyebrow")

        self._curve_link_sw = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        self._curve_link_sw.connect("notify::active", self._on_curve_link_toggled)
        curve_link_lbl = Gtk.Label(label="Curva vinculada (CPU+GPU)")
        curve_link_lbl.add_css_class("gcc-muted")

        self._btn_edit_cpu = Gtk.ToggleButton(label="CPU", active=True)
        self._btn_edit_gpu = Gtk.ToggleButton(label="GPU", group=self._btn_edit_cpu)
        self._btn_edit_cpu.connect("toggled", self._on_edit_target_toggled, "cpu")
        self._btn_edit_gpu.connect("toggled", self._on_edit_target_toggled, "gpu")
        seg_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        seg_box.add_css_class("linked")
        seg_box.append(self._btn_edit_cpu)
        seg_box.append(self._btn_edit_gpu)
        self._btn_edit_gpu.set_sensitive(False)

        curve_hdr.append(curve_title)
        curve_hdr.append(curve_link_lbl)
        curve_hdr.append(self._curve_link_sw)
        curve_hdr.append(seg_box)
        curve_card.append(curve_hdr)

        self._curve_editor = FanCurveEditor(on_preview=self._on_curve_preview_changed)
        curve_card.append(self._curve_editor)

        self._nodes_summary = Gtk.Label(label="", xalign=0.0, wrap=True)
        self._nodes_summary.add_css_class("gcc-muted")
        curve_card.append(self._nodes_summary)

        curve_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        curve_hint = Gtk.Label(
            label="Arrastra los 5 nodos o usa Tab + flechas. Al pulsar Aplicar se activa la curva en gigactld.",
            xalign=0.0,
            wrap=True,
            hexpand=True,
        )
        curve_hint.add_css_class("gcc-muted")
        reset_curve_btn = Gtk.Button(label="Cargar base Equilibrada")
        reset_curve_btn.connect("clicked", self._on_reset_curve_clicked)
        apply_curve_btn = Gtk.Button(label="Aplicar curva personalizada")
        apply_curve_btn.add_css_class("gcc-accent-btn")
        apply_curve_btn.connect("clicked", self._on_apply_curve_clicked)
        curve_actions.append(curve_hint)
        curve_actions.append(reset_curve_btn)
        curve_actions.append(apply_curve_btn)
        curve_card.append(curve_actions)
        root.append(curve_card)

        self._refresh_nodes_summary()
        self.set_child(root)

    def _make_fan_live_card(self, parent: Gtk.Box, heading: str) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("gcc-card")
        ey = Gtk.Label(label=heading, xalign=0.0)
        ey.add_css_class("gcc-eyebrow")
        val = Gtk.Label(label="— °C  ·  — RPM  ·  — %", xalign=0.0)
        val.add_css_class("gcc-kpi-big")
        box.append(ey)
        box.append(val)
        parent.append(box)
        return val

    def _on_profile_toggled(self, btn: Gtk.ToggleButton, profile_id: str) -> None:
        if self._syncing or not btn.get_active():
            return
        self._gigactl.set_profile(profile_id)

    def _on_link_manual_toggled(self, sw: Gtk.Switch, _pspec) -> None:
        linked = sw.get_active()
        self._gpu_slider.set_sensitive(not linked)
        if linked:
            self._gpu_slider.set_value(self._cpu_slider.get_value())

    def _on_manual_slider_changed(self, scale: Gtk.Scale, which: str) -> None:
        self._manual_touched = True
        pct = int(round(scale.get_value()))
        if which == "cpu":
            self._cpu_slider_val.set_label(f"{pct} %")
            if self._link_manual_sw.get_active():
                self._gpu_slider.set_value(pct)
                self._gpu_slider_val.set_label(f"{pct} %")
        else:
            self._gpu_slider_val.set_label(f"{pct} %")

    def _on_apply_manual_clicked(self, _btn) -> None:
        cpu_pct = int(round(self._cpu_slider.get_value()))
        gpu_pct = cpu_pct if self._link_manual_sw.get_active() else int(round(self._gpu_slider.get_value()))
        if self._last_cpu_temp >= curves_math.FLOOR_TEMP_C and (cpu_pct < curves_math.FLOOR_PCT or gpu_pct < curves_math.FLOOR_PCT):
            self._on_toast(
                f"Bloqueado por seguridad: con CPU a {self._last_cpu_temp} °C el mínimo permitido es {curves_math.FLOOR_PCT} %."
            )
            return
        if self._link_manual_sw.get_active():
            self._gigactl.set_fan_duty(0, cpu_pct)
            self._on_toast(f"Aplicando {cpu_pct} % a ambos ventiladores…")
        else:
            self._gigactl.set_fan_duty(1, cpu_pct)
            self._gigactl.set_fan_duty(2, gpu_pct)
            self._on_toast(f"Aplicando CPU {cpu_pct} % y GPU {gpu_pct} %…")

    def _on_curve_link_toggled(self, sw: Gtk.Switch, _pspec) -> None:
        self._linked_curves = sw.get_active()
        self._btn_edit_gpu.set_sensitive(not self._linked_curves)
        if self._linked_curves:
            self._editing_which = "cpu"
            self._btn_edit_cpu.set_active(True)
            self._gpu_curve = list(self._cpu_curve)
            self._curve_editor.set_points(self._cpu_curve)
            self._curve_editor.set_live_temp(self._last_cpu_temp or None)
        self._refresh_nodes_summary()

    def _on_edit_target_toggled(self, btn: Gtk.ToggleButton, which: str) -> None:
        if not btn.get_active():
            return
        self._editing_which = which
        pts = self._cpu_curve if which == "cpu" else self._gpu_curve
        self._curve_editor.set_points(pts)
        live = self._last_cpu_temp if which == "cpu" else self._last_gpu_temp
        self._curve_editor.set_live_temp(live or None)
        self._refresh_nodes_summary()

    def _on_curve_preview_changed(self, pts: curves_math.Curve) -> None:
        if self._linked_curves:
            self._cpu_curve = list(pts)
            self._gpu_curve = list(pts)
        elif self._editing_which == "cpu":
            self._cpu_curve = list(pts)
        else:
            self._gpu_curve = list(pts)
        self._refresh_nodes_summary()

    def _on_reset_curve_clicked(self, _btn) -> None:
        base = list(curves_math.BUILTIN_PROFILES["balanced"])
        if self._linked_curves:
            self._cpu_curve = list(base)
            self._gpu_curve = list(base)
        elif self._editing_which == "cpu":
            self._cpu_curve = list(base)
        else:
            self._gpu_curve = list(base)
        self._curve_editor.set_points(base)
        self._refresh_nodes_summary()

    def _on_apply_curve_clicked(self, _btn) -> None:
        pts = self._curve_editor.points
        if self._linked_curves:
            self._gigactl.set_curve("cpu", pts, True)
            self._on_toast("Curva personalizada vinculada aplicada.")
        else:
            self._gigactl.set_curve("cpu", self._cpu_curve, False)
            self._gigactl.set_curve("gpu", self._gpu_curve, False)
            self._on_toast("Curvas personalizadas independientes (CPU y GPU) aplicadas.")

    def _refresh_nodes_summary(self) -> None:
        pts = self._curve_editor.points
        txt = "   |   ".join(f"N{i+1}: {t}°C → {d}%" for i, (t, d) in enumerate(pts))
        self._nodes_summary.set_label(txt)

    def update_telemetry(self, t: Telemetry | None) -> None:
        if t is None:
            return
        self._last_cpu_temp = t.cpu_temp
        self._last_gpu_temp = t.gpu_temp
        self._cpu_live_lbl.set_label(f"{t.cpu_temp} °C  ·  {t.fan1_rpm} RPM  ·  {t.fan1_duty_pct} %")
        self._gpu_live_lbl.set_label(f"{t.gpu_temp} °C  ·  {t.fan2_rpm} RPM  ·  {t.fan2_duty_pct} %")
        live = t.cpu_temp if (self._linked_curves or self._editing_which == "cpu") else t.gpu_temp
        self._curve_editor.set_live_temp(live)
        if not self._manual_touched:
            self._cpu_slider.set_value(t.fan1_duty_pct)
            self._cpu_slider_val.set_label(f"{t.fan1_duty_pct} %")
            if not self._link_manual_sw.get_active():
                self._gpu_slider.set_value(t.fan2_duty_pct)
                self._gpu_slider_val.set_label(f"{t.fan2_duty_pct} %")

    def sync_from_daemon(self) -> None:
        prof = self._gigactl.active_profile() or "firmware"
        self._active_prof_chip.set_label(f"Activo: {curves_math.profile_label_es(prof)}")
        self._syncing = True
        try:
            for pid, btn in self._prof_buttons.items():
                btn.set_active(pid == prof)
            snap = self._gigactl.curves()
            if snap is not None and snap.cpu:
                self._linked_curves = snap.linked
                self._cpu_curve = list(snap.cpu)
                self._gpu_curve = list(snap.gpu) if snap.gpu else list(snap.cpu)
                self._curve_link_sw.set_active(snap.linked)
                self._btn_edit_gpu.set_sensitive(not snap.linked)
                active_pts = self._cpu_curve if self._editing_which == "cpu" else self._gpu_curve
                self._curve_editor.set_points(active_pts)
                self._refresh_nodes_summary()
        finally:
            self._syncing = False
