# Firma Authenticode del .exe portable (P2.13).
#
# Requisitos:
#   - Windows SDK (signtool.exe) o Visual Studio Build Tools
#   - Certificado de code signing (.pfx) OV/EV de una CA (DigiCert, Sectigo, etc.)
#
# Variables:
#   AIC_SIGN_PFX
#   AIC_SIGN_PFX_PASSWORD
#   AIC_SIGN_TIMESTAMP_URL  (default DigiCert)
#   AIC_SIGN_EXE
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File tools\firmar_portable.ps1

param(
    [string]$PfxPath = $env:AIC_SIGN_PFX,
    [string]$PfxPassword = $env:AIC_SIGN_PFX_PASSWORD,
    [string]$TimestampUrl = $(if ($env:AIC_SIGN_TIMESTAMP_URL) { $env:AIC_SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }),
    [string]$ExePath = $env:AIC_SIGN_EXE
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $ExePath) {
    $ExePath = Join-Path $Root "dist\AnalisisIntegralContribuyente\AnalisisIntegralContribuyente.exe"
}

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    )
    foreach ($r in $roots) {
        if (-not (Test-Path $r)) { continue }
        $hit = Get-ChildItem -Path $r -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

if (-not (Test-Path $ExePath)) {
    Write-Error "No existe el exe: $ExePath (compila antes con build_windows.bat)"
}

if (-not $PfxPath -or -not (Test-Path $PfxPath)) {
    Write-Host "SKIP: no hay certificado .pfx (AIC_SIGN_PFX)."
    Write-Host "Sin firma Authenticode, Windows mostrara SmartScreen en PCs ajenas."
    Write-Host "Ver docs/FIRMA_AUTHENTICODE.md"
    exit 0
}

$signtool = Find-SignTool
if (-not $signtool) {
    Write-Error "No se encontro signtool.exe. Instala Windows SDK / Build Tools."
}

Write-Host "Firmando con: $signtool"
Write-Host "Objetivo:     $ExePath"
Write-Host "Certificado:  $PfxPath"

$signArgs = @(
    "sign",
    "/fd", "SHA256",
    "/td", "SHA256",
    "/tr", $TimestampUrl,
    "/f", $PfxPath,
    "/p", $PfxPassword,
    $ExePath
)
& $signtool @signArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "signtool fallo con codigo $LASTEXITCODE"
}

$sig = Get-AuthenticodeSignature -FilePath $ExePath
$subject = ""
if ($sig.SignerCertificate) { $subject = $sig.SignerCertificate.Subject }
Write-Host ("Estado firma: {0} - {1}" -f $sig.Status, $subject)
if ($sig.Status -ne "Valid") {
    Write-Error ("La firma no quedo Valid (Status={0})" -f $sig.Status)
}
Write-Host "OK Authenticode"
exit 0
