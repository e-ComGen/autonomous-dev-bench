[CmdletBinding()]
param(
    [string]$Distro = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Error "WINDOWS_HOST_QUALIFICATION_FAIL: $Message"
    exit 2
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail "This entrypoint must be launched from Windows PowerShell or PowerShell on Windows."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ArtifactDir = Join-Path $RepoRoot "artifacts\harbor-phase2\windows-host"
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
$HostEvidencePath = Join-Path $ArtifactDir "host.json"

foreach ($Command in @("wsl.exe", "docker.exe")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        Fail "$Command is missing. WSL2 and Docker Desktop are required."
    }
}

$WslList = (& wsl.exe --list --verbose 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Fail "WSL is not available. Run 'wsl --install', reboot if Windows requests it, then retry."
}
if ($WslList -notmatch "(?m)^\s*\*.*\s+2\s*$" -and [string]::IsNullOrWhiteSpace($Distro)) {
    Fail "The default WSL distribution is not WSL2. 'wsl -l -v' must show VERSION 2 for the default distro."
}
if (-not [string]::IsNullOrWhiteSpace($Distro)) {
    $EscapedDistro = [regex]::Escape($Distro)
    if ($WslList -notmatch "(?m)^\s*\*?\s*$EscapedDistro\s+.*\s+2\s*$") {
        Fail "Requested distro '$Distro' is missing or is not WSL2."
    }
}

$DockerInfoRaw = (& docker.exe info --format '{{json .}}' 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Fail "Docker Desktop daemon is not reachable. Start Docker Desktop and retry."
}
$DockerInfo = $DockerInfoRaw | ConvertFrom-Json
if ($DockerInfo.OSType -ne "linux") {
    Fail "Docker Desktop must use the Linux container engine; observed OSType='$($DockerInfo.OSType)'."
}

$ContainerIdentity = (& docker.exe run --rm --pull=missing alpine:3.20 uname -sm 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $ContainerIdentity.StartsWith("Linux")) {
    Fail "Docker Desktop could not execute a Linux container. Observed: '$ContainerIdentity'"
}

$WslArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Distro)) {
    $WslArgs += @("-d", $Distro)
}
$WslArgs += @("--", "wslpath", "-a", $RepoRoot)
$WslRepoRoot = (& wsl.exe @WslArgs 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($WslRepoRoot)) {
    Fail "Could not translate repository path into the WSL filesystem."
}

$HostEvidence = [ordered]@{
    schema_version = 1
    physical_host_os = "windows"
    windows = [ordered]@{
        version = [Environment]::OSVersion.Version.ToString()
        edition = (Get-CimInstance Win32_OperatingSystem).Caption
        architecture = $env:PROCESSOR_ARCHITECTURE
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    wsl = [ordered]@{
        requested_distro = $Distro
        list_verbose = $WslList
    }
    docker = [ordered]@{
        server_version = $DockerInfo.ServerVersion
        operating_system = $DockerInfo.OperatingSystem
        os_type = $DockerInfo.OSType
        architecture = $DockerInfo.Architecture
        container_probe = $ContainerIdentity
    }
}
$HostEvidence | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $HostEvidencePath

$WslEvidenceArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Distro)) {
    $WslEvidenceArgs += @("-d", $Distro)
}
$WslEvidenceArgs += @("--", "wslpath", "-a", $HostEvidencePath)
$WslHostEvidence = (& wsl.exe @WslEvidenceArgs 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    Fail "Could not translate the evidence path into WSL."
}

function BashQuote([string]$Value) {
    return "'" + $Value.Replace("'", "'\"'\"'") + "'"
}

$Command = "cd $(BashQuote $WslRepoRoot) && bash tools/qualify_windows_host_wsl.sh $(BashQuote $WslHostEvidence)"
$RunArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Distro)) {
    $RunArgs += @("-d", $Distro)
}
$RunArgs += @("--", "bash", "-lc", $Command)

Write-Host "Windows host detected: $([Environment]::OSVersion.Version)"
Write-Host "Docker Linux engine: $($DockerInfo.OperatingSystem) / $($DockerInfo.Architecture)"
Write-Host "Running pinned Harbor qualification inside WSL2..."
& wsl.exe @RunArgs
if ($LASTEXITCODE -ne 0) {
    Fail "The WSL2 Harbor qualification failed. The error above identifies the missing prerequisite or failed gate."
}

$FinalEvidence = Join-Path $ArtifactDir "PHASE2_WINDOWS_HOST.json"
if (-not (Test-Path $FinalEvidence)) {
    Fail "Harbor completed but final evidence was not produced: $FinalEvidence"
}

Write-Host ""
Write-Host "WINDOWS_HOST_QUALIFICATION_PASS"
Write-Host "Evidence: $FinalEvidence"
