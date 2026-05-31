# Programa rebuild portable con debounce tras edición de archivos (hook afterFileEdit).
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $root "tools\hook_schedule_build.py"))) {
    $root = Split-Path $PSScriptRoot -Parent
}
Set-Location $root
$stdin = [Console]::In.ReadToEnd()
if ($stdin) {
    $stdin | python tools\hook_schedule_build.py
} else {
    python tools\hook_schedule_build.py
}
