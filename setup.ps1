<#
  Content Automation setup for a fresh Windows 10/11 laptop (SETUP.bat runs this).

  Step 1  uv (runs the app)          Step 3  FFmpeg (video tool)
  Step 2  Python + the app           Step 4  Checks
  Step 5  What is still missing (and the Codex Desktop download page)

  Safe to run twice. Never prints secret values.
  -CheckOnly   only run the checks (step 4) and the summary; install nothing.
#>
param([switch]$CheckOnly)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell downloads are very slow with a progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
$Missing = New-Object System.Collections.Generic.List[string]
$CodexPage = 'https://openai.com/codex/'

function Show-Step([string]$Text) {
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Show-Ok([string]$Text) {
    Write-Host "  OK       $Text" -ForegroundColor Green
}

function Show-Problem([string]$Text, [string]$Fix) {
    Write-Host "  PROBLEM  $Text" -ForegroundColor Red
    Write-Host "           $Fix" -ForegroundColor Yellow
    $script:Missing.Add("$Text $Fix")
}

function Update-SessionPath {
    $parts = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        (Join-Path $env:USERPROFILE '.local\bin')
    )
    $env:Path = ($parts | Where-Object { $_ }) -join ';'
}

function Test-Native([scriptblock]$Command) {
    # True when the program exists and exits with 0; its output is hidden.
    $global:LASTEXITCODE = 1
    try {
        $null = & $Command 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Ffmpeg {
    # Same order as the app's docs: FFMPEG_PATH, then tools\ffmpeg\bin, then PATH.
    if ($env:FFMPEG_PATH -and (Test-Path -LiteralPath $env:FFMPEG_PATH)) { return $env:FFMPEG_PATH }
    $local = Join-Path $Root 'tools\ffmpeg\bin\ffmpeg.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    $command = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

function Test-CodexDesktop {
    if (Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction SilentlyContinue) { return $true }
    $menus = @(
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
    )
    $links = Get-ChildItem -LiteralPath $menus -Recurse -Filter '*Codex*' -ErrorAction SilentlyContinue
    return [bool]$links
}

function Install-Uv {
    Show-Step 'Step 1 of 5: uv (runs the app)'
    Update-SessionPath
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Show-Ok 'uv is already installed.'
        return
    }
    Write-Host '  Installing uv from astral.sh (about 1 minute) ...'
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex"
    Update-SessionPath
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Show-Ok 'uv is installed.'
    } else {
        Show-Problem 'uv could not be installed.' 'Check the internet connection, then double-click SETUP.bat again.'
    }
}

function Install-App {
    Show-Step 'Step 2 of 5: Python and the app'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Show-Problem 'Skipped: uv is missing.' 'Fix step 1 first, then double-click SETUP.bat again.'
        return
    }
    $pyproject = Get-Content -LiteralPath (Join-Path $Root 'pyproject.toml') -Raw
    $match = [regex]::Match($pyproject, 'requires-python\s*=\s*"[^0-9]*(\d+\.\d+)')
    $version = '3.13'
    if ($match.Success) { $version = $match.Groups[1].Value }
    Write-Host "  Installing Python $version (a few minutes the first time) ..."
    & uv python install $version
    if ($LASTEXITCODE -eq 0) {
        Show-Ok "Python $version is installed."
    } else {
        Show-Problem "Python $version could not be installed." 'Check the internet connection, then double-click SETUP.bat again.'
        return
    }
    Write-Host '  Installing the app and its parts (a few minutes the first time) ...'
    & uv sync
    if ($LASTEXITCODE -eq 0) {
        Show-Ok 'The app is installed.'
    } else {
        Show-Problem 'The app could not be installed (uv sync failed).' 'Check the internet connection, then double-click SETUP.bat again.'
    }
}

