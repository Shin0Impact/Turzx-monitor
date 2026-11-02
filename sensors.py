"""Collects live system stats in a background thread. Every source is optional: anything that
isn't available just shows as None and the screen prints "--"."""
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from collections import deque

import psutil

HISTORY = 60  # samples kept for graphs

VIRTUAL_NIC = re.compile(r"loopback|vethernet|virtualbox|vmware|hyper-v|bluetooth|wsl|tailscale|zerotier|teredo|isatap|pseudo|^lo$", re.I)


def cpu_name():
    try:
        if os.name == "nt":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"


def short_cpu_name(name):
    name = re.sub(r"\(R\)|\(TM\)|CPU|Processor|\d+-Core|with Radeon Graphics|@.*", "", name, flags=re.I)
    name = name.replace("AMD ", "").replace("Intel ", "").replace("Core ", "")
    return " ".join(name.split())


class Gpu:
    """NVIDIA via NVML (nvidia-ml-py), falling back to nvidia-smi."""

    def __init__(self):
        self.mode = None
        self.name = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nv = pynvml
            self.h = pynvml.nvmlDeviceGetHandleByIndex(0)
            n = pynvml.nvmlDeviceGetName(self.h)
            self.name = n.decode() if isinstance(n, bytes) else n
            self.mode = "nvml"
        except Exception:
            if shutil.which("nvidia-smi"):
                self.mode = "smi"

    def read(self):
        if self.mode == "nvml":
            nv, h = self.nv, self.h
            out = {}
            for key, fn in (
                ("load", lambda: nv.nvmlDeviceGetUtilizationRates(h).gpu),
                ("temp", lambda: nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)),
                ("power", lambda: nv.nvmlDeviceGetPowerUsage(h) / 1000),
                ("fan", lambda: nv.nvmlDeviceGetFanSpeed(h)),
                ("clock", lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS)),
            ):
                try:
                    out[key] = fn()
                except Exception:
                    out[key] = None
            try:
                m = nv.nvmlDeviceGetMemoryInfo(h)
                out["mem_used"], out["mem_total"] = m.used / 2**30, m.total / 2**30
            except Exception:
                out["mem_used"] = out["mem_total"] = None
            return out
        if self.mode == "smi":
            try:
                flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console flash
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,fan.speed,clocks.gr,memory.used,memory.total",
                     "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, creationflags=flags)
                p = [s.strip() for s in r.stdout.strip().splitlines()[0].split(",")]
                self.name = p[0]
                f = lambda s: float(s) if re.match(r"^[\d.]+$", s) else None
                return {"load": f(p[1]), "temp": f(p[2]), "power": f(p[3]), "fan": f(p[4]), "clock": f(p[5]),
                        "mem_used": f(p[6]) / 1024 if f(p[6]) else None, "mem_total": f(p[7]) / 1024 if f(p[7]) else None}
            except Exception:
                return None
        return None


class LibreHardwareMonitor:
    """Reads CPU temperature/power/clock from LibreHardwareMonitor's built-in web server
    (Options > Remote Web Server > Run, default port 8085). Optional."""

    def __init__(self, url):
        self.url = url
        self.next_try = 0
        self.ok = False

    @staticmethod
    def _num(s):
        m = re.match(r"\s*(-?[\d.,]+)", str(s or ""))
        return float(m.group(1).replace(",", ".")) if m else None

    def read(self):
        if not self.url or time.time() < self.next_try:
            return None
        try:
            with urllib.request.urlopen(self.url, timeout=0.6) as r:
                tree = json.load(r)
        except Exception:
            self.ok = False
            self.next_try = time.time() + 30
            return None
        self.ok = True
        temps, powers, clocks = {}, {}, []

        def walk(node, path):
            text = node.get("Text", "")
            sid = node.get("SensorId", "")
            p = path + [text]
            in_cpu = "/amdcpu/" in sid or "/intelcpu/" in sid or any(
                re.search(r"ryzen|intel|core i|xeon|epyc|threadripper", x, re.I) for x in path[1:3])
            if "Value" in node and in_cpu and node.get("Children") == []:
                kind = node.get("Type") or (p[-2] if len(p) > 1 else "")
                v = self._num(node.get("Value"))
                if v is not None:
                    if "emperature" in kind:
                        temps[text] = v
                    elif "ower" in kind:
                        powers[text] = v
                    elif "lock" in kind and re.match(r"core", text, re.I):
                        clocks.append(v)
            for c in node.get("Children", []):
                walk(c, p)

        walk(tree, [])
        temp = None
        for k in ("Core (Tctl/Tdie)", "Tctl/Tdie", "CPU Package", "Package", "Core (Tdie)", "Tdie", "Tctl", "Core Average"):
            if k in temps:
                temp = temps[k]
                break
        if temp is None and temps:
            temp = max(temps.values())
        power = None
        for k in ("Package", "CPU Package"):
            if k in powers:
                power = powers[k]
                break
        return {"temp": temp, "power": power, "clock": (sum(clocks) / len(clocks)) if clocks else None}


