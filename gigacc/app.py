"""Ventana principal y ciclo de aplicación GTK4 / Libadwaita."""
from __future__ import annotations

import pkgutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, __version__  # noqa: E402
from .backend import hotkeys  # noqa: E402
from .backend.gigactl_client import GigactlClient, Telemetry  # noqa: E402
from .backend.power_client import PowerClient, find_backlight_device, read_cpu_power_state  # noqa: E402
from .backend.sysinfo import (  # noqa: E402
    NvidiaMetrics,
    SystemMetrics,
    read_hardware_info,
    read_nvidia_async,
    read_system_metrics,
)
from .pages.dashboard import DashboardPage  # noqa: E402
from .pages.fans import FansPage  # noqa: E402
from .pages.keyboard import KeyboardPage  # noqa: E402
from .pages.performance import PerformancePage  # noqa: E402
from .pages.power import PowerPage  # noqa: E402

NAV_ITEMS = (
    ("dashboard", "Panel General", "view-grid-symbolic"),
    ("keyboard", "Teclado RGB y Brillo", "input-keyboard-symbolic"),
    ("fans", "Ventiladores", "weather-windy-symbolic"),
    ("performance", "Rendimiento", "utilities-system-monitor-symbolic"),
    ("power", "Energía", "preferences-power-and-battery-symbolic"),
)


def _load_brand_image() -> Gtk.Image:
    svg_bytes = pkgutil.get_data("gigacc", "app-icon.svg")
    if svg_bytes:
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.set_size(34, 34)
            loader.write(svg_bytes)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is not None:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                img = Gtk.Image.new_from_paintable(texture)
                img.set_pixel_size(34)
                return img
        except Exception:
            pass
    img = Gtk.Image.new_from_icon_name("computer-symbolic")
    img.set_pixel_size(32)
    return img