function Install-Ffmpeg {
    Show-Step 'Step 3 of 5: FFmpeg (video tool)'
    if (Find-Ffmpeg) {
        Show-Ok 'FFmpeg is already installed.'
        return
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host '  Installing FFmpeg with winget ...'
        & winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
        Update-SessionPath
    }
    if (-not (Find-Ffmpeg)) {
        Write-Host '  Downloading FFmpeg from gyan.dev into tools\ffmpeg (about 100 MB) ...'
        $tools = Join-Path $Root 'tools'
        $zip = Join-Path $tools 'ffmpeg-download.zip'
        $unpacked = Join-Path $tools 'ffmpeg-download'
        $target = Join-Path $tools 'ffmpeg'
        try {
            New-Item -ItemType Directory -Force -Path $tools | Out-Null
            Invoke-WebRequest -UseBasicParsing -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip
            if (Test-Path -LiteralPath $unpacked) { Remove-Item -LiteralPath $unpacked -Recurse -Force }
            Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force
            $inner = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Move-Item -LiteralPath $inner.FullName -Destination $target
        } catch {
            Write-Host "  Download failed: $($_.Exception.Message)"
        } finally {
            if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
            if (Test-Path -LiteralPath $unpacked) { Remove-Item -LiteralPath $unpacked -Recurse -Force }
        }
    }
    if (Find-Ffmpeg) {
        Show-Ok 'FFmpeg is installed.'
    } else {
        Show-Problem 'FFmpeg could not be installed.' 'Check the internet connection, then double-click SETUP.bat again.'
    }
}

function Test-Setup {
    Show-Step 'Step 4 of 5: Checks'
    Update-SessionPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Show-Problem 'uv is not installed.' 'Double-click SETUP.bat (without -CheckOnly).'
    } elseif (Test-Native { uv run --no-sync ca --help }) {
        Show-Ok 'The app starts (ca --help).'
    } else {
        Show-Problem 'The app does not start (ca --help).' 'Double-click SETUP.bat again.'
    }

    $ffmpeg = Find-Ffmpeg
    if ($ffmpeg -and (Test-Native { & $ffmpeg -version })) {
        Show-Ok 'FFmpeg runs.'
    } else {
        Show-Problem 'FFmpeg does not run.' 'Double-click SETUP.bat again.'
    }

    if (Test-Path -LiteralPath (Join-Path $Root '.env') -PathType Leaf) {
        Show-Ok 'The settings file (.env) is there.'
    } else {
        Show-Problem 'The settings file (.env) is missing.' "Ask for it (USB or password manager, never e-mail) and put it in $Root"
    }

    foreach ($name in 'google_oauth_client.json', 'google_token.json', 'drive_state.json') {
        if (Test-Path -LiteralPath (Join-Path $Root ".secrets\$name") -PathType Leaf) {
            Show-Ok "Google Drive key file $name is there."
        } else {
            Show-Problem "Google Drive key file .secrets\$name is missing." "Ask for the .secrets folder (USB or password manager) and put it in $Root"
        }
    }

    $fonts = Get-ChildItem -LiteralPath (Join-Path $Root 'assets\fonts') -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in '.ttf', '.otf' }
    if ($fonts) {
        Show-Ok "Fonts are there ($(@($fonts).Count) files)."
    } else {
        Show-Problem 'No font in assets\fonts.' 'Unzip the whole project again into this folder.'
    }

    if (Test-CodexDesktop) {
        Show-Ok 'Codex Desktop is installed.'
    } else {
        Show-Problem 'Codex Desktop is not installed.' "Install it from $CodexPage and sign in."
    }
}

if (-not $CheckOnly) {
    Write-Host 'Setting up Content Automation. This window can stay open; it takes 5-15 minutes.'
    Install-Uv
    Install-App
    Install-Ffmpeg
}
Test-Setup

Show-Step 'Step 5 of 5: Result'
if ($Missing.Count -eq 0) {
    Write-Host '  ALL OK. Open this folder in Codex Desktop and type: show calendar' -ForegroundColor Green
    exit 0
}
Write-Host "  Still missing ($($Missing.Count)):" -ForegroundColor Red
foreach ($line in $Missing) { Write-Host "  - $line" -ForegroundColor Yellow }
if (-not $CheckOnly -and -not (Test-CodexDesktop)) {
    Write-Host "  Opening the Codex Desktop download page: $CodexPage"
    Start-Process $CodexPage
}
exit 1
