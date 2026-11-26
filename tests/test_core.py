"""Pruebas unitarias para la lógica central, atajos y binario compilado."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from gigacc.backend import curves_math, gigactl_client, hotkeys, power_client, sysinfo

ROOT = Path(__file__).resolve().parents[1]


class TestCurvesMath(unittest.TestCase):
    def test_duty_for_interpolation_and_clamps(self) -> None:
        c = [(40, 20), (60, 40), (80, 80), (90, 90), (95, 100)]
        self.assertEqual(curves_math.duty_for(c, 25), 20)
        self.assertEqual(curves_math.duty_for(c, 50), 30)
        self.assertEqual(curves_math.duty_for(c, 70), 60)
        self.assertEqual(curves_math.duty_for(c, 99), 100)

    def test_safety_floor_at_85c(self) -> None:
        c = [(40, 10), (50, 15), (70, 20), (85, 20), (95, 25)]
        self.assertEqual(curves_math.predict_duty(c, 84), 20)
        self.assertEqual(curves_math.predict_duty(c, 85), 30)
        self.assertEqual(curves_math.predict_duty(c, 92), 30)

    def test_normalize_and_drag_monotonic(self) -> None:
        pts = curves_math.normalize([(90, 80), (40, 20), (70, 50)])
        self.assertEqual(len(pts), 5)
        for (t0, d0), (t1, d1) in zip(pts, pts[1:]):
            self.assertLess(t0, t1)
            self.assertLessEqual(d0, d1)

        dragged = curves_math.clamp_dragged_point(pts, 2, new_temp=999, new_duty=999)
        self.assertLess(dragged[2][0], dragged[3][0])
        self.assertLessEqual(dragged[2][1], dragged[3][1])


class TestHotkeysAndShortcuts(unittest.TestCase):
    def test_brightness_steps_and_toggle(self) -> None:
        self.assertEqual(hotkeys.compute_next_brightness_up(False, 0), (True, 20))
        self.assertEqual(hotkeys.compute_next_brightness_up(True, 20), (True, 40))
        self.assertEqual(hotkeys.compute_next_brightness_up(True, 100), (True, 100))

        self.assertEqual(hotkeys.compute_next_brightness_down(True, 60), (True, 40))
        self.assertEqual(hotkeys.compute_next_brightness_down(True, 20), (False, 0))
        self.assertEqual(hotkeys.compute_next_brightness_down(False, 0), (False, 0))

        self.assertEqual(hotkeys.compute_toggle(True, 80), (False, 80))
        self.assertEqual(hotkeys.compute_toggle(False, 80), (True, 80))
        self.assertEqual(hotkeys.compute_toggle(False, 0), (True, 60))

    def test_color_cycle_and_parsing(self) -> None:
        first_name, first_rgb = hotkeys.RGB_PALETTE[0]
        second_name, second_rgb = hotkeys.RGB_PALETTE[1]
        self.assertEqual(hotkeys.compute_next_color(first_rgb), (second_name, second_rgb))
        self.assertEqual(hotkeys.compute_next_color((1, 2, 3)), (first_name, first_rgb))

        self.assertEqual(hotkeys.parse_color_arg("rojo")[1], (255, 0, 0))
        self.assertEqual(hotkeys.parse_color_arg("#ff6b00")[1], (255, 107, 0))
        with self.assertRaises(ValueError):
            hotkeys.parse_color_arg("invalido")

    def test_cosmic_ron_merge_and_remove_preserves_user_entries(self) -> None:
        existing = (
            '{\n'
            '    (modifiers: [Super], key: "x"): Spawn("xterm")\n'
            '}\n'
        )
        merged = hotkeys.merge_cosmic_shortcuts_ron(existing, "/usr/local/bin/gigabyte-control-center")
        self.assertIn('(modifiers: [Super], key: "x"): Spawn("xterm"),', merged)
        self.assertIn('XF86KbdLightOnOff', merged)
        self.assertIn('KP_Add', merged)
        self.assertTrue(merged.startswith("{\n"))
        self.assertTrue(merged.strip().endswith("}"))

        # Idempotencia: fusionar dos veces no duplica entradas
        merged_twice = hotkeys.merge_cosmic_shortcuts_ron(merged, "/usr/local/bin/gigabyte-control-center")
        self.assertEqual(merged_twice.count("XF86KbdLightOnOff"), 1)

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "custom"
            hotkeys.install_cosmic_shortcuts("/tmp/bin/gcc", shortcuts_path=p)
            self.assertTrue(hotkeys.are_cosmic_shortcuts_installed(p))
            hotkeys.remove_cosmic_shortcuts(p)
            self.assertFalse(hotkeys.are_cosmic_shortcuts_installed(p))


class TestParsingAndClassification(unittest.TestCase):
    def test_model_classification(self) -> None:
        self.assertEqual(sysinfo.classify_model("GIGABYTE", "G6 KF"), "verified")
        self.assertEqual(sysinfo.classify_model("GIGABYTE", "G5 MD"), "expected")
        self.assertEqual(sysinfo.classify_model("LENOVO", "ThinkPad"), "unsupported")

    def test_nvidia_csv_parsing(self) -> None:
        line = "NVIDIA GeForce RTX 3050 Ti Laptop GPU, 595.104.02, 41, 12, 256, 4096, 18.45, 780, P8, [N/A]"
        m = sysinfo.parse_nvidia_smi_csv(line)
        self.assertTrue(m.available)
        self.assertEqual(m.temp_c, 41)
        self.assertEqual(m.util_pct, 12)
        self.assertEqual(m.mem_used_mib, 256)
        self.assertEqual(m.mem_total_mib, 4096)
        self.assertAlmostEqual(m.power_w, 18.45, places=2)
        self.assertEqual(m.clock_gfx_mhz, 780)
        self.assertEqual(m.pstate, "P8")

    def test_dbus_error_translation(self) -> None:
        msg = gigactl_client.translate_dbus_error("GDBus.Error:io.github.smairio.gigactl.Error.NotAuthorized: denied")
        self.assertIn("Autorización", msg)
        msg_ro = gigactl_client.translate_dbus_error("EcNotWritable: read-only")
        self.assertIn("solo lectura", msg_ro)

    def test_power_profile_normalization(self) -> None:
        self.assertEqual(power_client.normalize_power_profile("power-saver"), "battery")
        self.assertEqual(power_client.normalize_power_profile("Performance"), "performance")
        self.assertEqual(power_client.normalize_power_profile("anything"), "balanced")


class TestHelperValidation(unittest.TestCase):
    def test_bash_syntax_and_arg_validation(self) -> None:
        for script_rel in ("scripts/apply_power_tuning.sh", "scripts/install-hotkeys-driver.sh"):
            syn = subprocess.run(["bash", "-n", str(ROOT / script_rel)], capture_output=True, text=True)
            self.assertEqual(syn.returncode, 0, syn.stderr)

        script = ROOT / "scripts" / "apply_power_tuning.sh"
        res1 = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        self.assertEqual(res1.returncode, 2)

        res2 = subprocess.run(["bash", str(script), "--max-perf", "10"], capture_output=True, text=True)
        self.assertEqual(res2.returncode, 2)

        res3 = subprocess.run(["bash", str(script), "--epp", "invalid_mode"], capture_output=True, text=True)
        self.assertEqual(res3.returncode, 2)

        res4 = subprocess.run(["bash", str(script), "--no-turbo", "5"], capture_output=True, text=True)
        self.assertEqual(res4.returncode, 2)


class TestCompiledBinary(unittest.TestCase):
    def test_compiled_launcher_version_and_status(self) -> None:
        binary = ROOT / "build" / "gigabyte-control-center"
        self.assertTrue(binary.is_file(), f"Falta el binario compilado: {binary}")

        ver = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(ver.returncode, 0)
        self.assertIn("GigaControl Center", ver.stdout)

        st = subprocess.run([str(binary), "--status"], capture_output=True, text=True, timeout=15)
        self.assertEqual(st.returncode, 0)
        self.assertIn("GigaControl Center", st.stdout)
        self.assertIn("Equipo", st.stdout)


if __name__ == "__main__":
    unittest.main()
