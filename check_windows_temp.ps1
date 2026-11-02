# Looks at every temperature source Windows has built in (no installs, no admin needed).
# Writes windows_temp_report.txt next to this file.
$out = New-Object System.Collections.Generic.List[string]
function Log([string]$m) { Write-Host $m; $out.Add($m) }
function KtoC($v) { return [math]::Round(([double]$v / 10.0) - 273.15, 1) }

Log "=== Windows built-in temperature sources ==="
Log ("Time: " + (Get-Date))
Log ("CPU: " + (Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name))
Log ""

Log "--- 1. WMI MSAcpi_ThermalZoneTemperature (root/wmi) ---"
try {
    $z = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop)
    if ($z.Count -eq 0) { Log "no thermal zones returned" }
    foreach ($x in $z) { Log ("  {0}: {1} C" -f $x.InstanceName, (KtoC $x.CurrentTemperature)) }
} catch { Log ("  not available: " + $_.Exception.Message) }
Log ""

Log "--- 2. Performance counter 'Thermal Zone Information' ---"
try {
    $c = (Get-Counter -Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop).CounterSamples
    if (@($c).Count -eq 0) { Log "no instances" }
    foreach ($s in $c) { Log ("  {0}: {1} K = {2} C" -f $s.InstanceName, $s.CookedValue, [math]::Round($s.CookedValue - 273.15, 1)) }
} catch { Log ("  not available: " + $_.Exception.Message) }
Log ""

Log "--- 3. WMI Win32_PerfFormattedData_Counters_ThermalZoneInformation ---"
try {
    $t = @(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction Stop)
    if ($t.Count -eq 0) { Log "no instances" }
    foreach ($x in $t) { Log ("  {0}: {1} K = {2} C  (HighPrecision {3})" -f $x.Name, $x.Temperature, ($x.Temperature - 273), $x.HighPrecisionTemperature) }
} catch { Log ("  not available: " + $_.Exception.Message) }
Log ""

Log "--- 4. Win32_TemperatureProbe / Win32_Fan (usually empty) ---"
try { $p = @(Get-CimInstance Win32_TemperatureProbe -ErrorAction Stop); Log ("  probes: " + $p.Count) } catch { Log "  not available" }
Log ""

Log "--- 5. Does the number follow CPU load? (reading source 2 while the CPU is busy for ~8 s) ---"
function ReadZone { try { (Get-Counter -Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop).CounterSamples | ForEach-Object { [math]::Round($_.CookedValue - 273.15, 1) } } catch { @() } }
$before = (ReadZone) -join ', '
$jobs = 1..[Environment]::ProcessorCount | ForEach-Object { Start-Job { $e = (Get-Date).AddSeconds(8); while ((Get-Date) -lt $e) { [math]::Sqrt(12345.6789) | Out-Null } } }
Start-Sleep -Seconds 7
$during = (ReadZone) -join ', '
$jobs | Wait-Job | Remove-Job
Log ("  idle: " + $before + " C")
Log ("  busy: " + $during + " C")
Log "  (a real CPU sensor climbs by several degrees; a motherboard sensor barely moves)"

$path = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'windows_temp_report.txt'
[System.IO.File]::WriteAllLines($path, $out)
Write-Host ""
Write-Host "Saved: $path"
