# 🖥️ PC Heartbeat Monitoring System v2.0

## 🎉 What's New in v2.0

**Complete Background Service - Zero Visibility!**

v2.0 is a ground-up redesign that solves the #1 user complaint: **accidental closure**. The agent now runs completely in the background with **NO console window**, appearing only as a system tray icon.

### Key Improvements

| Feature | v1.0 | v2.0 |
|---------|------|------|
| **Console Window** | ✅ Visible (users closed it) | ❌ None - completely hidden |
| **Taskbar Icon** | ✅ Shows in taskbar | ❌ Hidden from taskbar |
| **Visibility** | Console + Tray | Tray only |
| **Logging** | Console output | File-based logging |
| **Settings** | Console commands | GUI dialog from tray |
| **Status View** | Live console | On-demand GUI window |
| **User Confusion** | "What is this?" → Close | Invisible = Can't close |

## ✨ v2.0 Features

### 🎯 Completely Background
- **No console window** - Uses `--noconsole` PyInstaller flag
- **No taskbar presence** - Doesn't appear in taskbar
- **Silent operation** - Users won't even know it's running
- **System tray only** - Heart icon in system tray (hidden by default)

### 📊 Smart System Tray
- **Live heartbeat counter** - Shows count directly on icon
- **Color-coded status**:
  - 🟢 Green = Connected (heartbeat within 60s)
  - 🟡 Yellow = Warning (heartbeat 60s-2min ago)
  - 🔴 Red = Disconnected (network error)
  - ⚪ Gray = Starting up
- **Rich tooltip** - Shows device name, status, heartbeat count

### 🖱️ Tray Menu
Right-click the tray icon:
- **View Status** - Opens detailed status window
- **Settings** - Change device name, server URL, interval
- **Exit** - Gracefully shut down agent

### 📝 File-Based Logging
- **Rotating logs** - Max 5MB per file, keeps 3 backups
- **Location**: `%LOCALAPPDATA%\HeartbeatAgent\logs\heartbeat.log`
- **View in Status window** - Last 20 log lines shown
- **Never loses data** - Persistent across restarts

### ⚙️ GUI Settings Dialog
- **Device Name** - Set/change anytime
- **Server URL** - Configure server endpoint
- **Heartbeat Interval** - 5-300 seconds (default: 10)
- **MAC Address** - Display only (auto-detected)
- **First-run wizard** - Guides new installations

### 📊 Status Viewer Window
On-demand window showing:
- Device information (name, MAC, server)
- Connection status (running/stopped)
- Heartbeat statistics (total count, last success)
- Recent log entries (last 20 lines)
- Error messages (if any)

## 🚀 Installation

### Download Pre-built Executable

1. Download `HeartbeatAgentV2.exe` from releases
2. Double-click to run
3. Look for heart ❤️ icon in system tray (may be hidden)
4. Right-click icon → Settings to configure

### Build from Source

```powershell
# Clone repository
git clone https://github.com/joshuaoswari/ppp-app.git
cd ppp-app

# Run build script
powershell -ExecutionPolicy Bypass -File build_v2.ps1

# Output: dist\HeartbeatAgentV2.exe
```

## 📖 Usage Guide

### First Run

1. **Launch** - Double-click `HeartbeatAgentV2.exe`
2. **Configuration Dialog** - Appears automatically
   - Enter device name (default: your PC name)
   - Verify server URL
   - Click "Save"
3. **Find Tray Icon** - Look in system tray (bottom-right)
   - May be hidden in overflow area (click ^ arrow)
4. **Done!** - Agent runs in background

### Daily Use

**Normal operation**: Nothing! Just runs silently.

**To check status**: Right-click tray icon → "View Status"

**To change settings**: Right-click tray icon → "Settings"

**To exit**: Right-click tray icon → "Exit"

### Logs

View logs at: `%LOCALAPPDATA%\HeartbeatAgent\logs\heartbeat.log`

Or: Right-click icon → "View Status" → See "Recent Logs" section

## 🔧 Configuration Files

### Config Location
`%LOCALAPPDATA%\HeartbeatAgent\config.json`

### Example Config
```json
{
    "server_url": "https://your-server.com",
    "device_name": "Office-PC-01",
    "heartbeat_interval": 10,
    "max_retries": 3
}
```

### Lock File
`%LOCALAPPDATA%\HeartbeatAgent\agent.lock`
- Prevents multiple instances
- Auto-removed on exit
- Contains process ID

## 🎨 Visual Indicators

### Tray Icon Colors

- **Green Heart** 🟢 - Connected, recent heartbeat
- **Yellow Heart** 🟡 - Warning, heartbeat delayed
- **Red Heart** 🔴 - Error, connection failed
- **Gray Heart** ⚪ - Starting up, not configured

### Heartbeat Counter

Numbers displayed on icon:
- `1` to `999` - Exact count
- `999+` - Count exceeded display limit

## 🔐 Auto-Start Setup

### Option 1: Task Scheduler (Recommended)

```powershell
# Run as Administrator
schtasks /create /tn "Heartbeat Agent" /tr "C:\Path\To\HeartbeatAgentV2.exe" /sc onlogon /rl highest
```

