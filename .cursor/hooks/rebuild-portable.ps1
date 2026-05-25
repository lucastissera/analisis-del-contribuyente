# Rebuild portable tras cambios (hook stop). Ignora fallos si el exe está en uso.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $root "tools\portable_build.py"))) {
    $root = Split-Path $PSScriptRoot -Parent
}
Set-Location $root
$log = Join-Path $root "build\hook-rebuild.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$ts] Hook rebuild-portable" | Out-File -FilePath $log -Encoding utf8
python tools\portable_build.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
