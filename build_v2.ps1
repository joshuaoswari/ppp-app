# Build Script for Heartbeat Agent v2.0 - Background Service
# ===========================================================
# Creates a windowless executable that runs only in system tray

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heartbeat Agent v2.0 Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: Python is not installed or not in PATH!" -ForegroundColor Red
    exit 1
}

$pythonVersion = python --version
Write-Host "Found: $pythonVersion" -ForegroundColor Green
Write-Host ""

# Check if PyInstaller is installed
Write-Host "[2/5] Checking PyInstaller..." -ForegroundColor Yellow
$pyinstallerInstalled = python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install PyInstaller!" -ForegroundColor Red
        exit 1
    }
}
Write-Host "PyInstaller is ready" -ForegroundColor Green
Write-Host ""

# Check dependencies
Write-Host "[3/5] Checking dependencies..." -ForegroundColor Yellow
$dependencies = @("requests", "Pillow", "pystray", "psutil")
foreach ($dep in $dependencies) {
    $installed = python -c "import $($dep.ToLower().Replace('-', '_'))" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing $dep..." -ForegroundColor Yellow
        python -m pip install $dep
    } else {
        Write-Host "$dep is installed" -ForegroundColor Green
    }
}
Write-Host ""

# Build the executable
Write-Host "[4/5] Building HeartbeatAgent v2.0..." -ForegroundColor Yellow
Write-Host "Using --noconsole flag for background operation" -ForegroundColor Cyan
Write-Host ""

# PyInstaller command for windowless executable
$buildCmd = @"
python -m PyInstaller ``
    --onefile ``
    --noconsole ``
    --name HeartbeatAgentV2 ``
    --hidden-import=pystray._win32 ``
    --hidden-import=PIL._tkinter_finder ``
    client_v2.py ``
    --clean
"@

Write-Host "Build command:" -ForegroundColor Cyan
Write-Host $buildCmd -ForegroundColor Gray
Write-Host ""

Invoke-Expression $buildCmd

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[5/5] Build completed successfully!" -ForegroundColor Green
Write-Host ""

# Show output location
$exePath = "dist\HeartbeatAgentV2.exe"
if (Test-Path $exePath) {
    $exeSize = (Get-Item $exePath).Length / 1MB
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Executable: $exePath" -ForegroundColor Green
    Write-Host "Size: $($exeSize.ToString('0.00')) MB" -ForegroundColor Green
    Write-Host ""
    Write-Host "v2.0 Features:" -ForegroundColor Yellow
    Write-Host "  - No console window" -ForegroundColor White
    Write-Host "  - Runs completely in background" -ForegroundColor White
    Write-Host "  - Only visible in system tray" -ForegroundColor White
    Write-Host "  - Doesn't appear in taskbar" -ForegroundColor White
    Write-Host "  - File-based logging" -ForegroundColor White
    Write-Host "  - GUI settings from tray menu" -ForegroundColor White
    Write-Host ""
    Write-Host "To run:" -ForegroundColor Yellow
    Write-Host "  1. Double-click $exePath" -ForegroundColor White
    Write-Host "  2. Look for heart icon in system tray" -ForegroundColor White
    Write-Host "  3. Right-click icon for menu" -ForegroundColor White
    Write-Host ""
    Write-Host "Logs location:" -ForegroundColor Yellow
    Write-Host "  %LOCALAPPDATA%\HeartbeatAgent\logs\heartbeat.log" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "ERROR: Executable not found!" -ForegroundColor Red
    exit 1
}

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
