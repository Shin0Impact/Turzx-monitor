from __future__ import annotations

import time

from turingscreen import sensors
from turingscreen.sensors import HISTORY_LEN, Drive, NvidiaGpu, RateMeter, Stats


def test_rate_meter_needs_two_readings():
    meter = RateMeter()
    assert meter.update(100, 200) is None
    time.sleep(0.05)
    down, up = meter.update(100 + 5000, 200 + 1000)
    assert down > up > 0


def test_rate_meter_never_goes_negative_when_a_counter_resets():
    meter = RateMeter()
    meter.update(1000)
    time.sleep(0.01)
    assert meter.update(10)[0] == 0


def test_stats_sample_reads_this_machine():
    stats = Stats()
    stats.sample()
    sample, history = stats.snapshot()
    assert sample.cpu_name
    assert 0 <= sample.cpu_load <= 100
    assert len(sample.cores) >= 1
    assert sample.ram_total > 0
    assert 0 <= sample.ram_percent <= 100
    assert sample.uptime > 0
    assert len(history.cpu) == len(history.down) == HISTORY_LEN


def test_history_keeps_a_fixed_length_and_the_newest_value():
    stats = Stats()
    for _ in range(HISTORY_LEN + 5):
        stats.sample()
    _, history = stats.snapshot()
    assert len(history.cpu) == HISTORY_LEN
    assert history.cpu[-1] == stats.snapshot()[0].cpu_load


def test_snapshot_is_a_copy():
    stats = Stats()
    _, history = stats.snapshot()
    history.cpu.append(999)
    assert 999 not in stats.snapshot()[1].cpu


def test_no_nvidia_card_reads_as_none(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pynvml", None)  # makes `import pynvml` fail
    gpu = NvidiaGpu()
    assert not gpu.available
    assert gpu.read() is None


def test_drives_that_do_not_exist_are_skipped():
    assert sensors.drive_usage(["/definitely/not/here"]) == ()


def test_drive_usage_reports_percent():
    drives = sensors.drive_usage(["/"])
    assert drives and isinstance(drives[0], Drive)
    assert 0 <= drives[0].percent <= 100


def test_cpu_name_is_trimmed_for_the_screen(monkeypatch):
    monkeypatch.setattr(sensors.platform, "processor", lambda: "AMD Ryzen 9 9900X 12-Core Processor")
    monkeypatch.setattr(sensors.os, "name", "other")
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert sensors.cpu_name() == "Ryzen 9 9900X"


def test_network_counters_skip_virtual_adapters(monkeypatch):
    from types import SimpleNamespace as NS

    monkeypatch.setattr(
        sensors.psutil,
        "net_if_stats",
        lambda: {"Ethernet": NS(isup=True), "vEthernet (WSL)": NS(isup=True), "Wi-Fi": NS(isup=False)},
    )
    monkeypatch.setattr(
        sensors.psutil,
        "net_io_counters",
        lambda pernic: {
            "Ethernet": NS(bytes_recv=100, bytes_sent=10),
            "vEthernet (WSL)": NS(bytes_recv=900, bytes_sent=90),
            "Wi-Fi": NS(bytes_recv=500, bytes_sent=50),
        },
    )
    assert sensors.network_counters("auto") == (100, 10)
    assert sensors.network_counters("Wi-Fi") == (500, 50)
