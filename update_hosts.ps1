# Requires elevation to edit the Windows hosts file.

$hostsPath = "$env:WINDIR\System32\drivers\etc\hosts"
$targetHost = "ns.exitgames.com"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-Host "Restarting with administrator privileges..." -ForegroundColor Yellow
    $scriptPath = $PSCommandPath

    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $scriptPath + '"')
    )
    exit
}

Write-Host "Select an action:" -ForegroundColor Cyan
Write-Host "  1) Set or update $targetHost" -ForegroundColor Cyan
Write-Host "  2) Remove $targetHost" -ForegroundColor Cyan

$choice = Read-Host "Enter 1 or 2"

$Remove = $false
$IpAddress = $null

if ($choice -eq "1") {
    $IpAddress = Read-Host "Enter the IP address for $targetHost"
}
elseif ($choice -eq "2") {
    $Remove = $true
}
else {
    Write-Error "Invalid choice: $choice. Use 1 or 2."
    exit 1
}

if (-not $Remove) {
    $parsedIp = $null
    if (-not [System.Net.IPAddress]::TryParse($IpAddress, [ref]$parsedIp)) {
        Write-Error "Invalid IP address: $IpAddress"
        exit 1
    }
}

if (-not (Test-Path $hostsPath)) {
    Write-Error "Hosts file not found at: $hostsPath"
    exit 1
}

# Force array type so that if the file has only 1 line, it doesn't default to a string.
$lines = @(Get-Content -Path $hostsPath -ErrorAction Stop)

if ($Remove) {
    $newLines = @()
    foreach ($line in $lines) {
        if ($line -match "^\s*#") {
            $newLines += $line
            continue
        }
        if ($line -match "(^|\s)$([regex]::Escape($targetHost))(\s|$)") {
            continue
        }
        $newLines += $line
    }

    try {
        $fileInfo = Get-Item -Path $hostsPath -ErrorAction Stop
        if ($fileInfo.Attributes -band [System.IO.FileAttributes]::ReadOnly) {
            $fileInfo.Attributes = $fileInfo.Attributes -bxor [System.IO.FileAttributes]::ReadOnly
        }

        [System.IO.File]::WriteAllLines(
            $hostsPath,
            [string[]]$newLines,
            [System.Text.Encoding]::ASCII
        )
    }
    catch {
        Write-Error "Failed to update hosts file: $($_.Exception.Message)"
        exit 1
    }

    Write-Host "Hosts updated successfully:" -ForegroundColor Green
    Write-Host "  Removed entries for $targetHost" -ForegroundColor Green
    exit
}
$updated = $false
$newLine = "$IpAddress`t$targetHost"

for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*#") {
        continue
    }

    if ($lines[$i] -match "(^|\s)$([regex]::Escape($targetHost))(\s|$)") {
        $lines[$i] = $newLine
        $updated = $true
    }
}

if (-not $updated) {
    $lines += $newLine
}

try {
    $fileInfo = Get-Item -Path $hostsPath -ErrorAction Stop
    if ($fileInfo.Attributes -band [System.IO.FileAttributes]::ReadOnly) {
        $fileInfo.Attributes = $fileInfo.Attributes -bxor [System.IO.FileAttributes]::ReadOnly
    }

    [System.IO.File]::WriteAllLines(
        $hostsPath,
        [string[]]$lines,
        [System.Text.Encoding]::ASCII
    )
}
catch {
    Write-Error "Failed to update hosts file: $($_.Exception.Message)"
    exit 1
}

Write-Host "Hosts updated successfully:" -ForegroundColor Green
Write-Host "  $newLine" -ForegroundColor Green
