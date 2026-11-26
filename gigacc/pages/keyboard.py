"""Página Teclado RGB, Brillo y Teclas de Acceso Rápido."""
from __future__ import annotations

import math
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from ..backend import hotkeys  # noqa: E402
from ..backend.gigactl_client import GigactlClient  # noqa: E402
from ..backend.power_client import BacklightInfo, PowerClient  # noqa: E402
from ..widgets.kbd_preview import KeyboardPreview  # noqa: E402

SWATCHES = hotkeys.RGB_PALETTE


def _name_for_rgb(rgb: tuple[int, int, int]) -> str:
    for name, val in SWATCHES:
        if val == rgb:
            return name
    return "Personalizado"


class KeyboardPage(Gtk.ScrolledWindow):
    """Configuración del teclado RGB de zona única, brillo y hotkeys."""

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
        self._kbd_br_timer = 0
        self._scr_br_timer = 0
        self._local_rgb: tuple[int, int, int] = (0, 0, 255)
        self._local_kbd_br: int = 100
        self._local_kbd_on: bool = True

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20)
        root.set_margin_bottom(22)
        root.set_margin_start(22)
        root.set_margin_end(22)

        title = Gtk.Label(label="Teclado RGB y Brillo", xalign=0.0)
        title.add_css_class("gcc-page-title")
        subtitle = Gtk.Label(
            label="Personaliza la retroiluminación RGB del teclado, el brillo de la pantalla y las teclas de acceso rápido.",
            xalign=0.0,
            wrap=True,
        )
        subtitle.add_css_class("gcc-muted")
        root.append(title)
        root.append(subtitle)

        # Tarjeta 1: Teclado RGB
        kbd_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        kbd_card.add_css_class("gcc-card")

        kbd_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        kbd_title = Gtk.Label(label="ILUMINACIÓN DEL TECLADO (RGB)", xalign=0.0, hexpand=True)
        kbd_title.add_css_class("gcc-eyebrow")
        self._color_status = Gtk.Label(label="Azul · #0000FF")
        self._color_status.add_css_class("gcc-value-chip")
        self._kbd_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._kbd_switch.connect("notify::active", self._on_switch_toggled)
        kbd_hdr.append(kbd_title)
        kbd_hdr.append(self._color_status)
        kbd_hdr.append(self._kbd_switch)
        kbd_card.append(kbd_hdr)

        self._preview = KeyboardPreview()
        kbd_card.append(self._preview)

        palette_lbl = Gtk.Label(label="Colores predefinidos y selector personalizado", xalign=0.0)
        palette_lbl.add_css_class("gcc-section-title")
        kbd_card.append(palette_lbl)

        swatch_flow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        swatch_flow.set_halign(Gtk.Align.START)
        self._swatch_buttons: list[tuple[Gtk.Button, tuple[int, int, int]]] = []
        for name, rgb in SWATCHES:
            btn = self._build_swatch(name, rgb)
            swatch_flow.append(btn)
            self._swatch_buttons.append((btn, rgb))

        self._color_dialog_btn = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(title="Elegir color RGB del teclado", with_alpha=False),
            valign=Gtk.Align.CENTER,
        )
        self._color_dialog_btn.set_tooltip_text("Abrir selector RGB completo")
        self._color_dialog_btn.connect("notify::rgba", self._on_color_dialog_changed)
        swatch_flow.append(self._color_dialog_btn)

        self._hex_entry = Gtk.Entry()
        self._hex_entry.set_max_length(7)
        self._hex_entry.set_width_chars(9)
        self._hex_entry.set_placeholder_text("#FF6B00")
        self._hex_entry.set_text("#0000FF")
        self._hex_entry.connect("activate", lambda *_: self._apply_hex_entry())
        hex_btn = Gtk.Button(label="Aplicar Hex")
        hex_btn.connect("clicked", lambda *_: self._apply_hex_entry())

        palette_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        palette_row.append(swatch_flow)
        palette_row.append(Gtk.Box(hexpand=True))
        palette_row.append(self._hex_entry)
        palette_row.append(hex_btn)
        kbd_card.append(palette_row)

        kbd_br_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        kbd_br_lbl = Gtk.Label(label="Brillo del teclado", xalign=0.0, hexpand=True)
        kbd_br_lbl.add_css_class("gcc-section-title")
        self._kbd_br_val = Gtk.Label(label="100 %")
        self._kbd_br_val.add_css_class("gcc-value-chip")
        kbd_br_hdr.append(kbd_br_lbl)
        kbd_br_hdr.append(self._kbd_br_val)
        kbd_card.append(kbd_br_hdr)

        kbd_br_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._kbd_br_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self._kbd_br_scale.set_draw_value(False)
        self._kbd_br_scale.set_hexpand(True)
        self._kbd_br_scale.connect("value-changed", self._on_kbd_br_changed)
        kbd_br_row.append(self._kbd_br_scale)
        for pct in (0, 25, 50, 75, 100):
            pbtn = Gtk.Button(label=f"{pct}%")
            pbtn.connect("clicked", self._on_kbd_br_preset, pct)
            kbd_br_row.append(pbtn)
        kbd_card.append(kbd_br_row)

        kbd_note = Gtk.Label(
            label="Nota: gigactld guarda tu color y brillo para restaurarlos automáticamente al reiniciar o despertar de suspensión.",
            xalign=0.0,
            wrap=True,
        )
        kbd_note.add_css_class("gcc-muted")
        kbd_card.append(kbd_note)
        root.append(kbd_card)

        # Tarjeta 2: Brillo de Pantalla
        scr_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scr_card.add_css_class("gcc-card")

        scr_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        scr_ico = Gtk.Image.new_from_icon_name("display-brightness-symbolic")
        scr_title = Gtk.Label(label="BRILLO DE PANTALLA", xalign=0.0, hexpand=True)
        scr_title.add_css_class("gcc-eyebrow")
        self._scr_dev_lbl = Gtk.Label(label="")
        self._scr_dev_lbl.add_css_class("gcc-muted")
        self._scr_br_val = Gtk.Label(label="— %")
        self._scr_br_val.add_css_class("gcc-value-chip")
        scr_hdr.append(scr_ico)
        scr_hdr.append(scr_title)
        scr_hdr.append(self._scr_dev_lbl)
        scr_hdr.append(self._scr_br_val)
        scr_card.append(scr_hdr)

        scr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._scr_br_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self._scr_br_scale.set_draw_value(False)
        self._scr_br_scale.set_hexpand(True)
        self._scr_br_scale.connect("value-changed", self._on_scr_br_changed)
        scr_row.append(self._scr_br_scale)
        for pct in (25, 50, 75, 100):
            sbtn = Gtk.Button(label=f"{pct}%")
            sbtn.connect("clicked", self._on_scr_br_preset, pct)
            scr_row.append(sbtn)
        scr_card.append(scr_row)
        root.append(scr_card)

        # Tarjeta 3: Teclas de acceso rápido de iluminación
        hk_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        hk_card.add_css_class("gcc-card")

        hk_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hk_ico = Gtk.Image.new_from_icon_name("keyboard-brightness-symbolic")
        hk_title = Gtk.Label(label="TECLAS DE ACCESO RÁPIDO (ILUMINACIÓN)", xalign=0.0, hexpand=True)
        hk_title.add_css_class("gcc-eyebrow")
        hk_hdr.append(hk_ico)
        hk_hdr.append(hk_title)
        hk_card.append(hk_hdr)

        # Fila 1: Atajos globales COSMIC
        cosmic_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cosmic_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        c1 = Gtk.Label(label="Atajos globales del escritorio COSMIC", xalign=0.0)
        c1.add_css_class("gcc-section-title")
        c2 = Gtk.Label(
            label="Permite controlar la luz y el color RGB del teclado desde cualquier pantalla usando Super+Alt+NumPad o teclas Fn.",
            xalign=0.0,
            wrap=True,
        )
        c2.add_css_class("gcc-muted")
        cosmic_txt.append(c1)
        cosmic_txt.append(c2)

        self._cosmic_pill = Gtk.Label(label="—", valign=Gtk.Align.CENTER)
        self._cosmic_pill.add_css_class("gcc-pill")
        self._cosmic_install_btn = Gtk.Button(label="Configurar atajos COSMIC", valign=Gtk.Align.CENTER)
        self._cosmic_install_btn.add_css_class("gcc-accent-btn")
        self._cosmic_install_btn.connect("clicked", self._on_install_cosmic_clicked)
        self._cosmic_remove_btn = Gtk.Button(label="Quitar atajos", valign=Gtk.Align.CENTER)
        self._cosmic_remove_btn.connect("clicked", self._on_remove_cosmic_clicked)

        cosmic_row.append(cosmic_txt)
        cosmic_row.append(self._cosmic_pill)
        cosmic_row.append(self._cosmic_install_btn)
        cosmic_row.append(self._cosmic_remove_btn)
        hk_card.append(cosmic_row)

        # Fila 2: Driver físico Fn (WMI DKMS)
        fn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        fn_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        f1 = Gtk.Label(label="Teclas físicas Fn del portátil (Driver WMI gigactl_hotkeys)", xalign=0.0)
        f1.add_css_class("gcc-section-title")
        f2 = Gtk.Label(
            label="Opcional (requiere contraseña de administrador): habilita las teclas físicas Fn+/ Fn+* Fn+- Fn++ del hardware Gigabyte/Clevo en Linux.",
            xalign=0.0,
            wrap=True,
        )
        f2.add_css_class("gcc-muted")
        fn_txt.append(f1)
        fn_txt.append(f2)

        self._fn_pill = Gtk.Label(label="—", valign=Gtk.Align.CENTER)
        self._fn_pill.add_css_class("gcc-pill")
        self._fn_install_btn = Gtk.Button(label="Instalar driver Fn (DKMS)", valign=Gtk.Align.CENTER)
        self._fn_install_btn.connect("clicked", self._on_install_fn_driver_clicked)

        fn_row.append(fn_txt)
        fn_row.append(self._fn_pill)
        fn_row.append(self._fn_install_btn)
        hk_card.append(fn_row)

        # Tabla resumen de combinaciones
        map_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for action_lbl, combo_lbl, cli_flag in hotkeys.HOTKEY_DEFINITIONS:
            mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            al = Gtk.Label(label=action_lbl, xalign=0.0, hexpand=True)
            al.add_css_class("gcc-muted")
            cl = Gtk.Label(label=combo_lbl)
            cl.add_css_class("gcc-value-chip")
            fl = Gtk.Label(label=cli_flag)
            fl.add_css_class("gcc-muted")
            mrow.append(al)
            mrow.append(cl)
            mrow.append(fl)
            map_box.append(mrow)
        hk_card.append(map_box)

        root.append(hk_card)

        self.refresh_hotkey_status()
        self.set_child(root)

    def _build_swatch(self, name: str, rgb: tuple[int, int, int]) -> Gtk.Button:
        area = Gtk.DrawingArea()
        area.set_content_width(24)
        area.set_content_height(24)

        def draw(_a, cr, w, h) -> None:
            r, g, b = (c / 255.0 for c in rgb)
            cr.set_source_rgb(r, g, b)
            cr.arc(w / 2.0, h / 2.0, min(w, h) / 2.0 - 1.0, 0, math.tau)
            cr.fill()

        area.set_draw_func(draw)
        btn = Gtk.Button(child=area)
        btn.add_css_class("gcc-swatch")
        btn.set_tooltip_text(name)
        btn.connect("clicked", self._on_swatch_clicked, rgb)
        return btn

    def _on_install_cosmic_clicked(self, _btn) -> None:
        try:
            path = hotkeys.install_cosmic_shortcuts()
            self.refresh_hotkey_status()
            self._on_toast(f"Atajos globales COSMIC configurados en {path.name}.")
        except Exception as exc:
            self._on_toast(f"Error al guardar atajos COSMIC: {exc}")

    def _on_remove_cosmic_clicked(self, _btn) -> None:
        try:
            hotkeys.remove_cosmic_shortcuts()
            self.refresh_hotkey_status()
            self._on_toast("Atajos de GigaControl eliminados de COSMIC.")
        except Exception as exc:
            self._on_toast(f"Error al quitar atajos COSMIC: {exc}")

    def _on_install_fn_driver_clicked(self, btn: Gtk.Button) -> None:
        btn.set_sensitive(False)
        btn.set_label("Instalando…")

        def done(ok: bool, msg: str) -> bool:
            btn.set_sensitive(True)
            btn.set_label("Instalar driver Fn (DKMS)")
            self.refresh_hotkey_status()
            self._on_toast(msg)
            return False

        hotkeys.install_kernel_hotkey_driver_async(done)

    def refresh_hotkey_status(self) -> None:
        cosmic_ok = hotkeys.are_cosmic_shortcuts_installed()
        if cosmic_ok:
            self._cosmic_pill.set_label("Activos")
            self._cosmic_pill.set_css_classes(["gcc-pill", "gcc-pill-ok"])
            self._cosmic_remove_btn.set_sensitive(True)
        else:
            self._cosmic_pill.set_label("No configurados")
            self._cosmic_pill.set_css_classes(["gcc-pill", "gcc-pill-warn"])
            self._cosmic_remove_btn.set_sensitive(False)

        fn_loaded = hotkeys.is_kernel_hotkey_driver_loaded()
        if fn_loaded:
            self._fn_pill.set_label("Driver activo")
            self._fn_pill.set_css_classes(["gcc-pill", "gcc-pill-ok"])
            self._fn_install_btn.set_label("Reinstalar driver Fn")
        else:
            self._fn_pill.set_label("No instalado")
            self._fn_pill.set_css_classes(["gcc-pill", "gcc-pill-warn"])
            self._fn_install_btn.set_label("Instalar driver Fn (DKMS)")

    def _on_switch_toggled(self, sw: Gtk.Switch, _pspec) -> None:
        if self._syncing:
            return
        self._local_kbd_on = sw.get_active()
        self._gigactl.set_keyboard_enabled(self._local_kbd_on)
        self._refresh_preview()

    def _on_swatch_clicked(self, _btn, rgb: tuple[int, int, int]) -> None:
        if self._syncing:
            return
        self._apply_rgb(rgb)

    def _on_color_dialog_changed(self, btn: Gtk.ColorDialogButton, _pspec) -> None:
        if self._syncing:
            return
        rgba = btn.get_rgba()
        rgb = (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255))
        self._apply_rgb(rgb)

    def _apply_hex_entry(self) -> None:
        raw = self._hex_entry.get_text().strip().lstrip("#")
        if len(raw) != 6:
            self._on_toast("Introduce un color hexadecimal válido de 6 dígitos (ejemplo: #FF6B00).")
            return
        try:
            rgb = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        except ValueError:
            self._on_toast("Código hexadecimal inválido.")
            return
        self._apply_rgb(rgb)

    def _apply_rgb(self, rgb: tuple[int, int, int]) -> None:
        self._local_rgb = rgb
        self._local_kbd_on = True
        self._gigactl.set_keyboard_color(*rgb)
        self._syncing = True
        try:
            self._kbd_switch.set_active(True)
            self._hex_entry.set_text(f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0
            self._color_dialog_btn.set_rgba(rgba)
        finally:
            self._syncing = False
        self._refresh_preview()

    def _on_kbd_br_changed(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        pct = int(round(scale.get_value()))
        self._local_kbd_br = pct
        self._kbd_br_val.set_label(f"{pct} %")
        self._refresh_preview()
        if self._kbd_br_timer:
            GLib.source_remove(self._kbd_br_timer)

        def send() -> bool:
            self._kbd_br_timer = 0
            self._gigactl.set_keyboard_brightness(pct)
            return False

        self._kbd_br_timer = GLib.timeout_add(140, send)

    def _on_kbd_br_preset(self, _btn, pct: int) -> None:
        self._kbd_br_scale.set_value(pct)

    def _on_scr_br_changed(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        pct = int(round(scale.get_value()))
        self._scr_br_val.set_label(f"{pct} %")
        if self._scr_br_timer:
            GLib.source_remove(self._scr_br_timer)

        def send() -> bool:
            self._scr_br_timer = 0
            self._power.set_screen_brightness(pct)
            return False

        self._scr_br_timer = GLib.timeout_add(85, send)

    def _on_scr_br_preset(self, _btn, pct: int) -> None:
        self._scr_br_scale.set_value(pct)

    def _refresh_preview(self) -> None:
        hex_c = f"#{self._local_rgb[0]:02X}{self._local_rgb[1]:02X}{self._local_rgb[2]:02X}"
        name = _name_for_rgb(self._local_rgb)
        self._color_status.set_label(f"{name} · {hex_c}" if self._local_kbd_on else "Apagado")
        for btn, rgb in self._swatch_buttons:
            if self._local_kbd_on and rgb == self._local_rgb:
                btn.add_css_class("selected")
            else:
                btn.remove_css_class("selected")
        self._preview.set_state(self._local_kbd_on, self._local_rgb, self._local_kbd_br)

    def sync_from_daemon(self) -> None:
        kbd = self._gigactl.keyboard_state()
        if kbd is None:
            return
        self._local_kbd_on = kbd.enabled
        self._local_rgb = kbd.rgb
        if not self._kbd_br_timer:
            self._local_kbd_br = kbd.brightness_pct

        self._syncing = True
        try:
            self._kbd_switch.set_active(kbd.enabled)
            self._hex_entry.set_text(kbd.hex_color)
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = kbd.r / 255.0, kbd.g / 255.0, kbd.b / 255.0, 1.0
            self._color_dialog_btn.set_rgba(rgba)
            if not self._kbd_br_timer:
                self._kbd_br_scale.set_value(kbd.brightness_pct)
                self._kbd_br_val.set_label(f"{kbd.brightness_pct} %")
        finally:
            self._syncing = False
        self._refresh_preview()

    def update_backlight(self, info: BacklightInfo | None) -> None:
        if info is None or self._scr_br_timer:
            return
        self._syncing = True
        try:
            pct = max(5, min(100, info.percent))
            self._scr_dev_lbl.set_label(info.device)
            self._scr_br_scale.set_value(pct)
            self._scr_br_val.set_label(f"{pct} %")
        finally:
            self._syncing = False

    def cancel_pending(self) -> None:
        for t_attr in ("_kbd_br_timer", "_scr_br_timer"):
            tid = getattr(self, t_attr)
            if tid:
                GLib.source_remove(tid)
                setattr(self, t_attr, 0)
