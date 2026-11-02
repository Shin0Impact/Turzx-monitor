"""Live system stats, sampled in a background thread. A source that isn't available reads as None."""

from __future__ import annotations

import logging
import os
import platform
import re
import threading
import time
from dataclasses import dataclass, field

import psutil

log = logging.getLogger(__name__)

HISTORY_LEN = 60  # seconds of history kept for graphs
VIRTUAL_NIC = re.compile(
    r"loopback|vethernet|virtualbox|vmware|hyper-v|bluetooth|wsl|tailscale|zerotier|teredo|isatap|pseudo|^lo$", re.I
)
GIB = 2**30


@dataclass(frozen=True)
class Gpu:
    name: str = ""
    load: float | None = None
    temp: float | None = None
    power: float | None = None
    fan: float | None = None
    clock: float | None = None
    mem_used: float | None = None  # GiB
    mem_total: float | None = None


@dataclass(frozen=True)
class Drive:
    name: str
    percent: float


@dataclass(frozen=True)
class Sample:
    cpu_name: str = ""
    cpu_load: float | None = None
    cpu_clock: float | None = None  # MHz
    cores: tuple[float, ...] = ()
    ram_used: float | None = None  # GiB
    ram_total: float | None = None
    ram_percent: float | None = None
    gpu: Gpu | None = None
    down: float | None = None  # bytes/s
    up: float | None = None
    disk_read: float | None = None
    disk_write: float | None = None
    drives: tuple[Drive, ...] = ()
    uptime: float | None = None  # seconds


@dataclass
class History:
    cpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    gpu: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    down: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)
    up: list[float] = field(default_factory=lambda: [0.0] * HISTORY_LEN)


def cpu_name() -> str:
    """Marketing name of the CPU, trimmed to fit on the screen (e.g. 'Ryzen 9 9900X')."""
    name = platform.processor()
    try:
        if os.name == "nt":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        else:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                name = next(line.split(":", 1)[1] for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    name = re.sub(r"\(R\)|\(TM\)|CPU|Processor|\d+-Core|with Radeon Graphics|@.*", "", name, flags=re.I)
    name = name.replace("AMD ", "").replace("Intel ", "").replace("Core ", "")
    return " ".join(name.split()) or "CPU"


class NvidiaGpu:
    """First NVIDIA GPU, through NVML (installed with the driver)."""

    def __init__(self) -> None:
        self._nvml = None
        self._handle = None
        self.name = ""
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            raw = pynvml.nvmlDeviceGetName(self._handle)
            self.name = raw.decode() if isinstance(raw, bytes) else raw
        except Exception as e:  # no NVIDIA GPU / driver: NVML raises its own error types
            log.info("no NVIDIA GPU readings (%s)", e)
            self._nvml = None

    @property
    def available(self) -> bool:
        return self._nvml is not None

    def read(self) -> Gpu | None:
        if self._nvml is None:
            return None
        nv, h = self._nvml, self._handle

        def get(fn):
            try:
                return fn()
            except nv.NVMLError:  # this sensor isn't supported on this card
                return None

        mem = get(lambda: nv.nvmlDeviceGetMemoryInfo(h))
        power = get(lambda: nv.nvmlDeviceGetPowerUsage(h))
        return Gpu(
            name=self.name,
            load=get(lambda: nv.nvmlDeviceGetUtilizationRates(h).gpu),
            temp=get(lambda: nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)),
            power=None if power is None else power / 1000,
            fan=get(lambda: nv.nvmlDeviceGetFanSpeed(h)),
            clock=get(lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS)),
            mem_used=None if mem is None else mem.used / GIB,
            mem_total=None if mem is None else mem.total / GIB,
        )


class RateMeter:
    """Turns ever-growing byte counters into bytes/second."""

    def __init__(self) -> None:
        self._last: tuple[float, tuple[int, ...]] | None = None

    def update(self, *counters: int) -> tuple[float, ...] | None:
        now = time.monotonic()
        previous, self._last = self._last, (now, counters)
        if previous is None:
            return None
        elapsed = max(now - previous[0], 1e-3)
        return tuple(max(0, new - old) / elapsed for new, old in zip(counters, previous[1], strict=True))


