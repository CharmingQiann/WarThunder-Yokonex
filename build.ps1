$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$ArtifactsRoot = Join-Path $Root "artifacts"
$PackageDir = Join-Path $ArtifactsRoot "WarThunder-Yokonex-Plugin-v1.1.1"
$ZipPath = Join-Path $ArtifactsRoot "WarThunder-Yokonex-Plugin-v1.1.1.zip"
$ExeName = "WarThunder-Yokonex-Plugin.exe"

function Assert-WorkspaceChild([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $workspace = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $full.StartsWith($workspace, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside workspace: $full"
    }
    return $full
}

if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv --python 3.12 $Venv
    }
    else {
        python -m venv $Venv
    }
}

$Python = Join-Path $Venv "Scripts\python.exe"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv pip install --python $Python -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
}
else {
    & $Python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "pip initialization failed" }
    & $Python -m pip install -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
}
& $Python -m unittest discover -s (Join-Path $Root "tests") -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
& $Python -m PyInstaller --noconfirm --clean --onefile --noconsole --name WarThunder-Yokonex-Plugin `
    --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") `
    --specpath (Join-Path $Root "build") (Join-Path $Root "main.py")
if ($LASTEXITCODE -ne 0) { throw "EXE build failed" }

$PackageDir = Assert-WorkspaceChild $PackageDir
$ArtifactsRoot = Assert-WorkspaceChild $ArtifactsRoot
New-Item -ItemType Directory -Force -Path $ArtifactsRoot | Out-Null
if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "dist\$ExeName") -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $Root "manifest.json") -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $Root "config.json") -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $Root "USAGE.md") -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination $PackageDir

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "Package: $ZipPath"
