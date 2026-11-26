"""Matemática de curvas de ventilador idéntica al contrato de gigactld.curve."""
from __future__ import annotations

from typing import Sequence

POINTS = 5
HYSTERESIS_C = 4
FLOOR_PCT = 30
FLOOR_TEMP_C = 85
TEMP_MIN = 30
TEMP_MAX = 100

Point = tuple[int, int]
Curve = list[Point]

BUILTIN_PROFILES: dict[str, Curve] = {
    "quiet": [(40, 20), (60, 25), (75, 40), (85, 60), (95, 100)],
    "balanced": [(40, 25), (55, 35), (70, 55), (85, 80), (95, 100)],
    "performance": [(40, 40), (55, 55), (70, 75), (85, 95), (95, 100)],
    "max": [(40, 100), (55, 100), (70, 100), (85, 100), (95, 100)],
}

PROFILE_LABELS_ES: dict[str, str] = {
    "quiet": "Silencioso",
    "balanced": "Equilibrado",
    "performance": "Rendimiento",
    "max": "Máximo (100%)",
    "firmware": "Auto BIOS (Firmware)",
    "custom": "Curva personalizada",
    "manual": "Manual fijo",
}


def profile_label_es(profile_id: str) -> str:
    return PROFILE_LABELS_ES.get(profile_id, profile_id.capitalize())


def duty_for(curve: Sequence[Point], temp: int | float) -> int:
    """Interpolación lineal por tramos igual que gigactld.curve.duty_for."""
    if not curve:
        return 0
    if temp <= curve[0][0]:
        return int(curve[0][1])
    if temp >= curve[-1][0]:
        return int(curve[-1][1])
    for (t0, d0), (t1, d1) in zip(curve, curve[1:]):
        if t0 <= temp <= t1:
            span = t1 - t0
            if span == 0:
                return int(d1)
            return int(round(d0 + (d1 - d0) * (temp - t0) / span))
    return int(curve[-1][1])


def apply_floor(duty: int, temp: int | float, floor_pct: int = FLOOR_PCT,
                floor_temp: int = FLOOR_TEMP_C) -> int:
    """Piso de seguridad del daemon: >= 30 % cuando la temperatura >= 85 °C."""
    if temp >= floor_temp:
        return max(int(duty), floor_pct)
    return int(duty)


def predict_duty(curve: Sequence[Point], temp: int | float) -> int:
    """Deber efectivo predicho incluyendo el piso de seguridad."""
    return apply_floor(duty_for(curve, temp), temp)


def normalize(points: Sequence[Point]) -> Curve:
    """Normaliza puntos al formato válido de 5 nodos estrictamente crecientes en °C
    y no decrecientes en % (idéntico a gigactld.curve.normalize)."""
    pts = [(max(0, min(100, int(t))), max(0, min(100, int(d)))) for t, d in points]
    pts.sort(key=lambda p: p[0])
    if not pts:
        pts = [(40, FLOOR_PCT)]

    if len(pts) > POINTS:
        idx = sorted({round(i * (len(pts) - 1) / (POINTS - 1)) for i in range(POINTS)})
        pts = [pts[i] for i in idx]
    while len(pts) < POINTS:
        pts.append(pts[-1])

    spaced: Curve = []
    for i, (t, d) in enumerate(pts):
        lo = 0 if i == 0 else spaced[-1][0] + 1
        hi = 100 - (POINTS - 1 - i)
        spaced.append((min(max(t, lo), hi), d))

    out: Curve = []
    last_d = 0
    for t, d in spaced:
        d = max(d, last_d)
        out.append((t, d))
        last_d = d
    return out


def clamp_dragged_point(points: Sequence[Point], index: int, new_temp: int, new_duty: int) -> Curve:
    """Ajusta el nodo `index` mientras el usuario lo arrastra manteniendo la
    curva monótona sin mover los nodos vecinos."""
    pts = list(normalize(points))
    if not (0 <= index < len(pts)):
        return pts

    lo_t = TEMP_MIN if index == 0 else pts[index - 1][0] + 1
    hi_t = TEMP_MAX if index == len(pts) - 1 else pts[index + 1][0] - 1
    lo_d = 0 if index == 0 else pts[index - 1][1]
    hi_d = 100 if index == len(pts) - 1 else pts[index + 1][1]

    clamped_t = max(lo_t, min(hi_t, int(round(new_temp))))
    clamped_d = max(lo_d, min(hi_d, int(round(new_duty))))
    pts[index] = (clamped_t, clamped_d)
    return pts
