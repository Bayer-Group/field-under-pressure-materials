# -*- coding: utf-8 -*-
"""
Przykładowy moduł obliczeń geometrycznych (starter).
"""

def calculate_bounding_box(coords: list):
    """Zwraca [min_x, min_y, max_x, max_y] z listy par współrzędnych."""
    if not coords:
        return [0.0, 0.0, 0.0, 0.0]
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    return [min(xs), min(ys), max(xs), max(ys)]