class MainWindow(Adw.ApplicationWindow):
    """Ventana principal de GigaControl Center con barra lateral y 5 secciones."""

    def __init__(self, app: Adw.Application, initial_page: str = "dashboard", smoke_test: bool = False) -> None:
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(1080, 720)
        self.set_size_request(860, 580)

        self._closed = False
        self._poll_source = 0
        self._smoke_source = 0
        self._hw = read_hardware_info()
        self._last_sys: SystemMetrics = read_system_metrics()
        self._last_gpu: NvidiaMetrics = NvidiaMetrics(available=False)
        self._last_ec_tel: Telemetry | None = None
        self._nav_rows: dict[str, Gtk.ListBoxRow] = {}

        self._gigactl = GigactlClient(
            on_telemetry=self._on_ec_telemetry,
            on_availability=self._on_gigactl_availability,
            on_state=self._on_gigactl_state,
            on_error=self.show_toast,
        )
        self._power = PowerClient(
            on_profile_changed=self._on_power_profile_changed,
            on_graphics_changed=self._on_graphics_changed,
            on_error=self.show_toast,
        )

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.add_css_class("gcc-sidebar")
        sidebar.set_size_request(242, -1)
        sidebar.set_margin_top(0)
        sidebar.set_margin_bottom(14)

        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand_box.set_margin_top(16)
        brand_box.set_margin_start(14)
        brand_box.set_margin_end(14)
        brand_box.append(_load_brand_image())
        brand_txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        lbl_b = Gtk.Label(label="GIGA CONTROL", xalign=0.0)
        lbl_b.add_css_class("gcc-brand-title")
        lbl_sub = Gtk.Label(label=self._hw.product_name, xalign=0.0)
        lbl_sub.add_css_class("gcc-brand-sub")
        brand_txt.append(lbl_b)
        brand_txt.append(lbl_sub)
        brand_box.append(brand_txt)
        sidebar.append(brand_box)

        self._side_status = Gtk.Label(label="Iniciando enlace EC…", xalign=0.0)
        self._side_status.add_css_class("gcc-pill")
        self._side_status.add_css_class("gcc-pill-warn")
        self._side_status.set_margin_start(14)
        self._side_status.set_margin_end(14)
        sidebar.append(self._side_status)

        self._nav_list = Gtk.ListBox()
        self._nav_list.add_css_class("gcc-nav-list")
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.set_vexpand(True)
        for pid, pname, icon_name in NAV_ITEMS:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            ico = Gtk.Image.new_from_icon_name(icon_name)
            ico.set_pixel_size(18)
            lbl = Gtk.Label(label=pname, xalign=0.0)
            row_box.append(ico)
            row_box.append(lbl)
            row = Gtk.ListBoxRow(child=row_box)
            row.page_id = pid  # type: ignore[attr-defined]
            self._nav_list.append(row)
            self._nav_rows[pid] = row
        self._nav_list.connect("row-selected", self._on_nav_selected)
        sidebar.append(self._nav_list)

        side_footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side_footer.set_margin_start(14)
        side_footer.set_margin_end(14)

        self._theme_btn = Gtk.Button()
        self._update_theme_btn_label()
        self._theme_btn.connect("clicked", self._on_toggle_theme)
        side_footer.append(self._theme_btn)

        ver_lbl = Gtk.Label(label=f"v{__version__}  ·  Backend gigactld", xalign=0.0)
        ver_lbl.add_css_class("gcc-muted")
        side_footer.append(ver_lbl)
        sidebar.append(side_footer)

        split.append(sidebar)

        right_toolbar = Adw.ToolbarView()
        right_toolbar.set_hexpand(True)
        header = Adw.HeaderBar()
        header.set_show_title(False)
        right_toolbar.add_top_bar(header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(140)

        self._dashboard_page = DashboardPage(
            self._gigactl, self._power, self._hw, self.show_toast, self.navigate_to
        )
        self._keyboard_page = KeyboardPage(self._gigactl, self._power, self.show_toast)
        self._fans_page = FansPage(self._gigactl, self.show_toast)
        self._performance_page = PerformancePage(self._power, self._hw, self.show_toast)
        self._power_page = PowerPage(self._gigactl, self._power, self.show_toast)

        self._stack.add_named(self._dashboard_page, "dashboard")
        self._stack.add_named(self._keyboard_page, "keyboard")
        self._stack.add_named(self._fans_page, "fans")
        self._stack.add_named(self._performance_page, "performance")
        self._stack.add_named(self._power_page, "power")

        right_toolbar.set_content(self._stack)
        split.append(right_toolbar)

        self._toasts = Adw.ToastOverlay(child=split)
        self.set_content(self._toasts)

        # Atajos locales dentro de la ventana para teclas multimedia/Fn y NumPad
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_ctrl)

        self.navigate_to(initial_page if initial_page in self._nav_rows else "dashboard")

        self.connect("close-request", self._on_close)
        self._gigactl.start()
        self._power.start()
        self._poll_system()
        self._poll_source = GLib.timeout_add_seconds(2, self._poll_system)

        if smoke_test:
            self._schedule_smoke_test()

    def _on_window_key_pressed(self, _ctrl, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        kbd = self._gigactl.keyboard_state()
        cur_on = kbd.enabled if kbd else True
        cur_pct = kbd.brightness_pct if kbd else 100
        cur_rgb = kbd.rgb if kbd else (0, 0, 255)

        action: str | None = None
        if keyval == Gdk.KEY_KbdLightOnOff:
            action = "toggle"
        elif keyval == Gdk.KEY_KbdBrightnessUp:
            action = "up"
        elif keyval == Gdk.KEY_KbdBrightnessDown:
            action = "down"
        elif keyval == Gdk.KEY_Launch1:
            action = "color-next"
        elif (state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK)) == (
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        ):
            if keyval == Gdk.KEY_KP_Divide:
                action = "toggle"
            elif keyval == Gdk.KEY_KP_Add:
                action = "up"
            elif keyval == Gdk.KEY_KP_Subtract:
                action = "down"
            elif keyval == Gdk.KEY_KP_Multiply:
                action = "color-next"

        if action is None:
            return False

        if action == "toggle":
            new_on, new_pct = hotkeys.compute_toggle(cur_on, cur_pct)
            self._gigactl.set_keyboard_enabled(new_on)
            if new_on and new_pct != cur_pct:
                self._gigactl.set_keyboard_brightness(new_pct)
            self.show_toast("Iluminación del teclado encendida." if new_on else "Iluminación del teclado apagada.")
        elif action == "up":
            _on, new_pct = hotkeys.compute_next_brightness_up(cur_on, cur_pct)
            if not cur_on:
                self._gigactl.set_keyboard_enabled(True)
            self._gigactl.set_keyboard_brightness(new_pct)
            self.show_toast(f"Brillo del teclado: {new_pct}%")
        elif action == "down":
            new_on, new_pct = hotkeys.compute_next_brightness_down(cur_on, cur_pct)
            self._gigactl.set_keyboard_brightness(new_pct)
            if not new_on:
                self._gigactl.set_keyboard_enabled(False)
            self.show_toast(f"Brillo del teclado: {new_pct}%")
        elif action == "color-next":
            cname, (r, g, b) = hotkeys.compute_next_color(cur_rgb)
            self._gigactl.set_keyboard_color(r, g, b)
            self.show_toast(f"Color del teclado: {cname}")
        return True

    def show_toast(self, message: str) -> None:
        if self._closed or not message:
            return
        toast = Adw.Toast.new(message)
        toast.set_timeout(4)
        self._toasts.add_toast(toast)

    def navigate_to(self, page_id: str) -> None:
        row = self._nav_rows.get(page_id)
        if row is not None:
            self._nav_list.select_row(row)
        self._stack.set_visible_child_name(page_id)

    def _on_nav_selected(self, _lb: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        pid = getattr(row, "page_id", "dashboard")
        self._stack.set_visible_child_name(pid)

    def _on_toggle_theme(self, _btn) -> None:
        sm = Adw.StyleManager.get_default()
        if sm.get_dark():
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self._update_theme_btn_label()

    def _update_theme_btn_label(self) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        self._theme_btn.set_label("Cambiar a tema claro" if dark else "Cambiar a tema oscuro")

    def _on_ec_telemetry(self, t: Telemetry) -> None:
        if self._closed:
            return
        self._last_ec_tel = t
        self._dashboard_page.update_telemetry(t, self._last_sys, self._last_gpu)
        self._fans_page.update_telemetry(t)

    def _on_gigactl_availability(self, ok: bool) -> None:
        if self._closed:
            return
        if ok:
            self._side_status.set_label("EC conectado · gigactld")
            self._side_status.set_css_classes(["gcc-pill", "gcc-pill-ok"])
        else:
            self._side_status.set_label("gigactld desconectado")
            self._side_status.set_css_classes(["gcc-pill", "gcc-pill-err"])
        self._sync_all_control_states()

    def _on_gigactl_state(self) -> None:
        if self._closed:
            return
        self._sync_all_control_states()

    def _on_power_profile_changed(self, _prof: str) -> None:
        if self._closed:
            return
        self._sync_all_control_states()

    def _on_graphics_changed(self, _mode: str, _sw: bool, _pwr: bool) -> None:
        if self._closed:
            return
        self._performance_page.update_power_state(
            self._power.power_profile,
            self._power.graphics_mode,
            self._power.switchable_graphics,
        )

    def _sync_all_control_states(self) -> None:
        self._dashboard_page.update_status(
            gigactl_ok=self._gigactl.available,
            ec_status=self._gigactl.ec_status(),
            fan_profile=self._gigactl.active_profile(),
            power_profile=self._power.power_profile,
        )
        self._keyboard_page.sync_from_daemon()
        self._keyboard_page.refresh_hotkey_status()
        self._fans_page.sync_from_daemon()
        self._performance_page.update_power_state(
            self._power.power_profile,
            self._power.graphics_mode,
            self._power.switchable_graphics,
        )

    def _poll_system(self) -> bool:
        if self._closed:
            return False
        self._last_sys = read_system_metrics()
        backlight = find_backlight_device()
        cpu_pwr = read_cpu_power_state()

        self._dashboard_page.update_telemetry(self._last_ec_tel, self._last_sys, self._last_gpu)
        self._dashboard_page.update_backlight(backlight)
        self._keyboard_page.update_backlight(backlight)
        self._performance_page.update_metrics(self._last_sys, self._last_gpu, cpu_pwr)
        self._power_page.update_metrics(self._last_sys, self._last_gpu, backlight, cpu_pwr)

        def on_gpu(gpu: NvidiaMetrics) -> bool:
            if self._closed:
                return False
            self._last_gpu = gpu
            self._dashboard_page.update_telemetry(self._last_ec_tel, self._last_sys, gpu)
            self._performance_page.update_metrics(self._last_sys, gpu, read_cpu_power_state())
            self._power_page.update_metrics(self._last_sys, gpu, find_backlight_device(), read_cpu_power_state())
            return False

        read_nvidia_async(on_gpu)
        return True

    def _schedule_smoke_test(self) -> None:
        pages = [item[0] for item in NAV_ITEMS]
        idx = 0

        def step() -> bool:
            nonlocal idx
            if self._closed:
                return False
            if idx < len(pages):
                self.navigate_to(pages[idx])
                idx += 1
                return True
            print(
                f"SMOKE_TEST_OK: gigactl_available={self._gigactl.available} "
                f"telemetry={self._last_ec_tel} power_profile={self._power.power_profile}",
                flush=True,
            )
            self.close()
            return False

        self._smoke_source = GLib.timeout_add(320, step)

    def _on_close(self, _win) -> bool:
        self._closed = True
        for attr in ("_poll_source", "_smoke_source"):
            sid = getattr(self, attr)
            if sid:
                GLib.source_remove(sid)
                setattr(self, attr, 0)
        self._dashboard_page.cancel_pending()
        self._keyboard_page.cancel_pending()
        return False


class GigaControlApp(Adw.Application):
    """Aplicación Adwaita principal."""

    def __init__(self, initial_page: str = "dashboard", smoke_test: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._initial_page = initial_page
        self._smoke_test = smoke_test
        self._window: MainWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        css_bytes = pkgutil.get_data("gigacc", "style.css")
        if css_bytes:
            provider = Gtk.CssProvider()
            provider.load_from_string(css_bytes.decode("utf-8"))
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(
                self,
                initial_page=self._initial_page,
                smoke_test=self._smoke_test,
            )
        self._window.present()
