from autopilot import carbon


def test_gco2e_formula():
    # 2 J/token -> 2000 J per 1k tokens = 5.556e-4 kWh; x571 g/kWh = 0.317 g
    g = carbon.gco2e_per_1k_tokens(2.0)
    assert abs(g - 2000.0 / 3.6e6 * carbon.GRID_G_PER_KWH) < 1e-9


def test_labels_cover_scale():
    assert carbon.label(0.1) == "A"
    assert carbon.label(2.0) in "ABC"      # ~0.32 g at the default grid factor
    assert carbon.label(1000.0) == "G"     # absurdly inefficient -> worst band


def test_annotate_reports_method_transparency():
    a = carbon.annotate(1.5)
    assert set(a) == {"gco2e_per_1k_tokens", "label", "grid_g_per_kwh", "grid_source"}
