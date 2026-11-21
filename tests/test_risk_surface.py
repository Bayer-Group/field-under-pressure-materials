"""Unit tests of the risk index (septoria.risk_index) and of the risk surface (services/risk_surface.py), no database."""
import os
import struct
import sys
import tomllib
import unittest
import zlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.domain import septoria as sp  # noqa: E402
from backend.app.services import risk_surface as rs  # noqa: E402

with open(os.path.join(BASE_DIR, "config", "septoria.toml"), "rb") as fh:
    RULES = sp.Rules.from_config(tomllib.load(fh))


def index_class(i):
    return "low" if i < 0.5 else ("medium" if i < 1.0 else "high")


def lattice_points(values, lon0=20.0, lat0=52.0, step=0.044, jitter=0.0):
    """values[j][i] on a regular lattice (None = no cell); jitter shifts every other column a little, as the source data does."""
    return [(lon0 + i * step + (jitter if i % 2 else 0.0), lat0 + j * step, v)
            for j, line in enumerate(values) for i, v in enumerate(line) if v is not None]


class RiskIndex(unittest.TestCase):
    def test_agrees_with_the_classes_for_every_whole_hour(self):
        for h in range(0, 73):
            self.assertEqual(index_class(sp.risk_index(h, RULES)), sp.classify(h, RULES), f"H={h}")

    def test_anchors_and_monotone(self):
        self.assertEqual([sp.risk_index(h, RULES) for h in (0, 5, 10, 15, 20, 40)], [0.0, 0.25, 0.5, 0.75, 1.0, 1.0])
        vals = [sp.risk_index(h / 4, RULES) for h in range(0, 4 * 73)]
        self.assertTrue(all(a <= b for a, b in zip(vals, vals[1:])))

    def test_fractions_none_negative(self):
        self.assertAlmostEqual(sp.risk_index(14.5, RULES), 0.725)
        self.assertEqual(sp.risk_index(19.99, RULES) < 1.0, True)
        self.assertIsNone(sp.risk_index(None, RULES))
        self.assertEqual(sp.risk_index(-3, RULES), 0.0)

    def test_other_thresholds_and_degenerate_ones(self):
        r = sp.Rules(**{**RULES.__dict__, "threshold_medium": 6, "threshold_high": 18})
        for h in range(0, 73):
            self.assertEqual(index_class(sp.risk_index(h, r)), sp.classify(h, r), f"H={h}")
        flat = sp.Rules(**{**RULES.__dict__, "threshold_medium": 20, "threshold_high": 20})     # no division by zero
        self.assertEqual(sp.risk_index(20, flat), 1.0)
        self.assertEqual(sp.risk_index(10, flat), 0.25)


class Lattice(unittest.TestCase):
    def test_detects_a_lattice_with_rounded_coordinates(self):
        pts = lattice_points([[10, 12, None], [14, 30, 11], [9, None, 15]], jitter=0.001)
        lat = rs.detect_lattice([(lo, la, float(v)) for lo, la, v in pts])
        self.assertIsNotNone(lat)
        self.assertEqual(len(lat["nodes"]), 7)
        self.assertAlmostEqual(lat["dlon"], 0.044, places=3)

    def test_rejects_irregular_and_duplicated_points(self):
        self.assertIsNone(rs.detect_lattice([(20.0, 52.0, 1.0), (20.03, 52.0, 1.0), (20.09, 52.0, 1.0), (20.0, 52.044, 1.0)]))
        self.assertIsNone(rs.detect_lattice([(20.0, 52.0, 1.0), (20.0001, 52.0001, 2.0), (20.044, 52.0, 1.0), (20.0, 52.044, 1.0)]))
        self.assertIsNone(rs.detect_lattice([(20.0, 52.0, 1.0)]))


