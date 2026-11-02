"""Detect the Turing Smart Screen and report PC details. Run on Windows:
    pip install pyserial
    python detect_screen.py
Writes detect_report.txt next to this file - paste its contents back to Claude."""
import platform, subprocess, sys, os, shutil

out = []
def log(s=""):
    print(s); out.append(s)

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=isinstance(cmd, str)).stdout.strip()
    except Exception as e:
        return f"(failed: {e})"

log(f"Python {sys.version.split()[0]} on {platform.platform()}")
log(f"CPU: {platform.processor()}")
log()

# Known serial IDs used by the turing-smart-screen-python project to tell models apart
KNOWN = {
    "USB35INCHIPS": "Turing 3.5\" (Revision A)",
    "USB35INCHIPSV2": "Turing 3.5\" (Revision A, V2)",
    "2017-2-25": "XuanFang 3.5\" (Revision B)",
    "CT21INCH": "Turing 2.1\" (Revision C)",
    "USB7INCH": "Turing 5\"/8.8\" (Revision C)",
}

log("== Serial (COM) devices ==")
try:
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        log("No COM ports found. Is the screen plugged into the DATA USB-C port (not power-only)?")
    for p in ports:
        log(f"{p.device}: {p.description}")
        log(f"   hwid={p.hwid}  vid={p.vid}  pid={p.pid}  serial={p.serial_number}  mfr={p.manufacturer}")
        for k, v in KNOWN.items():
            if k in (p.serial_number or "") or k in (p.hwid or "") or k in (p.description or ""):
                log(f"   >>> MATCH: {v}")
except ImportError:
    log("pyserial missing: run  pip install pyserial  and try again")

log()
log("== USB devices (Windows) ==")
if os.name == "nt":
    log(run(["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*' -or $_.Class -eq 'Ports' } "
             "| Select-Object Class,FriendlyName,InstanceId | Format-Table -AutoSize -Wrap | Out-String -Width 250"]))
else:
    log("(not Windows - skipped)")

log()
log("== GPU ==")
if os.name == "nt":
    log(run(["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | Format-List | Out-String"]))
log("nvidia-smi: " + (run(["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total", "--format=csv,noheader"]) if shutil.which("nvidia-smi") else "not found"))

log()
log("== Python modules ==")
for m in ("serial", "PIL", "psutil", "yaml", "GPUtil", "pynvml", "wmi", "LibreHardwareMonitor"):
    try:
        __import__(m); log(f"{m}: ok")
    except Exception:
        log(f"{m}: missing")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect_report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
log("\nSaved detect_report.txt")
