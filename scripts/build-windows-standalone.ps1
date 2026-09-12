[CmdletBinding()]
param([string]$Python = "python", [string]$Uv = "uv", [string]$OutputDirectory = "")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo "build\standalone-venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$dist = Join-Path $repo "dist"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $Uv venv --python $Python $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the standalone build environment." }
}
& $Uv pip install --python $venvPython (Join-Path $repo "cli") "pyinstaller==6.15.0"
if ($LASTEXITCODE -ne 0) { throw "Could not install the standalone build dependencies." }
& $venvPython -m PyInstaller --noconfirm --clean --distpath $dist `
    --workpath (Join-Path $repo "build\pyinstaller") (Join-Path $PSScriptRoot "strata-windows.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
$built = Join-Path $dist "strata"
$exe = Join-Path $built "strata.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Standalone STRATA build did not produce strata.exe." }
$bridgeOutput = '{"id":1,"method":"capabilities","params":{}}' | & $exe bridge
$bridgeExitCode = $LASTEXITCODE
$response = $bridgeOutput | Select-Object -First 1
try {
    $capabilities = $response | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "Standalone STRATA bridge returned invalid JSON (exit $bridgeExitCode): $response"
}
if ($bridgeExitCode -ne 0 -or -not $capabilities.ok -or $capabilities.id -ne 1 -or
    $capabilities.result.transport -ne "stdio-jsonl" -or
    $capabilities.result.methods -notcontains "capabilities") {
    throw "Standalone STRATA bridge smoke test failed (exit $bridgeExitCode): $response"
}
if ($OutputDirectory) {
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    Copy-Item -Path (Join-Path $built "*") -Destination $OutputDirectory -Recurse -Force
    $built = (Resolve-Path -LiteralPath $OutputDirectory).Path
}
Write-Output $built
