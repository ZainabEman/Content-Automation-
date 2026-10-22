<#
  Builds dist\content-automation-<date>.zip of this project for a new laptop.
  Unzip it into any folder (spaces are fine; the zip has no top folder). Sharing via GitHub
  (git clone, HOW-TO-INSTALL.txt) replaces this zip; it stays for offline handovers.

  Left out: .venv, caches, .git, dist, outputs\jobs (and .env + .secrets\ unless -IncludeSecrets).
  Kept: everything else, e.g. calendar\, outputs\content\, assets\, vendor\, state\.

  -IncludeSecrets   also add .env and .secrets\ (send that zip by USB or password manager only).
#>
param([switch]$IncludeSecrets)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$SkipDirNames = @('.venv', '__pycache__', '.mypy_cache', '.ruff_cache', '.git', '.uv-cache', '.pytest_cache', '.pytest-tmp')
$SkipPaths = @('dist', 'outputs\jobs')
$SkipFiles = @()
if (-not $IncludeSecrets) {
    $SkipPaths += '.secrets'
    $SkipFiles += '.env'
}

function Get-ProjectFiles([string]$Dir, [string]$Relative) {
    foreach ($item in Get-ChildItem -LiteralPath $Dir -Force) {
        $path = $item.Name
        if ($Relative) { $path = "$Relative\$($item.Name)" }
        if ($item.PSIsContainer) {
            if ($SkipDirNames -contains $item.Name -or $SkipPaths -contains $path) { continue }
            Get-ProjectFiles $item.FullName $path
        } elseif ($SkipFiles -notcontains $path) {
            [pscustomobject]@{ Full = $item.FullName; Relative = $path }
        }
    }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$dist = Join-Path $Root 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$zipPath = Join-Path $dist ("content-automation-{0}.zip" -f (Get-Date -Format 'yyyy-MM-dd'))
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

$files = @(Get-ProjectFiles $Root '')
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $files) {
        $entry = $file.Relative.Replace('\', '/')
        $null = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file.Full, $entry, [System.IO.Compression.CompressionLevel]::Optimal)
    }
} finally {
    $zip.Dispose()
}

foreach ($folder in 'calendar', 'outputs\content', 'assets', 'vendor') {
    $count = @($files | Where-Object { $_.Relative -like "$folder\*" }).Count
    if ($count) { Write-Host "Included: $folder\ ($count files)" } else { Write-Host "Not found: $folder\ (nothing to include)" }
}
$megabytes = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
Write-Host "Zip: $zipPath ($($files.Count) files, $megabytes MB)"
if ($IncludeSecrets) {
    Write-Host 'This zip contains .env and .secrets\ (passwords and keys).' -ForegroundColor Yellow
    Write-Host 'Send this zip by USB or password manager only.' -ForegroundColor Yellow
} else {
    Write-Host 'No secrets inside: send .env and .secrets\ separately (USB or password manager only).'
}
