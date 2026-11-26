"""Medidor circular radial en Cairo estilo Gigabyte Control Center."""
from __future__ import annotations

import math
import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


def semantic_temp_color(temp: float) -> tuple[float, float, float]:
    if temp < 65:
        return (0.13, 0.83, 0.56)   # Verde / frío
    if temp < 82:
        return (1.00, 0.58, 0.10)   # Ámbar Gigabyte / templado
    return (0.96, 0.28, 0.28)       # Rojo / caliente


class RadialGauge(Gtk.DrawingArea):
    """Medidor circular con arco de progreso, valor central y subtítulo."""

    def __init__(
        self,
        title: str,
        unit: str = "°C",
        max_value: float = 100.0,
        semantic_temp: bool = True,
        accent_rgb: tuple[float, float, float] = (1.0, 0.42, 0.0),
        size: int = 152,
    ) -> None:
        super().__init__()
        self._title = title
        self._unit = unit
        self._max_value = max(1.0, float(max_value))
        self._semantic_temp = semantic_temp
        self._accent_rgb = accent_rgb
        self._value: float | None = None
        self._subtitle = ""

        self.set_content_width(size)
        self.set_content_height(size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._on_draw)

    def set_reading(self, value: float | None, subtitle: str = "") -> None:
        self._value = value
        self._subtitle = subtitle
        self.queue_draw()

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        cx = width / 2.0
        cy = height / 2.0
        radius = min(width, height) / 2.0 - 12.0
        line_w = 10.5

        start_angle = math.radians(135.0)
        sweep_total = math.radians(270.0)

        # Pista de fondo
        cr.set_line_width(line_w)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        if dark:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.09)
        else:
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.10)
        cr.arc(cx, cy, radius, start_angle, start_angle + sweep_total)
        cr.stroke()

        val = self._value
        if val is not None:
            frac = max(0.0, min(1.0, float(val) / self._max_value))
            if self._semantic_temp:
                r, g, b = semantic_temp_color(float(val))
            else:
                r, g, b = self._accent_rgb

            # Halo sutil
            cr.set_line_width(line_w + 5.0)
            cr.set_source_rgba(r, g, b, 0.18)
            cr.arc(cx, cy, radius, start_angle, start_angle + sweep_total * frac)
            cr.stroke()

            # Arco principal
            cr.set_line_width(line_w)
            cr.set_source_rgb(r, g, b)
            cr.arc(cx, cy, radius, start_angle, start_angle + sweep_total * frac)
            cr.stroke()

        # Texto central
        text_color = (0.94, 0.96, 0.99) if dark else (0.10, 0.12, 0.16)
        sub_color = (0.62, 0.68, 0.78) if dark else (0.38, 0.43, 0.50)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.0)
        cr.set_source_rgb(*sub_color)
        ext_t = cr.text_extents(self._title)
        cr.move_to(cx - ext_t.width / 2.0 - ext_t.x_bearing, cy - 22.0)
        cr.show_text(self._title)

        val_text = "—" if val is None else f"{int(round(val))}{self._unit}"
        cr.set_font_size(27.0)
        cr.set_source_rgb(*text_color)
        ext_v = cr.text_extents(val_text)
        cr.move_to(cx - ext_v.width / 2.0 - ext_v.x_bearing, cy + 10.0)
        cr.show_text(val_text)

        if self._subtitle:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(11.0)
            cr.set_source_rgb(*sub_color)
            ext_s = cr.text_extents(self._subtitle)
            cr.move_to(cx - ext_s.width / 2.0 - ext_s.x_bearing, cy + 32.0)
            cr.show_text(self._subtitle)
