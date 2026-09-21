param([string]$Executable = 'src-tauri/target/release/scholarmate.exe')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$testDirectory = Join-Path $root ('.tools/desktop-smoke-' + [guid]::NewGuid().ToString('N'))
$previousDirectory = $env:SCHOLARMATE_DATA_DIR
$previousToken = $env:SCHOLARMATE_TOKEN
$env:SCHOLARMATE_DATA_DIR = $testDirectory
$env:SCHOLARMATE_TOKEN = 'desktop-smoke-fixture-token'
$application = $null
try {
    $application = Start-Process -FilePath (Join-Path $root $Executable) -PassThru -WindowStyle Hidden
    $port = $null
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        $application.Refresh()
        if ($application.HasExited) { throw 'Desktop exited during startup.' }
        $allProcesses = Get-CimInstance Win32_Process
        $children = @($allProcesses | Where-Object { $_.ParentProcessId -eq $application.Id })
        $childIds = @($children.ProcessId)
        $grandchildren = @($allProcesses | Where-Object { $_.ParentProcessId -in $childIds })
        $ownedIds = @($childIds) + @($grandchildren.ProcessId)
        $listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -in $ownedIds -and $_.LocalAddress -eq '127.0.0.1' } | Select-Object -First 1
        if ($listener) { $port = $listener.LocalPort; break }
    }
    if (-not $port) { throw 'Desktop did not start the loopback backend.' }
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/plans" -Headers @{ Authorization = 'Bearer desktop-smoke-fixture-token' } -TimeoutSec 10
    if (@($response).Count -ne 0) { throw 'Expected an empty isolated database.' }
    Stop-Process -Id $application.Id
    $application.WaitForExit()
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $remaining = @(Get-Process -Id $ownedIds -ErrorAction SilentlyContinue)
        if ($remaining.Count -eq 0) { break }
    }
    if ($remaining.Count -ne 0) { throw 'Backend did not exit after parent termination.' }
    Write-Output 'PASS: release desktop launches packaged Python, authenticated API works, backend exits with parent.'
} finally {
    if ($application -and -not $application.HasExited) { Stop-Process -Id $application.Id -ErrorAction SilentlyContinue }
    $env:SCHOLARMATE_DATA_DIR = $previousDirectory
    $env:SCHOLARMATE_TOKEN = $previousToken
}

