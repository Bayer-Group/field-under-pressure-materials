# -*- coding: utf-8 -*-
"""
Polskie stałe układów współrzędnych i zasięgów geograficznych.
Zasada: obliczenia metryczne w PL wykonujemy w EPSG:2180 (brak zniekształceń pola).
"""

EPSG_POLAND_1992 = 2180   # PUWG 1992 (metryczny, państwowy układ odniesienia w Polsce)
EPSG_WGS84 = 4326         # WGS 84 (stopnie dziesiętne, GPS, standard API)
EPSG_WEB_MERCATOR = 3857  # Web Mercator (kafelki rastrowe, MapLibre, OpenStreetMap)

# Bounding box Polski w EPSG:4326 [min_lon, min_lat, max_lon, max_lat]
BBOX_POLAND_4326 = [14.12, 49.00, 24.15, 54.84]

# Bounding box Polski w EPSG:2180 [min_x, min_y, max_x, max_y]
BBOX_POLAND_2180 = [170000.0, 130000.0, 860000.0, 780000.0]
