"""Editor interactivo de curva de ventilador (5 nodos arrastrables)."""
from __future__ import annotations

import math
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..backend import curves_math  # noqa: E402


class FanCurveEditor(Gtk.DrawingArea):
    """Gráfico Temperatura (°C) -> Velocidad (%) con arrastre de ratón y teclado."""

    TEMP_MIN = curves_math.TEMP_MIN
    TEMP_MAX = curves_math.TEMP_MAX

    def __init__(
        self,
        on_changed: Callable[[curves_math.Curve], None] | None = None,
        on_preview: Callable[[curves_math.Curve], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_changed = on_changed
        self._on_preview = on_preview
        self._points: curves_math.Curve = list(curves_math.BUILTIN_PROFILES["balanced"])
        self._live_temp: int | None = None
        self._selected_idx: int = 0
        self._hover_idx: int | None = None
        self._drag_idx: int | None = None
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0

        self.set_content_width(520)
        self.set_content_height(275)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.set_can_focus(True)
        self.set_draw_func(self._on_draw)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    @property
    def points(self) -> curves_math.Curve:
        return list(self._points)

    def set_points(self, points: list[tuple[int, int]]) -> None:
        self._points = curves_math.normalize(points)
        self.queue_draw()

    def set_live_temp(self, temp: int | None) -> None:
        if self._live_temp != temp:
            self._live_temp = temp
            self.queue_draw()

    def _plot_rect(self, width: int, height: int) -> tuple[float, float, float, float]:
        left = 48.0
        right = 18.0
        top = 18.0
        bottom = 36.0
        return left, top, max(100.0, width - left - right), max(80.0, height - top - bottom)

    def _to_px(self, temp: float, duty: float, rect: tuple[float, float, float, float]) -> tuple[float, float]:
        x0, y0, pw, ph = rect
        tx = (temp - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN)
        ty = duty / 100.0
        return x0 + tx * pw, y0 + (1.0 - ty) * ph

    def _from_px(self, x: float, y: float, rect: tuple[float, float, float, float]) -> tuple[float, float]:
        x0, y0, pw, ph = rect
        temp = self.TEMP_MIN + ((x - x0) / pw) * (self.TEMP_MAX - self.TEMP_MIN)
        duty = (1.0 - (y - y0) / ph) * 100.0
        return temp, duty

    def _nearest_node(self, x: float, y: float, rect: tuple[float, float, float, float], max_dist: float = 18.0) -> int | None:
        best_idx = None
        best_d = max_dist
        for i, (t, d) in enumerate(self._points):
            px, py = self._to_px(t, d, rect)
            dist = math.hypot(x - px, y - py)
            if dist <= best_d:
                best_d = dist
                best_idx = i
        return best_idx

    def _on_motion(self, _ctrl, x: float, y: float) -> None:
        rect = self._plot_rect(self.get_width(), self.get_height())
        idx = self._nearest_node(x, y, rect)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.set_cursor_from_name("grab" if idx is not None else "default")
            self.queue_draw()

    def _on_leave(self, _ctrl) -> None:
        self._hover_idx = None
        self.set_cursor_from_name("default")
        self.queue_draw()

    def _on_drag_begin(self, _gesture, start_x: float, start_y: float) -> None:
        self.grab_focus()
        rect = self._plot_rect(self.get_width(), self.get_height())
        idx = self._nearest_node(start_x, start_y, rect, max_dist=22.0)
        self._drag_idx = idx
        self._drag_start_x = start_x
        self._drag_start_y = start_y
        if idx is not None:
            self._selected_idx = idx
            self.set_cursor_from_name("grabbing")
            self.queue_draw()

    def _on_drag_update(self, _gesture, offset_x: float, offset_y: float) -> None:
        if self._drag_idx is None:
            return
        rect = self._plot_rect(self.get_width(), self.get_height())
        cur_x = self._drag_start_x + offset_x
        cur_y = self._drag_start_y + offset_y
        temp, duty = self._from_px(cur_x, cur_y, rect)
        self._points = curves_math.clamp_dragged_point(self._points, self._drag_idx, round(temp), round(duty))
        self.queue_draw()
        if self._on_preview:
            self._on_preview(list(self._points))

    def _on_drag_end(self, _gesture, _offset_x: float, _offset_y: float) -> None:
        if self._drag_idx is not None:
            self._drag_idx = None
            self.set_cursor_from_name("default")
            self.queue_draw()
            if self._on_changed:
                self._on_changed(list(self._points))

    def _on_key_pressed(self, _ctrl, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        step = 5 if (state & Gdk.ModifierType.SHIFT_MASK) else 1
        t, d = self._points[self._selected_idx]
        if keyval == Gdk.KEY_Tab:
            self._selected_idx = (self._selected_idx + 1) % len(self._points)
            self.queue_draw()
            return True
        if keyval == Gdk.KEY_Left:
            t -= step
        elif keyval == Gdk.KEY_Right:
            t += step
        elif keyval == Gdk.KEY_Up:
            d += step
        elif keyval == Gdk.KEY_Down:
            d -= step
        else:
            return False
        self._points = curves_math.clamp_dragged_point(self._points, self._selected_idx, t, d)
        self.queue_draw()
        if self._on_preview:
            self._on_preview(list(self._points))
        if self._on_changed:
            self._on_changed(list(self._points))
        return True

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        rect = self._plot_rect(width, height)
        x0, y0, pw, ph = rect

        # Fondo del gráfico
        if dark:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.03)
        else:
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.03)
        cr.rectangle(x0, y0, pw, ph)
        cr.fill()

        # Zona de piso de seguridad (>=85°C, <30%)
        sx1, sy_top = self._to_px(curves_math.FLOOR_TEMP_C, curves_math.FLOOR_PCT, rect)
        sx2, sy_bot = self._to_px(self.TEMP_MAX, 0, rect)
        cr.set_source_rgba(0.95, 0.32, 0.25, 0.12)
        cr.rectangle(sx1, sy_top, sx2 - sx1, sy_bot - sy_top)
        cr.fill()
        cr.set_dash([4.0, 4.0])
        cr.set_line_width(1.2)
        cr.set_source_rgba(0.95, 0.42, 0.30, 0.65)
        cr.move_to(sx1, sy_bot)
        cr.line_to(sx1, sy_top)
        cr.line_to(sx2, sy_top)
        cr.stroke()
        cr.set_dash([])

        # Rejilla y etiquetas de ejes
        grid_col = (1.0, 1.0, 1.0, 0.08) if dark else (0.0, 0.0, 0.0, 0.09)
        label_col = (0.65, 0.70, 0.78) if dark else (0.35, 0.40, 0.48)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5)

        for pct in (0, 25, 50, 75, 100):
            _, gy = self._to_px(self.TEMP_MIN, pct, rect)
            cr.set_line_width(1.0)
            cr.set_source_rgba(*grid_col)
            cr.move_to(x0, gy)
            cr.line_to(x0 + pw, gy)
            cr.stroke()
            cr.set_source_rgb(*label_col)
            txt = f"{pct}%"
            ext = cr.text_extents(txt)
            cr.move_to(x0 - ext.width - 8.0, gy + 4.0)
            cr.show_text(txt)

        for temp in range(30, 101, 10):
            gx, _ = self._to_px(temp, 0, rect)
            cr.set_line_width(1.0)
            cr.set_source_rgba(*grid_col)
            cr.move_to(gx, y0)
            cr.line_to(gx, y0 + ph)
            cr.stroke()
            cr.set_source_rgb(*label_col)
            txt = f"{temp}°"
            ext = cr.text_extents(txt)
            cr.move_to(gx - ext.width / 2.0, y0 + ph + 18.0)
            cr.show_text(txt)

        # Área rellena bajo la curva
        px_pts = [self._to_px(t, d, rect) for t, d in self._points]
        if px_pts:
            grad = cairo.LinearGradient(0, y0, 0, y0 + ph)
            grad.add_color_stop_rgba(0.0, 1.0, 0.42, 0.0, 0.34)
            grad.add_color_stop_rgba(1.0, 1.0, 0.42, 0.0, 0.03)
            cr.move_to(x0, y0 + ph)
            cr.line_to(x0, px_pts[0][1])
            for px, py in px_pts:
                cr.line_to(px, py)
            cr.line_to(x0 + pw, px_pts[-1][1])
            cr.line_to(x0 + pw, y0 + ph)
            cr.close_path()
            cr.set_source(grad)
            cr.fill()

            # Línea de la curva (incluyendo extensiones planas antes del nodo 0 y tras el último)
            cr.set_line_width(2.6)
            cr.set_source_rgb(1.0, 0.48, 0.08)
            cr.move_to(x0, px_pts[0][1])
            for px, py in px_pts:
                cr.line_to(px, py)
            cr.line_to(x0 + pw, px_pts[-1][1])
            cr.stroke()

        # Marcador de temperatura en vivo
        if self._live_temp is not None:
            lt = max(self.TEMP_MIN, min(self.TEMP_MAX, self._live_temp))
            ld = curves_math.predict_duty(self._points, self._live_temp)
            lx, ly = self._to_px(lt, ld, rect)
            cr.set_dash([3.0, 3.0])
            cr.set_line_width(1.2)
            cr.set_source_rgba(0.0, 0.82, 1.0, 0.70)
            cr.move_to(lx, y0)
            cr.line_to(lx, y0 + ph)
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgba(0.0, 0.82, 1.0, 0.28)
            cr.arc(lx, ly, 9.0, 0, math.tau)
            cr.fill()
            cr.set_source_rgb(0.0, 0.82, 1.0)
            cr.arc(lx, ly, 4.5, 0, math.tau)
            cr.fill()

        # Nodos arrastrables
        for idx, (t, d) in enumerate(self._points):
            px, py = self._to_px(t, d, rect)
            active = idx in (self._hover_idx, self._drag_idx, self._selected_idx)
            r_node = 7.5 if active else 6.0
            if active:
                cr.set_source_rgba(1.0, 0.48, 0.08, 0.28)
                cr.arc(px, py, r_node + 5.0, 0, math.tau)
                cr.fill()
            cr.set_source_rgb(1.0, 0.48, 0.08)
            cr.arc(px, py, r_node, 0, math.tau)
            cr.fill()
            cr.set_line_width(2.0)
            cr.set_source_rgb(0.11, 0.13, 0.18) if dark else cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.arc(px, py, r_node, 0, math.tau)
            cr.stroke()

            if active:
                tag = f"{t}°C → {d}%"
                cr.set_font_size(10.5)
                ext = cr.text_extents(tag)
                tx = max(x0 + 4, min(x0 + pw - ext.width - 8, px - ext.width / 2.0))
                ty = py - 14.0 if py > y0 + 26 else py + 22.0
                cr.set_source_rgba(0.08, 0.10, 0.14, 0.88)
                cr.rectangle(tx - 5, ty - 12, ext.width + 10, 16)
                cr.fill()
                cr.set_source_rgb(0.98, 0.98, 0.99)
                cr.move_to(tx, ty)
                cr.show_text(tag)
