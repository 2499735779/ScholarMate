# Scoped compatibility for RTK on Windows hosts without HOME in the child environment.
$previousClaudeConfig = $env:CLAUDE_CONFIG_DIR
try {
    if (-not $env:CLAUDE_CONFIG_DIR) {
        $env:CLAUDE_CONFIG_DIR = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.claude'
    }
    $rtkExecutable = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local/bin/rtk.exe'
    & $rtkExecutable @args
    exit $LASTEXITCODE
} finally {
    $env:CLAUDE_CONFIG_DIR = $previousClaudeConfig
}

