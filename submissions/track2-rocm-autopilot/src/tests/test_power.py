from autopilot.power import EnergyMeter


class FakeNvml:
    def __init__(self):
        self.vals = iter([1_000_000, 4_600_000])  # millijoules

    def energy(self):
        return next(self.vals)


def test_energy_meter_computes_delta():
    m = EnergyMeter(_backend=FakeNvml())
    with m:
        pass
    assert abs(m.joules - 3600.0) < 1e-6
    assert m.mean_power_w > 0
