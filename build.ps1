# HeartbeatAgent Builder Script
# =============================
# This script will:
# 1. Kill any running HeartbeatAgent processes
# 2. Clean up old build files
# 3. Install dependencies
# 4. Build the executable

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HeartbeatAgent EXE Builder" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Kill running HeartbeatAgent processes
Write-Host "[1/5] Checking for running HeartbeatAgent processes..." -ForegroundColor Yellow

$processes = Get-Process -Name "HeartbeatAgent" -ErrorAction SilentlyContinue
if ($processes) {
    Write-Host "      Found $($processes.Count) running instance(s)" -ForegroundColor Red
    Write-Host "      Terminating processes..." -ForegroundColor Red

    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.Id -Force
            Write-Host "      ✓ Killed process ID: $($process.Id)" -ForegroundColor Green
        } catch {
            Write-Host "      ✗ Failed to kill process ID: $($process.Id)" -ForegroundColor Red
        }
    }

    Start-Sleep -Seconds 1
    Write-Host "      ✓ All HeartbeatAgent processes terminated" -ForegroundColor Green
} else {
    Write-Host "      ✓ No running HeartbeatAgent processes found" -ForegroundColor Green
}

Write-Host ""

# Step 2: Check if client_tray.py exists
Write-Host "[2/5] Checking for client_tray.py..." -ForegroundColor Yellow

if (-Not (Test-Path "client_tray.py")) {
    Write-Host "      ✗ ERROR: client_tray.py not found!" -ForegroundColor Red
    Write-Host "      Please make sure client_tray.py is in the current directory." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "      ✓ Found client_tray.py" -ForegroundColor Green
Write-Host ""

# Step 3: Clean up old build files
Write-Host "[3/5] Cleaning up old build files..." -ForegroundColor Yellow

$foldersToRemove = @("build", "dist", "__pycache__")
$filesToRemove = @("HeartbeatAgent.spec", "*.pyc")

foreach ($folder in $foldersToRemove) {
    if (Test-Path $folder) {
        Remove-Item -Path $folder -Recurse -Force
        Write-Host "      ✓ Removed $folder folder" -ForegroundColor Green
    }
}

foreach ($file in $filesToRemove) {
    if (Test-Path $file) {
        Remove-Item -Path $file -Force
        Write-Host "      ✓ Removed $file" -ForegroundColor Green
    }
}

Write-Host "      ✓ Cleanup complete" -ForegroundColor Green
Write-Host ""

# Step 4: Install dependencies
Write-Host "[4/5] Installing dependencies..." -ForegroundColor Yellow
Write-Host "      This may take a few minutes..." -ForegroundColor Gray
Write-Host ""

$dependencies = "pyinstaller", "pillow", "pystray", "psutil", "requests"

foreach ($dep in $dependencies) {
    Write-Host "      Installing $dep..." -ForegroundColor Gray
}

$installResult = & python -m pip install pyinstaller pillow pystray psutil requests 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "      ✓ Dependencies installed successfully" -ForegroundColor Green
} else {
    Write-Host "      ✗ Failed to install dependencies" -ForegroundColor Red
    Write-Host "      Error: $installResult" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""

# Step 5: Build the executable
Write-Host "[5/5] Building HeartbeatAgent.exe..." -ForegroundColor Yellow
Write-Host "      This may take several minutes..." -ForegroundColor Gray
Write-Host ""

$buildResult = & python -m PyInstaller --onefile --name HeartbeatAgent client_tray.py 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "      ✓ Build completed successfully!" -ForegroundColor Green

    # Check if exe exists
    if (Test-Path "dist\HeartbeatAgent.exe") {
        $fileSize = (Get-Item "dist\HeartbeatAgent.exe").Length / 1MB

        # Copy VBS launcher to dist folder
        if (Test-Path "HeartbeatAgent.vbs") {
            Copy-Item "HeartbeatAgent.vbs" "dist\HeartbeatAgent.vbs" -Force
            Write-Host "      ✓ Copied VBS launcher to dist folder" -ForegroundColor Green
        }

        Write-Host ""
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "  BUILD COMPLETE!" -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Location: $(Resolve-Path 'dist\HeartbeatAgent.exe')" -ForegroundColor Cyan
        Write-Host "  Size: $([math]::Round($fileSize, 2)) MB" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  HOW TO RUN:" -ForegroundColor Yellow
        Write-Host "  Double-click: dist\HeartbeatAgent.exe" -ForegroundColor White
        Write-Host "  (A console window will appear with live status)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  FEATURES:" -ForegroundColor Yellow
        Write-Host "  - Live status display in console" -ForegroundColor White
        Write-Host "  - System tray icon" -ForegroundColor White
        Write-Host "  - Type 'help' for available commands" -ForegroundColor White
        Write-Host "  - Type 'close' to exit safely (requires confirmation)" -ForegroundColor White
        Write-Host ""
        Write-Host "  DEPLOY TO OTHER PCS:" -ForegroundColor Yellow
        Write-Host "  Copy the file: HeartbeatAgent.exe" -ForegroundColor White
        Write-Host ""

        # Ask if user wants to open the dist folder
        $openFolder = Read-Host "Open dist folder? (Y/N)"
        if ($openFolder -eq "Y" -or $openFolder -eq "y") {
            Start-Process explorer.exe -ArgumentList (Resolve-Path "dist")
        }
    } else {
        Write-Host "      ✗ Build succeeded but EXE not found in dist folder" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "      ✗ Build failed!" -ForegroundColor Red
    Write-Host "      Error: $buildResult" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Enter to exit..." -ForegroundColor Gray
$null = Read-Host
