"""Página Rendimiento: perfiles system76-power, modo GPU y métricas detalladas."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..backend.power_client import CpuPowerState, PowerClient  # noqa: E402
from ..backend.sysinfo import HardwareInfo, NvidiaMetrics, SystemMetrics  # noqa: E402

POWER_PROFILES = (
    ("battery", "Ahorro de Energía", "Reduce frecuencias y prioriza autonomía y silencio.", "power-profile-power-saver-symbolic"),
    ("balanced", "Equilibrado", "Ajuste dinámico inteligente entre fluidez y consumo.", "power-profile-balanced-symbolic"),
    ("performance", "Alto Rendimiento", "Máxima frecuencia CPU/GPU para juegos y compilación.", "power-profile-performance-symbolic"),
)

GRAPHICS_MODES = (
    ("nvidia", "NVIDIA Dedicada", "Máximo rendimiento gráfico y salidas HDMI/DP directas."),
    ("hybrid", "Híbrido (PRIME)", "Intel en escritorio y NVIDIA bajo demanda."),
    ("integrated", "Integrada Intel", "Máxima autonomía apagando la GPU dedicada."),
    ("compute", "Cómputo CUDA", "Escritorio en Intel, NVIDIA libre para IA/CUDA."),
)


class PerformancePage(Gtk.ScrolledWindow):
    """Gestión de perfil de rendimiento del sistema, gráficos híbridos y telemetría."""

    def __init__(
        self,
        power: PowerClient,
        hw: HardwareInfo,
        on_toast: Callable[[str], None],
    ) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._power = power
        self._hw = hw
        self._on_toast = on_toast
        self._syncing = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20)
        root.set_margin_bottom(22)
        root.set_margin_start(22)
        root.set_margin_end(22)

        title = Gtk.Label(label="Rendimiento y Gráficos", xalign=0.0)
        title.add_css_class("gcc-page-title")
        sub = Gtk.Label(
            label="Configura el plan de rendimiento de Pop!_OS (system76-power), el modo de GPU y supervisa el hardware.",
            xalign=0.0,
            wrap=True,
        )
        sub.add_css_class("gcc-muted")
        root.append(title)
        root.append(sub)

        # Tarjeta 1: Perfiles de rendimiento del sistema
        prof_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        prof_card.add_css_class("gcc-card")
        prof_title = Gtk.Label(label="PERFIL DE RENDIMIENTO DEL SISTEMA", xalign=0.0)
        prof_title.add_css_class("gcc-eyebrow")
        prof_card.append(prof_title)

        prof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
        self._prof_buttons: dict[str, Gtk.ToggleButton] = {}
        grp: Gtk.ToggleButton | None = None
        for pid, pname, pdesc, picon in POWER_PROFILES:
            btn = Gtk.ToggleButton()
            btn.add_css_class("gcc-mode-btn")
            if grp is None:
                grp = btn
            else:
                btn.set_group(grp)
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            ico = Gtk.Image.new_from_icon_name(picon)
            ico.set_pixel_size(24)
            ico.set_halign(Gtk.Align.START)
            l1 = Gtk.Label(label=pname, xalign=0.0)
            l1.add_css_class("gcc-section-title")
            l2 = Gtk.Label(label=pdesc, xalign=0.0, wrap=True)
            l2.add_css_class("gcc-muted")
            bx.append(ico)
            bx.append(l1)
            bx.append(l2)
            btn.set_child(bx)
            btn.connect("toggled", self._on_profile_toggled, pid)
            prof_row.append(btn)
            self._prof_buttons[pid] = btn
        prof_card.append(prof_row)
        root.append(prof_card)

        # Tarjeta 2: Modo de GPU (Gráficos intercambiables)
        gfx_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        gfx_card.add_css_class("gcc-card")
        gfx_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gfx_title = Gtk.Label(label="MODO DE GRÁFICOS (GPU)", xalign=0.0, hexpand=True)
        gfx_title.add_css_class("gcc-eyebrow")
        self._gfx_chip = Gtk.Label(label="Actual: —")
        self._gfx_chip.add_css_class("gcc-value-chip")
        gfx_hdr.append(gfx_title)
        gfx_hdr.append(self._gfx_chip)
        gfx_card.append(gfx_hdr)

        gfx_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        self._gfx_buttons: dict[str, Gtk.Button] = {}
        for gid, gname, gdesc in GRAPHICS_MODES:
            btn = Gtk.Button()
            btn.add_css_class("gcc-mode-btn")
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            l1 = Gtk.Label(label=gname, xalign=0.0)
            l1.add_css_class("gcc-section-title")
            l2 = Gtk.Label(label=gdesc, xalign=0.0, wrap=True)
            l2.add_css_class("gcc-muted")
            bx.append(l1)
            bx.append(l2)
            btn.set_child(bx)
            btn.connect("clicked", self._on_graphics_clicked, gid, gname)
            gfx_row.append(btn)
            self._gfx_buttons[gid] = btn
        gfx_card.append(gfx_row)

        gfx_note = Gtk.Label(
            label="Cambiar el modo de gráficos aplica la configuración de System76 Power y requiere reiniciar para surtir efecto.",
            xalign=0.0,
            wrap=True,
        )
        gfx_note.add_css_class("gcc-muted")
        gfx_card.append(gfx_note)
        root.append(gfx_card)

        # Tarjeta 3: Especificaciones y métricas en tiempo real
        det_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        det_card.add_css_class("gcc-card")
        det_title = Gtk.Label(label="TELEMETRÍA DETALLADA DE HARDWARE", xalign=0.0)
        det_title.add_css_class("gcc-eyebrow")
        det_card.append(det_title)

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._kv_labels: dict[str, Gtk.Label] = {}
        for key, label in (
            ("cpu_model", "Procesador"),
            ("cpu_freq", "Frecuencia y carga CPU"),
            ("cpu_pstate", "Política Intel P-State / Governor"),
            ("gpu_model", "GPU Dedicada"),
            ("gpu_clocks", "Reloj / VRAM / Estado P-State GPU"),
            ("ram_nvme", "Memoria RAM y SSD NVMe"),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            k_lbl = Gtk.Label(label=label, xalign=0.0, hexpand=True)
            k_lbl.add_css_class("gcc-muted")
            v_lbl = Gtk.Label(label="—", xalign=1.0)
            v_lbl.add_css_class("gcc-value-chip")
            row.append(k_lbl)
            row.append(v_lbl)
            self._rows_box.append(row)
            self._kv_labels[key] = v_lbl
        det_card.append(self._rows_box)
        root.append(det_card)

        self._kv_labels["cpu_model"].set_label(f"{hw.cpu_model} ({hw.cpu_threads} hilos)")
        self.set_child(root)

    def _on_profile_toggled(self, btn: Gtk.ToggleButton, profile_id: str) -> None:
        if self._syncing or not btn.get_active():
            return
        self._power.set_power_profile(profile_id)
        self._on_toast(f"Perfil de rendimiento cambiado a '{profile_id}'.")

    def _on_graphics_clicked(self, _btn, mode_id: str, mode_name: str) -> None:
        if mode_id == self._power.graphics_mode:
            self._on_toast(f"El modo de gráficos '{mode_name}' ya está activo.")
            return
        root_win = self.get_root()
        if hasattr(Adw, "AlertDialog"):
            dlg = Adw.AlertDialog.new(
                f"¿Cambiar gráficos a {mode_name}?",
                "Se actualizará la configuración de GPU mediante system76-power. Será necesario reiniciar el sistema para aplicar el cambio.",
            )
            dlg.add_response("cancel", "Cancelar")
            dlg.add_response("confirm", "Aplicar cambio")
            dlg.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
            dlg.connect("response", self._on_graphics_dialog_response, mode_id, mode_name)
            dlg.present(root_win)
        else:
            self._apply_graphics_mode(mode_id, mode_name)

    def _on_graphics_dialog_response(self, _dlg, response: str, mode_id: str, mode_name: str) -> None:
        if response == "confirm":
            self._apply_graphics_mode(mode_id, mode_name)

    def _apply_graphics_mode(self, mode_id: str, mode_name: str) -> None:
        self._on_toast(f"Cambiando modo de gráficos a {mode_name}…")

        def done(ok: bool, msg: str) -> None:
            if ok:
                self._on_toast(f"Modo {mode_name} programado. Reinicia el equipo para activarlo.")
            else:
                self._on_toast(f"Error al cambiar gráficos: {msg}")

        self._power.set_graphics_mode(mode_id, done)

    def update_power_state(self, profile: str, gfx_mode: str, switchable: bool) -> None:
        self._syncing = True
        try:
            for pid, btn in self._prof_buttons.items():
                btn.set_active(pid == profile)
            self._gfx_chip.set_label(f"Actual: {gfx_mode.upper()}")
            for gid, btn in self._gfx_buttons.items():
                btn.set_sensitive(switchable or gid == gfx_mode)
                if gid == gfx_mode:
                    btn.add_css_class("gcc-accent-btn")
                else:
                    btn.remove_css_class("gcc-accent-btn")
        finally:
            self._syncing = False

    def update_metrics(self, sys_m: SystemMetrics, gpu_m: NvidiaMetrics, cpu_pwr: CpuPowerState) -> None:
        self._kv_labels["cpu_freq"].set_label(
            f"{sys_m.cpu_freq_mhz:.0f} / {sys_m.cpu_max_mhz:.0f} MHz  ·  Uso {sys_m.cpu_percent:.0f} %"
        )
        turbo_s = "ON" if cpu_pwr.turbo_enabled else "OFF"
        self._kv_labels["cpu_pstate"].set_label(
            f"Turbo {turbo_s}  ·  Máx {cpu_pwr.max_perf_pct}%  ·  {cpu_pwr.governor or '—'} / {cpu_pwr.epp or '—'}"
        )
        if gpu_m.available:
            self._kv_labels["gpu_model"].set_label(f"{gpu_m.name} (Driver {gpu_m.driver})")
            self._kv_labels["gpu_clocks"].set_label(
                f"{gpu_m.clock_gfx_mhz} MHz  ·  {gpu_m.mem_used_mib}/{gpu_m.mem_total_mib} MiB  ·  {gpu_m.pstate}  ·  {gpu_m.power_w:.1f} W"
            )
        else:
            self._kv_labels["gpu_model"].set_label("GPU NVIDIA no activa o en suspensión")
            self._kv_labels["gpu_clocks"].set_label("—")

        nvme_s = f"NVMe {sys_m.nvme_temp_c} °C" if sys_m.nvme_temp_c is not None else "NVMe —"
        self._kv_labels["ram_nvme"].set_label(
            f"RAM {sys_m.ram_used_gb:.1f} / {sys_m.ram_total_gb:.1f} GB ({sys_m.ram_percent:.0f}%)  ·  {nvme_s}"
        )
