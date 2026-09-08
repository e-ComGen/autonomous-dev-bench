[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [switch]$AutoReboot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Error "WINDOWS_HOST_QUALIFICATION_FAIL: $Message"
    exit 2
}

function Info([string]$Message) {
    Write-Host "[windows-bootstrap] $Message"
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-ProcessArg([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Restart-Elevated {
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', (Quote-ProcessArg $PSCommandPath),
        '-Distro', (Quote-ProcessArg $Distro)
    )
    if ($AutoReboot) { $arguments += '-AutoReboot' }
    Info "Administrator rights are required for first-time WSL/Docker setup. Opening UAC..."
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList ($arguments -join ' ')
    exit 0
}

function Register-ResumeAfterReboot {
    $command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' + (Quote-ProcessArg $PSCommandPath) + ' -Distro ' + (Quote-ProcessArg $Distro)
    if ($AutoReboot) { $command += ' -AutoReboot' }
    $runOnce = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
    New-Item -Path $runOnce -Force | Out-Null
    Set-ItemProperty -Path $runOnce -Name 'AutonomousDevBenchPhase2Resume' -Value $command
    Info "Registered automatic continuation after the next Windows sign-in."
}

function Get-WslDistros {
    if (-not (Get-Command 'wsl.exe' -ErrorAction SilentlyContinue)) { return @() }
    $raw = (& wsl.exe --list --quiet 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($raw -split "`r?`n" | ForEach-Object { $_.Trim().Trim([char]0) } | Where-Object { $_ })
}

function Ensure-WSL {
    Info "Ensuring WSL2 and distro '$Distro'..."

    if (-not (Get-Command 'wsl.exe' -ErrorAction SilentlyContinue)) {
        Fail "wsl.exe is unavailable on this Windows build. Windows 10 22H2 or Windows 11 is required for this benchmark host."
    }

    & wsl.exe --update --web-download 2>$null | Out-Host
    & wsl.exe --set-default-version 2 2>$null | Out-Host

    $distros = Get-WslDistros
    if ($distros -notcontains $Distro) {
        Info "Installing WSL2 distribution '$Distro' automatically..."
        & wsl.exe --install -d $Distro --web-download --no-launch
        $installExit = $LASTEXITCODE
        if ($installExit -ne 0 -and $installExit -ne 3010) {
            Fail "Automatic WSL distribution installation failed with exit code $installExit."
        }
    }

    $distros = Get-WslDistros
    if ($distros -notcontains $Distro) {
        Register-ResumeAfterReboot
        Info "WSL components were installed, but Windows must reboot before the distro can initialize."
        if ($AutoReboot) {
            Info "AutoReboot requested. Rebooting Windows now; qualification will resume after sign-in."
            Restart-Computer -Force
        }
        exit 3010
    }

    & wsl.exe --set-version $Distro 2 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Register-ResumeAfterReboot
        Info "WSL2 conversion needs a Windows reboot. Bootstrap will resume after sign-in."
        if ($AutoReboot) { Restart-Computer -Force }
        exit 3010
    }

    & wsl.exe --set-default $Distro | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "Could not set '$Distro' as the WSL default distribution." }

    # Initialize the distro non-interactively as root, avoiding first-launch username prompts.
    & wsl.exe -d $Distro -u root -- /bin/sh -lc 'true'
    if ($LASTEXITCODE -ne 0) {
        Register-ResumeAfterReboot
        Info "WSL was installed but cannot initialize until Windows restarts."
        if ($AutoReboot) { Restart-Computer -Force }
        exit 3010
    }

    Info "Installing Linux prerequisites and Python 3.12 inside WSL..."
    & wsl.exe -d $Distro -u root -- bash -lc 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y --no-install-recommends ca-certificates git curl python3.12 python3.12-venv python3-pip'
    if ($LASTEXITCODE -ne 0) {
        Fail "Automatic Linux prerequisite installation failed inside '$Distro'."
    }
}

function Find-DockerExecutable {
    $command = Get-Command 'docker.exe' -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Install-DockerDesktop {
    Info "Docker Desktop is missing; installing it automatically with the WSL2 backend..."

    $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if ($winget) {
        & $winget.Source install --id Docker.DockerDesktop --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -eq 0) { return }
        Info "winget install failed; falling back to Docker's official installer."
    }

    if ($env:PROCESSOR_ARCHITECTURE -notin @('AMD64', 'x86')) {
        Fail "Automatic Docker fallback is currently qualified only for x86_64 Windows; observed '$env:PROCESSOR_ARCHITECTURE'."
    }

    $installer = Join-Path $env:TEMP 'Docker Desktop Installer.exe'
    $url = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
    Info "Downloading official Docker Desktop installer..."
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
    $process = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        'install',
        '--quiet',
        '--accept-license',
        '--backend=wsl-2',
        '--no-windows-containers'
    )
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
        Fail "Docker Desktop installer failed with exit code $($process.ExitCode)."
    }
}

