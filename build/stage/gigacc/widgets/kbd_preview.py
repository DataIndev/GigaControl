"""Vista previa en tiempo real del teclado RGB (zona única, estilo laptop Gigabyte G5)."""
from __future__ import annotations

import math
import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


def _rounded_rect(cr: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2.0, 0.0)
    cr.arc(x + w - r, y + h - r, r, 0.0, math.pi / 2.0)
    cr.arc(x + r, y + h - r, r, math.pi / 2.0, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3.0 * math.pi / 2.0)
    cr.close_path()


class KeyboardPreview(Gtk.DrawingArea):
    """Dibuja un teclado ANSI + bloque numérico con iluminación RGB de zona única."""

    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self._rgb = (0, 0, 255)
        self._brightness_pct = 100
        self.set_content_width(520)
        self.set_content_height(190)
        self.set_hexpand(True)
        self.set_draw_func(self._on_draw)

    def set_state(self, enabled: bool, rgb: tuple[int, int, int], brightness_pct: int) -> None:
        self._enabled = bool(enabled)
        self._rgb = tuple(max(0, min(255, int(c))) for c in rgb)
        self._brightness_pct = max(0, min(100, int(brightness_pct)))
        self.queue_draw()

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        pad = 10.0
        chassis_w = max(240.0, width - pad * 2.0)
        chassis_h = max(120.0, height - pad * 2.0)
        cx0 = pad
        cy0 = pad

        # Marco del chasis del teclado
        _rounded_rect(cr, cx0, cy0, chassis_w, chassis_h, 14.0)
        if dark:
            cr.set_source_rgb(0.08, 0.10, 0.14)
        else:
            cr.set_source_rgb(0.14, 0.16, 0.21)
        cr.fill_preserve()
        cr.set_line_width(1.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
        cr.stroke()

        r, g, b = (c / 255.0 for c in self._rgb)
        intensity = (self._brightness_pct / 100.0) if self._enabled else 0.0
        # Curva perceptual suave para que brillos bajos sigan viéndose en pantalla
        glow = (0.18 + 0.82 * (intensity ** 0.75)) if intensity > 0 else 0.0

        inner_pad = 14.0
        kx0 = cx0 + inner_pad
        ky0 = cy0 + inner_pad
        kw = chassis_w - inner_pad * 2.0
        kh = chassis_h - inner_pad * 2.0

        # Resplandor difuso bajo todas las teclas
        if glow > 0:
            grad = cairo.RadialGradient(
                cx0 + chassis_w * 0.5,
                cy0 + chassis_h * 0.5,
                10.0,
                cx0 + chassis_w * 0.5,
                cy0 + chassis_h * 0.5,
                chassis_w * 0.56,
            )
            grad.add_color_stop_rgba(0.0, r, g, b, 0.34 * glow)
            grad.add_color_stop_rgba(0.7, r, g, b, 0.18 * glow)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.04 * glow)
            _rounded_rect(cr, kx0 - 4, ky0 - 4, kw + 8, kh + 8, 10.0)
            cr.set_source(grad)
            cr.fill()

        # Filas proporcionales: área principal (15 unidades) + gap + numpad (4 unidades)
        rows = [
            ([1.0] * 14, [1.0] * 4),                                           # Esc + F1..F12 + Del | Numpad top
            ([1.0] * 13 + [1.8], [1.0] * 4),                                   # 1..= Backspace
            ([1.4] + [1.0] * 12 + [1.4], [1.0] * 4),                           # Tab .. \
            ([1.7] + [1.0] * 11 + [2.1], [1.0] * 4),                           # Caps .. Enter
            ([2.1] + [1.0] * 10 + [2.7], [1.0] * 4),                           # Shift .. Shift
            ([1.3, 1.1, 1.1, 5.8, 1.1, 1.1, 1.1, 1.1, 1.1], [2.0, 1.0, 1.0]),  # Ctrl .. Arrows + 0 . Ent
        ]
        n_rows = len(rows)
        gap = 4.0
        numpad_gap = 12.0
        main_units = 14.8
        num_units = 4.0
        row_h = (kh - gap * (n_rows - 1)) / n_rows
        total_unit_space = kw - numpad_gap
        unit_w = total_unit_space / (main_units + num_units)

        for ri, (main_row, num_row) in enumerate(rows):
            ry = ky0 + ri * (row_h + gap)
            self._draw_row(cr, kx0, ry, row_h, main_row, main_units, unit_w, gap, r, g, b, glow)
            nx0 = kx0 + main_units * unit_w + numpad_gap
            self._draw_row(cr, nx0, ry, row_h, num_row, num_units, unit_w, gap, r, g, b, glow)

    def _draw_row(
        self,
        cr: cairo.Context,
        x_start: float,
        y: float,
        row_h: float,
        weights: list[float],
        target_units: float,
        unit_w: float,
        gap: float,
        r: float,
        g: float,
        b: float,
        glow: float,
    ) -> None:
        total_w = target_units * unit_w
        avail_w = total_w - gap * (len(weights) - 1)
        sum_weights = sum(weights)
        x = x_start
        for w_unit in weights:
            kw = avail_w * (w_unit / sum_weights)
            _rounded_rect(cr, x, y, kw, row_h, 4.0)
            cr.set_source_rgb(0.14, 0.17, 0.22)
            cr.fill_preserve()

            if glow > 0:
                cr.set_line_width(1.6)
                cr.set_source_rgba(r, g, b, 0.90 * glow)
            else:
                cr.set_line_width(1.0)
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
            cr.stroke()

            # Leyenda luminosa sutil en la parte superior de cada tecla
            if glow > 0 and kw > 12:
                bar_w = min(kw * 0.45, 14.0)
                cr.set_source_rgba(r, g, b, 0.72 * glow)
                cr.rectangle(x + (kw - bar_w) / 2.0, y + 3.5, bar_w, 2.0)
                cr.fill()

            x += kw + gap