def network_counters(interface: str) -> tuple[int, int]:
    """(bytes received, bytes sent) over the chosen adapter, or over all real, connected ones."""
    stats = psutil.net_if_stats()
    received = sent = 0
    for nic, counters in psutil.net_io_counters(pernic=True).items():
        if interface != "auto":
            if nic != interface:
                continue
        elif VIRTUAL_NIC.search(nic) or not (stats.get(nic) and stats[nic].isup):
            continue
        received += counters.bytes_recv
        sent += counters.bytes_sent
    return received, sent


def drive_usage(drives: str | list[str]) -> tuple[Drive, ...]:
    if drives == "auto":
        mounts: list[str] = []
        for part in psutil.disk_partitions(all=False):
            if os.name == "nt" and ("cdrom" in part.opts or not part.fstype):
                continue
            if os.name != "nt" and not part.device.startswith("/dev/"):
                continue
            if part.mountpoint not in mounts:
                mounts.append(part.mountpoint)
        drives = mounts[:3]
    found = []
    for mount in drives:
        try:
            found.append(Drive(mount.rstrip("\\/") or "/", psutil.disk_usage(mount).percent))
        except OSError:
            continue
    return tuple(found)


class Stats(threading.Thread):
    """Samples every `interval` seconds. snapshot() is safe to call from any thread."""

    def __init__(
        self, interval: float = 1.0, drives: str | list[str] = "auto", network_interface: str = "auto"
    ) -> None:
        super().__init__(daemon=True, name="stats")
        self.interval = interval
        self._drives = drives
        self._nic = network_interface
        self._lock = threading.Lock()
        self._paused = threading.Event()
        self._net = RateMeter()
        self._disk = RateMeter()
        self._history = History()
        self.gpu = NvidiaGpu()
        self.cpu_name = cpu_name()
        psutil.cpu_percent(percpu=True)  # first call only primes the counters
        self._sample = self._read()

    def pause(self, paused: bool = True) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def _read(self) -> Sample:
        cores = tuple(psutil.cpu_percent(percpu=True))
        freq = psutil.cpu_freq()
        ram = psutil.virtual_memory()
        net = self._net.update(*network_counters(self._nic))
        io = psutil.disk_io_counters()
        disk = self._disk.update(io.read_bytes, io.write_bytes) if io else None
        return Sample(
            cpu_name=self.cpu_name,
            cpu_load=sum(cores) / len(cores) if cores else 0.0,
            cpu_clock=freq.current if freq else None,
            cores=cores,
            ram_used=ram.used / GIB,
            ram_total=ram.total / GIB,
            ram_percent=ram.percent,
            gpu=self.gpu.read(),
            down=net[0] if net else None,
            up=net[1] if net else None,
            disk_read=disk[0] if disk else None,
            disk_write=disk[1] if disk else None,
            drives=drive_usage(self._drives),
            uptime=time.time() - psutil.boot_time(),
        )

    def sample(self) -> None:
        new = self._read()
        with self._lock:
            self._sample = new
            h = self._history
            for series, value in (
                (h.cpu, new.cpu_load),
                (h.gpu, new.gpu.load if new.gpu else 0),
                (h.down, new.down),
                (h.up, new.up),
            ):
                series.append(value or 0.0)
                del series[0]

    def snapshot(self) -> tuple[Sample, History]:
        with self._lock:
            h = self._history
            return self._sample, History(list(h.cpu), list(h.gpu), list(h.down), list(h.up))

    def run(self) -> None:
        while True:
            started = time.monotonic()
            if not self._paused.is_set():
                try:
                    self.sample()
                except Exception:  # a flaky sensor must never kill the thread
                    log.exception("sampling failed")
            time.sleep(max(0.05, self.interval - (time.monotonic() - started)))