function Ensure-DockerDesktop {
    $docker = Find-DockerExecutable
    if (-not $docker) {
        Install-DockerDesktop
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        $docker = Find-DockerExecutable
    }
    if (-not $docker) { Fail "Docker Desktop installation completed but docker.exe could not be found." }

    $desktopCandidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
    )
    $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($desktop) {
        $running = Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue
        if (-not $running) {
            Info "Starting Docker Desktop..."
            Start-Process -FilePath $desktop | Out-Null
        }
    }

    Info "Waiting for Docker Desktop Linux engine..."
    $deadline = (Get-Date).AddMinutes(5)
    $dockerInfoRaw = $null
    while ((Get-Date) -lt $deadline) {
        $dockerInfoRaw = (& $docker info --format '{{json .}}' 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $dockerInfoRaw) { break }
        Start-Sleep -Seconds 3
    }
    if (-not $dockerInfoRaw -or $LASTEXITCODE -ne 0) {
        Fail "Docker Desktop was installed and started, but its Linux engine did not become ready within 5 minutes."
    }

    $dockerInfo = $dockerInfoRaw | ConvertFrom-Json
    if ($dockerInfo.OSType -ne 'linux') {
        Fail "Docker Desktop started with OSType='$($dockerInfo.OSType)' instead of the required Linux engine."
    }

    return @($docker, $dockerInfo)
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail "This bootstrap must be launched from Windows PowerShell or PowerShell on Windows."
}

if (-not (Test-Administrator)) {
    Restart-Elevated
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ArtifactDir = Join-Path $RepoRoot 'artifacts\harbor-phase2\windows-host'
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
$HostEvidencePath = Join-Path $ArtifactDir 'host.json'

Ensure-WSL
$dockerResult = Ensure-DockerDesktop
$DockerExe = $dockerResult[0]
$DockerInfo = $dockerResult[1]

$ContainerIdentity = (& $DockerExe run --rm --pull=missing alpine:3.20 uname -sm 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $ContainerIdentity.StartsWith('Linux')) {
    Fail "Docker Desktop could not execute a Linux container. Observed: '$ContainerIdentity'"
}

# Docker Desktop integrates its Linux CLI with the default WSL2 distro. Give it a short
# readiness window after first installation/startup.
Info "Waiting for Docker Desktop WSL integration in '$Distro'..."
$wslDockerReady = $false
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    & wsl.exe -d $Distro -- bash -lc 'command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1'
    if ($LASTEXITCODE -eq 0) { $wslDockerReady = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $wslDockerReady) {
    Fail "Docker Desktop is installed and running, but WSL integration for '$Distro' did not become active automatically."
}

$WslList = (& wsl.exe --list --verbose 2>&1 | Out-String).Trim()
$WslRepoRoot = (& wsl.exe -d $Distro -- wslpath -a $RepoRoot 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($WslRepoRoot)) {
    Fail "Could not translate repository path into the WSL filesystem."
}

$HostEvidence = [ordered]@{
    schema_version = 2
    physical_host_os = 'windows'
    bootstrap_mode = 'automatic'
    windows = [ordered]@{
        version = [Environment]::OSVersion.Version.ToString()
        edition = (Get-CimInstance Win32_OperatingSystem).Caption
        architecture = $env:PROCESSOR_ARCHITECTURE
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    wsl = [ordered]@{
        distro = $Distro
        list_verbose = $WslList
        prerequisites_installed_automatically = $true
    }
    docker = [ordered]@{
        executable = $DockerExe
        server_version = $DockerInfo.ServerVersion
        operating_system = $DockerInfo.OperatingSystem
        os_type = $DockerInfo.OSType
        architecture = $DockerInfo.Architecture
        container_probe = $ContainerIdentity
        installed_or_verified_automatically = $true
    }
}
$HostJson = $HostEvidence | ConvertTo-Json -Depth 8
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($HostEvidencePath, $HostJson + [Environment]::NewLine, $Utf8NoBom)

$WslHostEvidence = (& wsl.exe -d $Distro -- wslpath -a $HostEvidencePath 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($WslHostEvidence)) {
    Fail "Could not translate the evidence path into WSL."
}

$WslScript = "$WslRepoRoot/tools/qualify_windows_host_wsl.sh"
Info "Running pinned Harbor qualification inside WSL2..."
& wsl.exe -d $Distro -- bash $WslScript $WslHostEvidence
if ($LASTEXITCODE -ne 0) {
    Fail "The WSL2 Harbor qualification failed."
}

$FinalEvidence = Join-Path $ArtifactDir 'PHASE2_WINDOWS_HOST.json'
if (-not (Test-Path $FinalEvidence)) {
    Fail "Harbor completed but final evidence was not produced: $FinalEvidence"
}

Write-Host ''
Write-Host 'WINDOWS_HOST_QUALIFICATION_PASS'
Write-Host "Evidence: $FinalEvidence"