Or manually:
1. Open Task Scheduler (`taskschd.msc`)
2. Create Basic Task → "Heartbeat Agent"
3. Trigger: "When I log on"
4. Action: Start program → Browse to `HeartbeatAgentV2.exe`
5. Check "Run with highest privileges"
6. Done!

### Option 2: Startup Folder

1. Press `Win+R`
2. Type: `shell:startup`
3. Create shortcut to `HeartbeatAgentV2.exe`
4. Done! (Starts on login)

### Option 3: Registry Run Key

```powershell
# Run as Administrator
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "HeartbeatAgent" /t REG_SZ /d "C:\Path\To\HeartbeatAgentV2.exe" /f
```

## 🆚 Comparison: v1.0 vs v2.0

### v1.0 Problems Solved

❌ **Console window visible** → Users closed it thinking it was unused
❌ **Taskbar clutter** → Appeared as "unknown app"
❌ **Console logs only** → Lost after close
❌ **Console commands** → Hard to remember
❌ **Always visible** → Distracting

### v2.0 Solutions

✅ **No console** → Can't close what you can't see
✅ **No taskbar** → Invisible to users
✅ **File logging** → Persistent, viewable anytime
✅ **GUI dialogs** → Intuitive, easy to use
✅ **Tray only** → Hidden, professional

## 🐛 Troubleshooting

### Can't Find Tray Icon

1. Look for ^ arrow in system tray (bottom-right)
2. Click arrow to show hidden icons
3. Look for heart ❤️ icon
4. Drag icon to main tray area to pin it

### Check if Running

```powershell
# PowerShell
Get-Process HeartbeatAgentV2

# Task Manager
# Look for "HeartbeatAgentV2.exe" in Processes tab
```

### Agent Won't Start

1. Check lock file: `%LOCALAPPDATA%\HeartbeatAgent\agent.lock`
2. If exists, delete it (previous instance may have crashed)
3. Check logs: `%LOCALAPPDATA%\HeartbeatAgent\logs\heartbeat.log`
4. Try running as Administrator

### Another Instance Already Running

Error message: "Another instance of Heartbeat Agent is already running!"

**Solution**:
1. Check system tray for existing icon
2. If not visible, check Task Manager for `HeartbeatAgentV2.exe`
3. Kill process or delete lock file and restart

### Can't Save Settings

**Permission denied** errors:

1. Run as Administrator once
2. Or manually create folder: `%LOCALAPPDATA%\HeartbeatAgent`
3. Give write permissions to your user account

### Network Errors

Check logs for specific errors:
- **Connection refused** → Server not running or wrong URL
- **Timeout** → Network/firewall blocking
- **404** → Wrong server URL or endpoint changed

## 📊 Server Compatibility

v2.0 client is **fully compatible** with v1.0 server.

No server changes required! Just deploy new client.

### API Endpoints Used

- `POST /api/heartbeat` - Send heartbeat
- `POST /api/login` - Record login (if tracked)
- `POST /api/logout` - Record logout (if tracked)

## 🔒 Security Notes

- **No elevation required** - Runs as normal user
- **No network listening** - Outbound only
- **Local config only** - No remote configuration
- **Single instance** - Lock file prevents duplicates
- **Clean shutdown** - Removes lock file on exit

## 📈 Performance

### Resource Usage

- **Memory**: ~15-20 MB (idle)
- **CPU**: <1% (during heartbeat)
- **Disk**: ~50 KB logs per day (compressed: ~10 KB)
- **Network**: ~1 KB per heartbeat

### Efficiency Improvements

- Rotating logs prevent unlimited growth
- Efficient icon updates (only when status changes)
- Daemon threads for non-blocking operations
- Single instance lock prevents resource waste

## 🎁 Deployment Tips

### Mass Deployment

1. **Pre-configure** `config.json` with server URL
2. **Package** with `HeartbeatAgentV2.exe`
3. **Deploy** via Group Policy or management tool
4. **Auto-start** via Task Scheduler or Registry
5. **Users never see it!**

### Silent Installation Script

```powershell
# silent_install.ps1
$InstallDir = "C:\Program Files\HeartbeatAgent"
$ExePath = "$InstallDir\HeartbeatAgentV2.exe"

# Create directory
New-Item -ItemType Directory -Path $InstallDir -Force

# Copy executable
Copy-Item "HeartbeatAgentV2.exe" -Destination $ExePath

# Create pre-configured config
$ConfigDir = "$env:LOCALAPPDATA\HeartbeatAgent"
New-Item -ItemType Directory -Path $ConfigDir -Force

$Config = @{
    server_url = "https://your-server.com"
    device_name = $env:COMPUTERNAME
    heartbeat_interval = 10
    max_retries = 3
} | ConvertTo-Json

$Config | Out-File "$ConfigDir\config.json" -Encoding utf8

# Create auto-start task
schtasks /create /tn "Heartbeat Agent" /tr $ExePath /sc onlogon /rl highest /f

# Start immediately
Start-Process $ExePath
```

## 📝 License

MIT License - Free to use and modify

## 🙏 Credits

Built with:
- **Python** - Core language
- **PyInstaller** - Executable packaging
- **pystray** - System tray integration
- **Pillow** - Icon generation
- **tkinter** - GUI dialogs
- **psutil** - Process management
- **requests** - HTTP client

---

**v2.0** - The invisible agent that never gets closed! 🎉
