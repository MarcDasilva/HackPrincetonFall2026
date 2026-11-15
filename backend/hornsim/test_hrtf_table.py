"""hornsim.hrtf_table against known answers: a point source in free field, and a rigid sphere.

The reciprocity run puts a click at the receiver and projects the field on a box around it to the far
field (Kirchhoff). Two checks with exact answers:
  free field   a point source radiates the same in every direction, and moving it off the origin by s
               shifts the far-field phase by k r̂·s (the delay that keeps the interaural time difference)
  rigid sphere a receiver on the surface of a rigid sphere, sound from far away: the classic series
               solution (Rayleigh; Duda & Martens 1998, JASA 104:3048). Compared as band levels relative
               to frontal incidence, the way the scene grid uses the table.
Both run on the CPU on a coarse 3 mm grid so they stay deterministic and quick, with the PML
hrtf_table adds around the grid; one test runs the sphere without it to show what it removes.
"""
import math

import numpy as np
import pytest
import torch
from scipy.special import eval_legendre, spherical_jn, spherical_yn

from . import hrtf_table as ht

DX = 3.0
CPU = torch.device("cpu")


def _box(half_mm):
    n = 2 * int(round(half_mm / DX)) + 1                   # odd: a cell centre sits exactly at 0
    origin = np.full(3, -(n // 2) * DX)
    centres = [origin[i] + np.arange(n) * DX for i in range(3)]
    return (n, n, n), origin, centres


def _cell(origin, p_mm):
    return tuple(int(round(v)) for v in (np.asarray(p_mm) - origin) / DX)


def _dirs(azimuths):
    return np.array([ht.unit(a, 0.0) for a in azimuths])


def test_free_field_point_source_is_omnidirectional_with_the_right_phase():
    shape, origin, _ = _box(60.0)
    solid = np.zeros(shape, bool)
    s = np.array([15.0, 0.0, 0.0])                          # source 15 mm toward +x (the right)
    src = _cell(origin, s)
    s = origin + np.array(src) * DX                         # exactly where the cell is
    az = np.arange(0, 360, 30)
    F = ht.run_ear(solid, np.zeros(shape, bool), src, origin, DX, CPU, log=lambda m: None, dirs=_dirs(az))
    _, f = ht.bins()

    # magnitude: the same in every direction (to 6 kHz, ~19 cells per wavelength)
    lvl = 20 * np.log10(np.abs(F[:, f <= 6000]))
    assert np.ptp(lvl, axis=0).max() < 0.3

    # phase: right (az 90) minus left (az 270) is 2 k s_x, the round-trip of the offset
    j = int(np.argmin(np.abs(f - 1000)))
    k = 2 * np.pi * f[j] / ht.C
    i90, i270 = list(az).index(90), list(az).index(270)
    dphi = np.angle(F[i90, j] / F[i270, j])
    assert dphi == pytest.approx(2 * k * s[0] * 1e-3, abs=0.05)


def _sphere_surface_pressure(ka, cos_gamma, m_max=60):
    """|p| on a rigid sphere for a unit plane wave, gamma = angle between the receiver and the source
    direction (0 = facing the source). Series solution, up to a constant phase."""
    m = np.arange(m_max)
    dh = (spherical_jn(m[:, None], ka, derivative=True) - 1j * spherical_yn(m[:, None], ka, derivative=True))
    terms = (2 * m[:, None] + 1) * (1j ** m[:, None]) * eval_legendre(m[:, None], cos_gamma) / dh
    return np.abs(terms.sum(0)) / ka ** 2


def _sphere_band_errors(air_mm, pml=None):
    """dB error per (direction, band <= 4 kHz) against the series solution, relative to frontal
    incidence, for a 60 mm rigid sphere with `air_mm` of air to the grid edge."""
    a = 60.0                                                # sphere radius, mm
    shape, origin, (cx, cy, cz) = _box(a + air_mm)
    X, Y, Z = np.meshgrid(cx, cy, cz, indexing="ij")
    solid = X ** 2 + Y ** 2 + Z ** 2 <= a ** 2
    src = _cell(origin, [a + DX, 0.0, 0.0])                 # first air cell outside the sphere, on +x
    assert not solid[src] and solid[src[0] - 1, src[1], src[2]]
    r_rec = np.linalg.norm(origin + np.array(src) * DX)

    az = np.array([0, 45, 90, 135, 180, 225, 270])          # 90 faces the receiver, 270 is the far side
    F = ht.run_ear(solid, np.zeros(shape, bool), src, origin, DX, CPU, log=lambda m: None, dirs=_dirs(az), pml=pml)
    _, f = ht.bins()
    sim = np.array([ht.band_power(F[i], f) for i in range(len(az))])

    # the same band averaging (5 log-spaced points per band) on the analytic response
    from .scoring import SII_FREQS
    ff = (SII_FREQS[:, None] * 2.0 ** (-1 / 6 + (np.arange(5) + 0.5) / 15)).ravel()
    gamma = np.radians(90.0 - az)                           # angle between +x (receiver) and the source
    ref = np.array([(_sphere_surface_pressure(2 * np.pi * ff / ht.C * r_rec * 1e-3, np.cos(g)) ** 2)
                    .reshape(len(SII_FREQS), 5).mean(1) for g in gamma])
    keep = SII_FREQS <= 4000                                # 3 mm cells: ~29 per wavelength at 4 kHz
    sim_db = 10 * np.log10(sim / sim[0])[:, keep]
    ref_db = 10 * np.log10(ref / ref[0])[:, keep]
    return sim_db - ref_db, sim_db, list(az), SII_FREQS[keep]


def test_rigid_sphere_matches_the_series_solution():
    # 33 mm of air, about what head_grid leaves around the head (EAR_PAD_MM, BOX_PAD_MM), and the PML.
    err, sim_db, az, bands = _sphere_band_errors(33.0)
    err = np.abs(err)
    assert err.max() < 1.2, f"worst band error {err.max():.2f} dB"       # far side, 4 kHz: staircased sphere
    assert err.mean() < 0.1, f"mean band error {err.mean():.2f} dB"
    assert err[:, bands <= 800].max() < 0.15, "low bands: nothing but the box edges can spoil these"
    # the physics the scene grid relies on: the near side is louder than the far side at 2-4 kHz
    # (the series solution gives 3.5-4 dB there; the staircased far-side bright spot narrows it to ~2.5)
    hi = bands >= 2000
    assert (sim_db[az.index(90), hi] - sim_db[az.index(270), hi]).min() > 2


def test_pml_removes_the_box_edge_reflections():
    """Same sphere and box without the PML: the plain absorbing faces reflect obliquely arriving sound
    (R = (cos θ - 1)/(cos θ + 1)), worst 2.9 dB and mean 0.32 dB; with the PML worst 1.0 and mean 0.06."""
    plain = np.abs(_sphere_band_errors(33.0, pml=0)[0])
    pml = np.abs(_sphere_band_errors(33.0)[0])
    assert plain.mean() > 3 * pml.mean()
    assert plain.max() > 2.0 > 1.2 > pml.max()