class Stats(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True, name="stats")
        self.cfg = cfg
        self.interval = cfg.get("interval", 1.0)
        self.lock = threading.Lock()
        self.data = {}
        self.cpu_hist = deque([0] * HISTORY, maxlen=HISTORY)
        self.gpu_hist = deque([0] * HISTORY, maxlen=HISTORY)
        self.down_hist = deque([0] * HISTORY, maxlen=HISTORY)
        self.up_hist = deque([0] * HISTORY, maxlen=HISTORY)
        self.cpu_name = short_cpu_name(cpu_name())
        self.gpu = Gpu()
        self.lhm = LibreHardwareMonitor(cfg.get("librehardwaremonitor_url", "http://localhost:8085/data.json"))
        self.nic_filter = cfg.get("network_interface", "auto")
        self.drives = cfg.get("drives", "auto")
        self._last_net = None
        self._last_disk = None
        self._paused = threading.Event()
        psutil.cpu_percent(percpu=True)  # prime the counters
        self.sample()

    def pause(self, yes=True):
        if yes:
            self._paused.set()
        else:
            self._paused.clear()

    def _net(self):
        counters = psutil.net_io_counters(pernic=True)
        stats = psutil.net_if_stats()
        sent = recv = 0
        for nic, c in counters.items():
            if self.nic_filter != "auto":
                if nic != self.nic_filter:
                    continue
            elif VIRTUAL_NIC.search(nic) or not (stats.get(nic) and stats[nic].isup):
                continue
            sent += c.bytes_sent
            recv += c.bytes_recv
        now = time.time()
        rate = (0.0, 0.0)
        if self._last_net:
            t, s0, r0 = self._last_net
            dt = max(now - t, 1e-3)
            rate = (max(0, recv - r0) / dt, max(0, sent - s0) / dt)
        self._last_net = (now, sent, recv)
        return rate

    def _disk_io(self):
        try:
            c = psutil.disk_io_counters()
        except Exception:
            return None, None
        if c is None:
            return None, None
        now = time.time()
        rate = (None, None)
        if self._last_disk:
            t, r0, w0 = self._last_disk
            dt = max(now - t, 1e-3)
            rate = (max(0, c.read_bytes - r0) / dt, max(0, c.write_bytes - w0) / dt)
        self._last_disk = (now, c.read_bytes, c.write_bytes)
        return rate

    def _drives(self):
        if self.drives != "auto":
            mounts = self.drives
        else:
            mounts = []
            for p in psutil.disk_partitions(all=False):
                if os.name == "nt" and ("cdrom" in p.opts or p.fstype == ""):
                    continue
                if os.name != "nt" and not p.device.startswith("/dev/"):
                    continue
                if p.mountpoint not in mounts:
                    mounts.append(p.mountpoint)
            mounts = mounts[:3]
        out = []
        for m in mounts:
            try:
                u = psutil.disk_usage(m)
                label = m.rstrip("\\/") or "/"
                out.append({"name": label, "used": u.used / 2**30, "total": u.total / 2**30, "pct": u.percent})
            except Exception:
                pass
        return out

    def sample(self):
        d = {}
        per = psutil.cpu_percent(percpu=True)
        d["cores"] = per
        d["cpu_load"] = sum(per) / len(per) if per else 0
        try:
            f = psutil.cpu_freq()
            d["cpu_clock"] = f.current if f else None
        except Exception:
            d["cpu_clock"] = None
        d["cpu_temp"] = d["cpu_power"] = None
        lhm = self.lhm.read()
        if lhm:
            d["cpu_temp"], d["cpu_power"] = lhm["temp"], lhm["power"]
            if lhm["clock"]:
                d["cpu_clock"] = lhm["clock"]
        elif hasattr(psutil, "sensors_temperatures"):  # Linux / testing
            try:
                t = psutil.sensors_temperatures()
                for k in ("k10temp", "coretemp", "zenpower"):
                    if t.get(k):
                        d["cpu_temp"] = t[k][0].current
                        break
            except Exception:
                pass
        vm = psutil.virtual_memory()
        d["ram_used"], d["ram_total"], d["ram_pct"] = vm.used / 2**30, vm.total / 2**30, vm.percent
        d["gpu"] = self.gpu.read()
        d["gpu_name"] = self.gpu.name
        d["down"], d["up"] = self._net()
        d["disk_read"], d["disk_write"] = self._disk_io()
        d["drives"] = self._drives()
        d["uptime"] = time.time() - psutil.boot_time()
        d["cpu_name"] = self.cpu_name
        d["lhm_ok"] = self.lhm.ok
        with self.lock:
            self.data = d
            self.cpu_hist.append(d["cpu_load"])
            self.gpu_hist.append((d["gpu"] or {}).get("load") or 0)
            self.down_hist.append(d["down"])
            self.up_hist.append(d["up"])

    def snapshot(self):
        with self.lock:
            return dict(self.data), {
                "cpu": list(self.cpu_hist), "gpu": list(self.gpu_hist),
                "down": list(self.down_hist), "up": list(self.up_hist)}

    def run(self):
        while True:
            t0 = time.time()
            if not self._paused.is_set():
                try:
                    self.sample()
                except Exception as e:  # never let a sensor kill the thread
                    print("stats error:", e)
            time.sleep(max(0.05, self.interval - (time.time() - t0)))