class Interpolation(unittest.TestCase):
    PEAK = [[12, 12, 12, 12, 12], [12, 12, 30, 12, 12], [12, 12, 12, 12, 12]]

    def build(self, values, **kw):
        return rs.build(lattice_points(values), method="interpolate", resolution_deg=kw.pop("resolution_deg", 0.002), **kw)

    def pixel(self, grid, lon, lat):
        west, south, east, north = grid["bounds"]
        r = grid["resolution_deg"]
        return grid["values"][int((north - lat) / r)][int((lon - west) / r)]

    def test_exact_at_the_nodes_and_no_overshoot(self):
        g = self.build(self.PEAK)
        self.assertEqual(g["method"], "interpolate")
        self.assertAlmostEqual(self.pixel(g, 20.0 + 2 * 0.044, 52.0 + 0.044), 30.0, delta=0.7)       # the peak keeps its value
        self.assertAlmostEqual(self.pixel(g, 20.0 + 0.044, 52.0 + 0.044), 12.0, delta=0.7)
        vals = [v for line in g["values"] for v in line if v is not None]
        self.assertGreaterEqual(min(vals), 12.0 - 1e-6)
        self.assertLessEqual(max(vals), 30.0 + 1e-6)

    def test_keeps_a_peak_that_a_gaussian_on_the_capped_index_loses(self):
        """2 x 2 cells of 30 h in a sea of 12 h: the interpolated surface has high (>= 20 h) pixels; the mean of the capped
        index over the same neighbourhood never reaches 1.0 (the first version of the surface showed 0 % high)."""
        block = [[12] * 6 for _ in range(6)]
        for j in (2, 3):
            for i in (2, 3):
                block[j][i] = 30
        g = self.build(block, resolution_deg=0.004)
        high = sum(1 for line in g["values"] for v in line if v is not None and sp.risk_index(v, RULES) >= 1.0)
        self.assertGreater(high, 0)
        pts = [(lon, lat, sp.risk_index(h, RULES)) for lon, lat, h in lattice_points(block)]
        gauss = rs.smooth([(a, b, float(c)) for a, b, c in pts], resolution_deg=0.004, sigma_km=5.0, max_distance_km=4.0)
        self.assertLess(max(v for line in gauss["values"] for v in line if v is not None), 1.0)

    def test_follows_the_outline_of_the_data(self):
        g = self.build([[12, None], [None, 30]], resolution_deg=0.004)
        self.assertTrue(any(v is None for line in g["values"] for v in line))                    # corners without data stay empty
        self.assertIsNotNone(self.pixel(g, 20.0, 52.0))                                           # a node
        self.assertIsNone(g["values"][0][0])                                                      # the padded corner, beyond 4 km
        far = rs.build(lattice_points([[12, 12], [12, 12]]), method="interpolate", resolution_deg=0.004, max_distance_km=0.5)
        self.assertTrue(any(v is None for line in far["values"] for v in line))

    def test_constant_field_stays_constant(self):
        g = self.build([[15, 15, 15], [15, 15, 15]])
        self.assertEqual({v for line in g["values"] for v in line if v is not None}, {15.0})

    def test_falls_back_to_smoothing_for_irregular_points(self):
        pts = [(20.0, 52.0, 10), (20.03, 52.01, 20), (20.09, 52.0, 15), (20.0, 52.044, 12)]
        g = rs.build(pts, method="interpolate", resolution_deg=0.02)
        self.assertEqual(g["method"], "smooth")
        self.assertIsNone(rs.build([(20.0, 52.0, None)]))


class Smooth(unittest.TestCase):
    def test_weighted_mean_stays_in_range(self):
        pts = lattice_points([[10, 30, 10], [30, 10, 30]])
        g = rs.build(pts, method="smooth", resolution_deg=0.02, sigma_km=5.0)
        vals = [v for line in g["values"] for v in line if v is not None]
        self.assertGreaterEqual(min(vals), 10.0 - 1e-6)
        self.assertLessEqual(max(vals), 30.0 + 1e-6)
        self.assertEqual(g["sigma_km"], 5.0)


class Exports(unittest.TestCase):
    GRID = [[None, 0.0, 0.5], [1.0, 0.25, None]]

    def test_png_is_valid_and_coloured(self):
        png = rs.to_png(self.GRID)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        pos, chunks = 8, {}
        while pos < len(png):
            n = struct.unpack(">I", png[pos:pos + 4])[0]
            kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + n]
            self.assertEqual(struct.unpack(">I", png[pos + 8 + n:pos + 12 + n])[0], zlib.crc32(kind + data) & 0xFFFFFFFF)
            chunks.setdefault(kind, []).append(data)
            pos += 12 + n
        w, h = struct.unpack(">II", chunks[b"IHDR"][0][:8])
        raw = zlib.decompress(b"".join(chunks[b"IDAT"]))
        self.assertEqual((w, h, len(raw)), (3, 2, (1 + 4 * 3) * 2))
        self.assertEqual(rs.colour(None), (0, 0, 0, 0))
        self.assertEqual(rs.colour(0.0)[:3], rs.RAMP[0][1])
        self.assertEqual(rs.colour(1.0)[:3], rs.RAMP[2][1])
        self.assertEqual(rs.colour(9.0)[:3], rs.RAMP[2][1])                    # clipped

    def test_asc(self):
        text = rs.to_asc(self.GRID, [20.0, 52.0, 20.06, 52.04], 0.02)
        lines = text.strip().split("\n")
        self.assertEqual(lines[:6], ["ncols 3", "nrows 2", "xllcorner 20.0", "yllcorner 52.0", "cellsize 0.02", "NODATA_value -9999"])
        self.assertEqual(lines[6], "-9999 0.000 0.500")
        self.assertEqual(lines[7], "1.000 0.250 -9999")

    def test_to_index_converts_hours(self):
        out = rs.to_index([[None, 5.0, 20.0, 31.7]], lambda h: sp.risk_index(h, RULES))
        self.assertEqual(out, [[None, 0.25, 1.0, 1.0]])


class Cache(unittest.TestCase):
    def setUp(self):
        rs._CACHE.clear()

    def test_built_once_per_key_and_bounded(self):
        calls = []

        def builder():
            calls.append(1)
            return {"x": 1}

        self.assertEqual(rs.cached(("a",), builder), {"x": 1})
        rs.cached(("a",), builder)
        self.assertEqual(len(calls), 1)
        for i in range(40):
            rs.cached(("k", i), lambda: {"i": i})
        self.assertLessEqual(len(rs._CACHE), 24)
        self.assertIsNone(rs.cached(("none",), lambda: None))                  # nothing is cached for "no data"
        self.assertNotIn(("none",), rs._CACHE)

    def test_fingerprint_follows_the_data(self):
        a = [(20.0, 52.0, 10), (20.044, 52.0, 12)]
        self.assertEqual(rs.fingerprint(a), rs.fingerprint(list(reversed(a))))
        self.assertNotEqual(rs.fingerprint(a), rs.fingerprint([(20.0, 52.0, 10), (20.044, 52.0, 13)]))


if __name__ == "__main__":
    unittest.main()
