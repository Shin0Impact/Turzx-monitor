# Sets up LibreHardwareMonitor so the Turing screen app can show CPU temperature.
# Windows doesn't let normal apps read CPU temperature; LibreHardwareMonitor (free, open source)
# reads it with admin rights and shares it on http://localhost:8085/data.json, which the app reads.
#
# What this does: installs it (winget) if needed, turns on its web server + tray mode in its
# settings file, starts it, and checks that a CPU temperature comes through.
param([switch]$NoLaunch, [int]$WaitSeconds = 90)

$ErrorActionPreference = 'Stop'
$Url = 'http://localhost:8085/data.json'

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }

function Get-CpuTemp {
    try { $data = Invoke-RestMethod -Uri $Url -TimeoutSec 2 } catch { return $null }
    $script:found = $null
    function Walk($n) {
        if ($null -ne $n.SensorId -and $n.SensorId -match '/(amd|intel)cpu/' -and $n.Type -eq 'Temperature') {
            if ($null -eq $script:found -or $n.Text -match 'Tctl/Tdie|Package') { $script:found = $n }
        }
        foreach ($c in @($n.Children)) { if ($null -ne $c) { Walk $c } }
    }
    Walk $data
    if ($null -eq $script:found) { return 'none' }
    if ($null -ne $script:found.RawValue) { return ('{0:N0} C ({1})' -f [double]$script:found.RawValue, $script:found.Text) }
    return ('{0} ({1})' -f $script:found.Value, $script:found.Text)
}

function Find-Lhm {
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'),
        $env:ProgramFiles, ${env:ProgramFiles(x86)},
        (Join-Path $env:LOCALAPPDATA 'Programs'),
        (Join-Path $env:USERPROFILE 'Downloads'), (Join-Path $env:USERPROFILE 'Desktop'),
        (Join-Path $env:USERPROFILE 'Documents')
    )
    foreach ($r in $roots) {
        if ($r -and (Test-Path $r)) {
            $f = Get-ChildItem -Path $r -Filter 'LibreHardwareMonitor.exe' -Recurse -Depth 4 -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($f) { return $f.FullName }
        }
    }
    return $null
}

function Set-LhmSettings([string]$exe) {
    # LibreHardwareMonitor keeps its settings in LibreHardwareMonitor.config next to the exe
    $cfg = [System.IO.Path]::ChangeExtension($exe, '.config')
    $x = New-Object System.Xml.XmlDocument
    if (Test-Path $cfg) {
        $x.Load($cfg)
    } else {
        $x.LoadXml('<?xml version="1.0" encoding="utf-8"?><configuration><appSettings /></configuration>')
    }
    $app = $x.SelectSingleNode('/configuration/appSettings')
    if ($null -eq $app) {
        $root = $x.SelectSingleNode('/configuration')
        $app = $x.CreateElement('appSettings')
        [void]$root.AppendChild($app)
    }
    $wanted = [ordered]@{
        'runWebServerMenuItem' = 'true'    # Options > Remote Web Server > Run
        'startMinMenuItem'     = 'true'    # Options > Start Minimized
        'minTrayMenuItem'      = 'true'    # Options > Minimize To Tray
        'minCloseMenuItem'     = 'true'    # Options > Minimize On Close (closing keeps it running)
    }
    foreach ($k in $wanted.Keys) {
        $node = $app.SelectSingleNode("add[@key='$k']")
        if ($null -eq $node) {
            $node = $x.CreateElement('add')
            $node.SetAttribute('key', $k)
            [void]$app.AppendChild($node)
        }
        $node.SetAttribute('value', $wanted[$k])
    }
    $x.Save($cfg)
    return $cfg
}

Say ''
Say '=== CPU temperature setup for the Turing screen ===' 'Cyan'
Say ''

$t = Get-CpuTemp
if ($t -and $t -ne 'none') {
    Say "Already working: CPU temperature is $t" 'Green'
    Say 'The screen app picks it up within 10 seconds.'
    exit 0
}

$exe = Find-Lhm
if (-not $exe) {
    Say 'LibreHardwareMonitor is not installed. Installing it with winget...' 'Yellow'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Say 'winget is not available. Download LibreHardwareMonitor from' 'Red'
        Say '  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases'
        Say 'unzip it (for example into Documents), then run this again.'
        exit 1
    }
    & winget install --id LibreHardwareMonitor.LibreHardwareMonitor -e --accept-package-agreements --accept-source-agreements
    $exe = Find-Lhm
    if (-not $exe) {
        Say 'Install finished but LibreHardwareMonitor.exe was not found. Run this again, or download it manually:' 'Red'
        Say '  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases'
        exit 1
    }
}
Say "Found: $exe" 'Green'

# it rewrites its settings file when it exits, so it must be closed while we change them
while (Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue) {
    Say ''
    Say 'LibreHardwareMonitor is running. Please close it completely:' 'Yellow'
    Say '  right-click its tray icon (bottom-right, near the clock) > Exit'
    Read-Host 'Press Enter when it is closed'
}

$cfg = Set-LhmSettings $exe
Say "Turned on its web server and tray mode ($cfg)" 'Green'

if ($NoLaunch) { exit 0 }

Say ''
Say 'Starting LibreHardwareMonitor. Windows will ask for admin permission - click Yes.' 'Cyan'
Say 'If it asks to install PawnIO (its sensor driver), click OK.' 'Cyan'
Start-Process -FilePath $exe

Say ''
Say "Waiting for the CPU temperature (up to $WaitSeconds seconds)..."
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$t = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $t = Get-CpuTemp
    if ($t -and $t -ne 'none') { break }
}

Say ''
if ($t -and $t -ne 'none') {
    Say "Working! CPU temperature: $t" 'Green'
    Say 'The screen app picks it up within 10 seconds.'
    Say ''
    Say 'Last step, so it starts with Windows: open LibreHardwareMonitor from the tray,' 'Yellow'
    Say 'then Options > Run On Windows Startup.' 'Yellow'
} elseif ($t -eq 'none') {
    Say 'The web server works but no CPU temperature yet. Usually PawnIO was not installed:' 'Yellow'
    Say 'close LibreHardwareMonitor (tray > Exit), run this again and click OK when it offers PawnIO.'
} else {
    Say 'No answer from LibreHardwareMonitor yet.' 'Yellow'
    Say 'Check it is running (tray icon) and that Options > Remote Web Server > Run is ticked.'
    Say 'If you said No to the admin prompt, run this again and click Yes.'
}
