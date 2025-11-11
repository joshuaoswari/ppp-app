"""
PC Heartbeat Client Agent - System Tray Version
================================================
Enhanced version with system tray icon showing heartbeat status and count.

Features:
- System tray icon with live heartbeat count
- Right-click menu (Status, Exit)
- Tooltip showing connection info
- Visual feedback on heartbeat success/failure
- GUI popup for initial configuration
"""

import requests
import time
import json
from datetime import datetime
import socket
import sys
import os
import threading
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item
import tempfile
import atexit
import uuid
import ctypes
from ctypes import wintypes

# ==================== SINGLE INSTANCE LOCK ====================

LOCK_FILE = os.path.join(tempfile.gettempdir(), 'heartbeat_agent.lock')

def check_single_instance():
    """Ensure only one instance of the agent is running"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process is still running (Windows specific)
            try:
                import psutil
                if psutil.pid_exists(pid):
                    return False
            except ImportError:
                # If psutil not available, assume process is running
                return False
        except:
            # Lock file corrupted, remove it
            os.remove(LOCK_FILE)
    
    # Create lock file
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    # Register cleanup on exit
    atexit.register(cleanup_lock_file)
    
    return True

def cleanup_lock_file():
    """Remove lock file on exit"""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except:
        pass

# ==================== CONFIGURATION ====================

# Default server URL (will be shown in GUI popup)
SERVER_URL = "https://ppp-app-production-8aa2.up.railway.app/heartbeat"

# Device name will be set via GUI popup (leave as None for GUI prompt)
DEVICE_NAME = None

# Heartbeat interval in seconds (default: 60 seconds = 1 minute)
HEARTBEAT_INTERVAL = 60

# Retry settings
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300

# Configuration file path - use AppData for write permissions
def get_config_path():
    """Get the configuration file path in a user-writable location"""
    if sys.platform == 'win32':
        # Use AppData/Local for Windows
        appdata = os.getenv('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        config_dir = os.path.join(appdata, 'HeartbeatAgent')
    else:
        # Use home directory for other platforms
        config_dir = os.path.expanduser('~/.heartbeat')

    # Create directory if it doesn't exist
    try:
        os.makedirs(config_dir, exist_ok=True)
    except:
        # Fallback to temp directory if AppData is not writable
        config_dir = tempfile.gettempdir()

    return os.path.join(config_dir, 'heartbeat_config.json')

CONFIG_FILE = get_config_path()

# Global variables for system tray
heartbeat_count = 0
is_online = False
tray_icon = None
device_name_global = ""
shutdown_event = threading.Event()  # Event to signal shutdown
_console_handler_ref = None  # Keep reference to console handler to prevent garbage collection

# ==================== CONFIGURATION FUNCTIONS ====================

def load_config():
    """Load configuration from file if it exists"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('device_name'), config.get('server_url')
        except Exception as e:
            print(f"⚠️  Could not load config file: {e}")
    return None, None

def save_config(device_name, server_url):
    """Save configuration to file"""
    try:
        config = {
            'device_name': device_name,
            'server_url': server_url,
            'last_updated': datetime.now().isoformat()
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"✅ Configuration saved")
        return True
    except Exception as e:
        print(f"❌ ERROR: Could not save config file: {e}")
        print(f"   Attempted path: {CONFIG_FILE}")
        return False

def get_default_device_name():
    """Get default device name based on computer name"""
    try:
        hostname = socket.gethostname()
        return hostname.replace('-', '_').replace('.', '_')
    except:
        return "PC-Unknown"

def get_mac_address():
    """Get the MAC address of the PC"""
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                       for elements in range(0,2*6,2)][::-1])
        return mac
    except:
        return None

class DeviceNameDialog:
    """GUI dialog for configuring device name"""
    
    def __init__(self):
        self.device_name = None
        self.server_url = None
        
    def show_dialog(self, current_name=None, current_server=None):
        """Show configuration dialog"""
        root = tk.Tk()
        root.withdraw()
        
        try:
            root.iconbitmap(default='')
        except:
            pass
        
        dialog = tk.Toplevel(root)
        dialog.title("PC Heartbeat Agent - Configuration")
        dialog.geometry("500x300")
        dialog.resizable(False, False)
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (300 // 2)
        dialog.geometry(f"+{x}+{y}")
        
        dialog.attributes('-topmost', True)
        
        header = tk.Label(
            dialog, 
            text="🖥️ PC Heartbeat Agent Setup",
            font=("Segoe UI", 14, "bold"),
            fg="#667eea"
        )
        header.pack(pady=10)
        
        instructions = tk.Label(
            dialog,
            text="Configure your device name and server URL",
            font=("Segoe UI", 9),
            fg="#666"
        )
        instructions.pack(pady=5)
        
        input_frame = tk.Frame(dialog)
        input_frame.pack(pady=20, padx=30, fill="both", expand=True)
        
        name_label = tk.Label(
            input_frame, 
            text="Device Name:",
            font=("Segoe UI", 10, "bold")
        )
        name_label.grid(row=0, column=0, sticky="w", pady=5)
        
        name_entry = tk.Entry(input_frame, font=("Segoe UI", 10), width=35)
        name_entry.grid(row=1, column=0, pady=5, ipady=5)
        
        default_name = current_name or get_default_device_name()
        name_entry.insert(0, default_name)
        name_entry.select_range(0, tk.END)
        name_entry.focus()
        
        example = tk.Label(
            input_frame,
            text="Examples: Jakarta-Office, Store-01, HQ-Manager",
            font=("Segoe UI", 8),
            fg="#999"
        )
        example.grid(row=2, column=0, sticky="w")
        
        server_label = tk.Label(
            input_frame,
            text="Server URL:",
            font=("Segoe UI", 10, "bold")
        )
        server_label.grid(row=3, column=0, sticky="w", pady=(15, 5))
        
        server_entry = tk.Entry(input_frame, font=("Segoe UI", 10), width=35)
        server_entry.grid(row=4, column=0, pady=5, ipady=5)
        server_entry.insert(0, current_server or SERVER_URL)
        
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=10)
        
        def on_ok():
            name = name_entry.get().strip()
            server = server_entry.get().strip()
            
            if not name:
                messagebox.showwarning("Invalid Input", "Please enter a device name.", parent=dialog)
                return
            
            if not server:
                messagebox.showwarning("Invalid Input", "Please enter a server URL.", parent=dialog)
                return
            
            self.device_name = name
            self.server_url = server
            dialog.destroy()
            root.quit()
        
        def on_cancel():
            dialog.destroy()
            root.quit()
        
        ok_button = tk.Button(
            button_frame,
            text="✓ Start Agent",
            command=on_ok,
            bg="#10b981",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=15,
            relief="flat",
            cursor="hand2"
        )
        ok_button.grid(row=0, column=0, padx=5)
        
        cancel_button = tk.Button(
            button_frame,
            text="✗ Cancel",
            command=on_cancel,
            bg="#ef4444",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=15,
            relief="flat",
            cursor="hand2"
        )
        cancel_button.grid(row=0, column=1, padx=5)
        
        dialog.bind('<Return>', lambda e: on_ok())
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        
        root.mainloop()
        
        try:
            root.destroy()
        except:
            pass
        
        return self.device_name, self.server_url

def get_device_name_gui():
    """Get device name via GUI popup (only on first run)"""
    # Try to load saved configuration
    saved_name, saved_server = load_config()

    # If configuration exists, use it directly without showing dialog
    if saved_name and saved_server:
        print(f"✅ Using saved configuration")
        print(f"   Device Name: {saved_name}")
        print(f"   Server URL: {saved_server}")
        print()
        return saved_name, saved_server

    # First run - show configuration dialog
    print("⚠️  No saved configuration found - showing setup dialog")

    if DEVICE_NAME and DEVICE_NAME != "Branch01":
        return DEVICE_NAME, SERVER_URL

    try:
        dialog = DeviceNameDialog()
        device_name, server_url = dialog.show_dialog(saved_name, saved_server)

        if device_name and server_url:
            save_config(device_name, server_url)
            return device_name, server_url
        else:
            return None, None

    except Exception as e:
        print(f"⚠️  GUI not available: {e}")
        return None, None

# ==================== SYSTEM TRAY ICON ====================

def create_tray_icon(count, online):
    """Create a system tray icon with heartbeat count"""
    # Create a 64x64 image
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw circle background
    color = (16, 185, 129) if online else (239, 68, 68)  # Green if online, red if offline
    draw.ellipse([4, 4, 60, 60], fill=color)
    
    # Draw heartbeat count
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except:
        font = ImageFont.load_default()
    
    text = str(count) if count < 999 else "999+"
    
    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    position = ((64 - text_width) // 2, (64 - text_height) // 2 - 2)
    draw.text(position, text, fill=(255, 255, 255), font=font)
    
    return img

def update_tray_icon():
    """Update the system tray icon"""
    global tray_icon, heartbeat_count, is_online
    
    if tray_icon:
        icon_image = create_tray_icon(heartbeat_count, is_online)
        tray_icon.icon = icon_image
        
        # Update tooltip
        status = "🟢 ONLINE" if is_online else "🔴 OFFLINE"
        tray_icon.title = f"{device_name_global}\n{status}\nHeartbeats: {heartbeat_count}"

def show_status():
    """Show status window"""
    status = "🟢 ONLINE" if is_online else "🔴 OFFLINE"

    # Use a simple notification instead of tkinter dialog
    message = (
        f"Device: {device_name_global}\n"
        f"Status: {status}\n"
        f"Total Heartbeats: {heartbeat_count}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # Show notification using pystray's notification system
    if tray_icon:
        tray_icon.notify(message, "Heartbeat Agent Status")

def change_device_name(icon, item):
    """Change device name using PowerShell input dialog"""
    global device_name_global

    try:
        old_name = device_name_global

        # Use PowerShell for Windows native input dialog
        ps_script = f'''
Add-Type -AssemblyName Microsoft.VisualBasic
$newName = [Microsoft.VisualBasic.Interaction]::InputBox("Enter new device name:", "Change Device Name", "{device_name_global}")
Write-Output $newName
'''

        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        new_name = result.stdout.strip()

        if new_name and new_name != device_name_global:
            device_name_global = new_name

            # Save to config
            _, server_url = load_config()
            save_config(new_name, server_url)

            # Update tray icon tooltip
            update_tray_icon()

            # Print to console
            print("\n")
            print("=" * 80)
            print("✅ DEVICE NAME CHANGED")
            print("=" * 80)
            print(f"Old Name: {old_name}")
            print(f"New Name: {new_name}")
            print()
            print("This change will take effect on the next heartbeat.")
            print("=" * 80)
            print()
            print("📊 Live Status:")
            print("-" * 80)

            # Show notification
            if tray_icon:
                tray_icon.notify(
                    f"Device name changed to: {new_name}\n\nThis will take effect on the next heartbeat.",
                    "Success"
                )
    except Exception:
        pass  # Silent failure

def exit_app(icon, item):
    """Exit the application"""
    global tray_icon, shutdown_event

    # Signal shutdown to the heartbeat loop
    shutdown_event.set()

    # Clean up lock file
    cleanup_lock_file()

    # Stop the tray icon gracefully
    if icon:
        try:
            icon.visible = False
            icon.stop()
        except:
            pass

    # Give it a moment to cleanup
    time.sleep(1)

    # Force exit to ensure all threads are killed
    os._exit(0)

def setup_tray_icon(device_name):
    """Setup system tray icon"""
    global tray_icon, device_name_global
    device_name_global = device_name
    
    icon_image = create_tray_icon(0, False)
    
    menu = pystray.Menu(
        item('Status', show_status),
        item('Change Name', change_device_name),
        item('Exit', exit_app)
    )
    
    tray_icon = pystray.Icon(
        "heartbeat_agent",
        icon_image,
        f"{device_name}\nStarting...",
        menu
    )
    
    # Run in separate thread
    threading.Thread(target=tray_icon.run, daemon=True).start()

# ==================== HEARTBEAT LOGIC ====================

def send_heartbeat(server_url, device_name):
    """Send heartbeat POST request to server"""
    global heartbeat_count, is_online, device_name_global
    
    # Use the current global device name (in case it was changed)
    current_device_name = device_name_global if device_name_global else device_name
    
    # Get MAC address
    mac_address = get_mac_address()
    
    try:
        payload = {
            "device_name": current_device_name,
            "timestamp": datetime.now().isoformat(),
            "mac_address": mac_address
        }
        
        response = requests.post(
            server_url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            data = response.json()
            heartbeat_count += 1
            is_online = True
            update_tray_icon()
            return True, None
        else:
            is_online = False
            update_tray_icon()
            error_msg = f"Server returned status {response.status_code}"
            return False, error_msg

    except requests.exceptions.ConnectionError:
        is_online = False
        update_tray_icon()
        error_msg = "Connection failed - server unreachable"
        return False, error_msg
        
    except requests.exceptions.Timeout:
        is_online = False
        update_tray_icon()
        error_msg = "Request timeout"
        return False, error_msg

    except Exception as e:
        is_online = False
        update_tray_icon()
        error_msg = f"Unexpected error: {str(e)}"
        return False, error_msg

def send_heartbeat_with_retry(server_url, device_name, max_retries=MAX_RETRIES):
    """Send heartbeat with exponential backoff retry logic"""
    retry_delay = INITIAL_RETRY_DELAY
    
    for attempt in range(1, max_retries + 1):
        success, error = send_heartbeat(server_url, device_name)
        
        if success:
            return True
        
        if attempt < max_retries:
            # Retry with exponential backoff
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

    # Failed after all retries
    return False

def run_heartbeat_agent(server_url, device_name):
    """Main loop that sends heartbeats at regular intervals"""
    global shutdown_event

    # Setup system tray icon
    setup_tray_icon(device_name)
    time.sleep(1)  # Give tray icon time to initialize

    consecutive_failures = 0

    while not shutdown_event.is_set():
        try:
            # Print live status to console
            print_status_line()

            success = send_heartbeat_with_retry(server_url, device_name)

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

                if consecutive_failures >= 5:
                    # Too many failures, wait longer
                    shutdown_event.wait(MAX_RETRY_DELAY)
                    continue

            # Print updated status after heartbeat
            print_status_line()

            # Use wait() instead of sleep() so shutdown can interrupt it
            shutdown_event.wait(HEARTBEAT_INTERVAL)

        except KeyboardInterrupt:
            # User stopped the agent
            if tray_icon:
                try:
                    tray_icon.stop()
                except:
                    pass
            cleanup_lock_file()
            os._exit(0)

        except Exception:
            # Error occurred, wait and retry
            shutdown_event.wait(HEARTBEAT_INTERVAL)

    # Heartbeat loop terminated

# ==================== CONSOLE UI ====================

def print_banner():
    """Print console banner with warning"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 80)
    print("██╗  ██╗███████╗ █████╗ ██████╗ ████████╗██████╗ ███████╗ █████╗ ████████╗")
    print("██║  ██║██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔════╝██╔══██╗╚══██╔══╝")
    print("███████║█████╗  ███████║██████╔╝   ██║   ██████╔╝█████╗  ███████║   ██║   ")
    print("██╔══██║██╔══╝  ██╔══██║██╔══██╗   ██║   ██╔══██╗██╔══╝  ██╔══██║   ██║   ")
    print("██║  ██║███████╗██║  ██║██║  ██║   ██║   ██████╔╝███████╗██║  ██║   ██║   ")
    print("╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝   ")
    print("=" * 80)
    print()
    print("⚠️  WARNING: DO NOT CLOSE THIS WINDOW! ⚠️")
    print("⚠️  Closing this window will stop the Heartbeat Agent! ⚠️")
    print()
    print("=" * 80)
    print()

def print_status_line():
    """Print current status on console"""
    status_symbol = "🟢" if is_online else "🔴"
    status_text = "ONLINE " if is_online else "OFFLINE"

    # Clear the line and print status
    print(f"\r[{datetime.now().strftime('%H:%M:%S')}] {status_symbol} {status_text} | Device: {device_name_global} | Heartbeats: {heartbeat_count}          ", end='', flush=True)

def console_monitor_thread():
    """Thread to monitor console input for exit command"""
    global shutdown_event

    print("💡 To exit the agent, type 'close' and press Enter")
    print()
    print("📊 Live Status:")
    print("-" * 80)

    while not shutdown_event.is_set():
        try:
            # Use select-like behavior for input with timeout
            if sys.stdin in select.select([sys.stdin], [], [], 1)[0]:
                user_input = sys.stdin.readline().strip().lower()

                if user_input == 'close':
                    print("\n")
                    print("=" * 80)
                    confirm = input("⚠️  Type 'YES' to confirm shutdown: ").strip().upper()

                    if confirm == 'YES':
                        print()
                        print("🛑 Shutting down Heartbeat Agent...")
                        shutdown_event.set()

                        # Stop tray icon
                        if tray_icon:
                            try:
                                tray_icon.stop()
                            except:
                                pass

                        cleanup_lock_file()
                        print("✓ Shutdown complete!")
                        time.sleep(1)
                        os._exit(0)
                    else:
                        print()
                        print("❌ Shutdown cancelled. Agent continues running.")
                        print()
                        print("📊 Live Status:")
                        print("-" * 80)
                elif user_input == 'status':
                    print("\n")
                    print("=" * 80)
                    print(f"📊 STATUS REPORT")
                    print("=" * 80)
                    print(f"Device Name      : {device_name_global}")
                    print(f"Status           : {'🟢 ONLINE' if is_online else '🔴 OFFLINE'}")
                    print(f"Total Heartbeats : {heartbeat_count:,}")
                    print(f"Current Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print("=" * 80)
                    print()
                    print("📊 Live Status:")
                    print("-" * 80)
                elif user_input == 'help':
                    print("\n")
                    print("=" * 80)
                    print("📖 AVAILABLE COMMANDS")
                    print("=" * 80)
                    print("status  - Show detailed status report")
                    print("help    - Show this help message")
                    print("close   - Exit the Heartbeat Agent (requires confirmation)")
                    print("=" * 80)
                    print()
                    print("📊 Live Status:")
                    print("-" * 80)
                elif user_input:
                    print(f"\n❓ Unknown command: '{user_input}'. Type 'help' for available commands.\n")
        except:
            time.sleep(0.5)

# ==================== CONSOLE CLOSE HANDLER ====================

# Global variable to store the original window procedure
_original_wndproc = None
_close_handler_callback = None  # Keep reference to prevent garbage collection

def setup_console_close_handler():
    """Setup handler for console window close button (X button)

    Shows a Windows MessageBox confirmation dialog when X button is clicked.
    Uses SetConsoleCtrlHandler which works reliably with PyInstaller.
    """
    if sys.platform != 'win32':
        return False

    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # Windows API constants
        CTRL_CLOSE_EVENT = 2
        MB_YESNO = 0x00000004
        MB_ICONWARNING = 0x00000030
        MB_SYSTEMMODAL = 0x00001000
        IDYES = 6

        def console_close_handler(event_type):
            """Handler called when user clicks X button"""
            global shutdown_event, tray_icon

            # Only handle close button (X button)
            if event_type == CTRL_CLOSE_EVENT:
                # Get console window handle for MessageBox parent
                hwnd = kernel32.GetConsoleWindow()

                # Show Windows MessageBox (native, no tkinter needed)
                result = user32.MessageBoxW(
                    hwnd,
                    "⚠️  Closing this window will STOP the Heartbeat Agent!\n\n"
                    "Are you sure you want to exit?\n\n"
                    "💡 Tip: Use the system tray icon to exit instead,\n"
                    "or type 'close' in the console for a safer exit.",
                    "Confirm Exit - Heartbeat Agent",
                    MB_YESNO | MB_ICONWARNING | MB_SYSTEMMODAL
                )

                if result == IDYES:
                    # User clicked YES - exit normally
                    print("\n")
                    print("=" * 80)
                    print("🛑 Shutting down Heartbeat Agent...")
                    print("=" * 80)

                    shutdown_event.set()

                    # Stop tray icon
                    if tray_icon:
                        try:
                            tray_icon.stop()
                        except:
                            pass

                    cleanup_lock_file()
                    print("✓ Shutdown complete!")
                    time.sleep(1)
                    os._exit(0)
                else:
                    # User clicked NO - RELAUNCH THE EXE BEFORE CLOSING!
                    # This is a workaround because SetConsoleCtrlHandler doesn't prevent
                    # the close in PyInstaller executables
                    print("\n")
                    print("=" * 80)
                    print("✅ EXIT CANCELLED - RESTARTING...")
                    print("=" * 80)

                    try:
                        # Check if we're running as frozen executable
                        is_frozen = getattr(sys, 'frozen', False)

                        if is_frozen:
                            # Get absolute path to the executable
                            import os
                            exe_path = os.path.abspath(sys.executable)
                            print(f"Relaunching: {exe_path}")

                            # CRITICAL: Remove the lock file so new instance can start
                            try:
                                cleanup_lock_file()
                                print("✓ Lock file removed")
                            except Exception as e:
                                print(f"⚠️  Error removing lock file: {e}")

                            # Use Windows API CreateProcess for more reliable detached launch
                            import subprocess

                            # Use shell=True with 'start' command - most reliable way on Windows
                            # The 'start' command creates a truly independent process
                            try:
                                subprocess.Popen(
                                    f'start "" "{exe_path}"',
                                    shell=True,
                                    cwd=os.path.dirname(exe_path)
                                )
                                print(f"✓ New instance launched via 'start' command")
                                time.sleep(1)  # Brief delay to let it start
                            except Exception as sub_e:
                                print(f"⚠️  Launch failed: {sub_e}")
                                import traceback
                                traceback.print_exc()

                            print("✓ New window should appear now. This window will close...")
                        else:
                            print("⚠️  Not running as frozen executable - cannot restart")
                            time.sleep(2)
                    except Exception as e:
                        print(f"⚠️  Error restarting: {e}")
                        import traceback
                        traceback.print_exc()
                        print("Please manually restart the application.")
                        time.sleep(3)

                # Since we can't actually prevent the close in PyInstaller,
                # we've relaunched a new instance if user clicked NO
                # Return 1 anyway (though it won't prevent close in PyInstaller)
                return 1

            # For other events (Ctrl+C, etc), return 0 to allow default behavior
            return 0

        # Set the console control handler
        HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        handler_func = HandlerRoutine(console_close_handler)

        # Keep reference to prevent garbage collection
        global _close_handler_callback
        _close_handler_callback = handler_func

        result = kernel32.SetConsoleCtrlHandler(handler_func, 1)

        if result:
            print("✓ Console close handler installed (X button will show confirmation dialog)")
            return True
        else:
            print("⚠️  Could not install console close handler")
            return False

    except Exception as e:
        print(f"⚠️  Could not set console close handler: {e}")
        import traceback
        traceback.print_exc()
        return False


def setup_console_close_handler_OLD_COMPLEX():
    """OLD COMPLEX VERSION - This didn't work with PyInstaller

    Kept for reference in case we want to try again later.
    """
    if sys.platform != 'win32':
        return False

    is_frozen = getattr(sys, 'frozen', False)

    try:
        # Windows API constants
        CTRL_CLOSE_EVENT = 2
        CTRL_C_EVENT = 0
        CTRL_BREAK_EVENT = 1

        # Track if we're showing a dialog to prevent multiple dialogs
        _showing_dialog = threading.Lock()

        def console_close_handler(event_type):
            """Handler called when user tries to close console window"""
            global shutdown_event, tray_icon

            # Debug logging
            print(f"\n[DEBUG] Close handler triggered! event_type={event_type}")
            print(f"[DEBUG] CTRL_CLOSE_EVENT={CTRL_CLOSE_EVENT}")

            try:
                # Only handle close button (X button)
                if event_type == CTRL_CLOSE_EVENT:
                    print(f"[DEBUG] X button detected! Attempting to show dialog...")
                    # Try to acquire the lock - if we can't, a dialog is already showing
                    if not _showing_dialog.acquire(blocking=False):
                        return 1  # Already showing dialog, prevent close

                    try:
                        # CRITICAL: We must return 1 (True) IMMEDIATELY to prevent Windows from closing
                        # Then we handle the dialog in a separate thread

                        def show_exit_dialog():
                            """Show exit confirmation dialog in a separate thread"""
                            global shutdown_event, tray_icon

                            try:
                                print(f"[DEBUG] Dialog thread started...")
                                # Small delay to ensure handler has returned
                                time.sleep(0.1)

                                print(f"[DEBUG] Creating tkinter window...")
                                # Show confirmation dialog
                                root = tk.Tk()
                                root.withdraw()
                                root.attributes('-topmost', True)
                                root.lift()
                                root.focus_force()

                                print(f"[DEBUG] Showing messagebox...")
                                response = messagebox.askyesno(
                                    "Confirm Exit",
                                    "⚠️  Closing this window will STOP the Heartbeat Agent!\n\n"
                                    "Are you sure you want to exit?\n\n"
                                    "💡 Tip: Use the system tray icon to exit instead,\n"
                                    "or type 'close' in the console for a safer exit.",
                                    icon='warning'
                                )

                                print(f"[DEBUG] Dialog closed. User response: {response}")
                                root.destroy()

                                if response:
                                    # User confirmed exit
                                    print("\n")
                                    print("=" * 80)
                                    print("🛑 Shutting down Heartbeat Agent...")
                                    print("=" * 80)

                                    shutdown_event.set()

                                    # Stop tray icon
                                    if tray_icon:
                                        try:
                                            tray_icon.stop()
                                        except:
                                            pass

                                    cleanup_lock_file()
                                    print("✓ Shutdown complete!")
                                    time.sleep(1)
                                    os._exit(0)
                                else:
                                    # User cancelled - continue running
                                    print("\n")
                                    print("=" * 80)
                                    print("✅ EXIT CANCELLED")
                                    print("=" * 80)
                                    print("The Heartbeat Agent will continue running.")
                                    print()
                                    print("📊 Live Status:")
                                    print("-" * 80)
                            except Exception as e:
                                # If dialog fails, just print error and continue running
                                print(f"\n⚠️  Error showing exit dialog: {e}")
                                print("Agent will continue running. Use 'close' command to exit safely.")
                                print()
                            finally:
                                # Always release the lock
                                _showing_dialog.release()

                        # Start dialog in a separate thread
                        print(f"[DEBUG] Starting dialog thread...")
                        dialog_thread = threading.Thread(target=show_exit_dialog, daemon=False)
                        dialog_thread.start()
                        print(f"[DEBUG] Dialog thread started, returning 1 to prevent close")

                        # ALWAYS return 1 (True) to tell Windows we handled it and prevent the close
                        return 1
                    except:
                        _showing_dialog.release()
                        return 1

                # For Ctrl+C and Ctrl+Break, let them through (return 0)
                elif event_type == CTRL_C_EVENT or event_type == CTRL_BREAK_EVENT:
                    return 0

                # For other events, prevent close
                return 1

            except Exception as e:
                # If anything fails, prevent the close by default
                print(f"\n⚠️  Error in close handler: {e}")
                return 1

        # Try BOTH methods: SetConsoleCtrlHandler AND Window Procedure Hook
        print(f"[DEBUG] Setting up console close handler...")
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # METHOD 1: SetConsoleCtrlHandler
        # Define the handler function type
        HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        handler_func = HandlerRoutine(console_close_handler)
        print(f"[DEBUG] Handler function created: {handler_func}")

        # Set the console control handler
        print(f"[DEBUG] Calling SetConsoleCtrlHandler...")
        result = kernel32.SetConsoleCtrlHandler(handler_func, 1)
        print(f"[DEBUG] SetConsoleCtrlHandler result: {result} (1=success, 0=failure)")

        # METHOD 2: Window Procedure Hook (for PyInstaller compatibility)
        hwnd = kernel32.GetConsoleWindow()
        print(f"[DEBUG] Console window handle: {hwnd}")

        if hwnd:
            # Define window procedure callback
            WM_CLOSE = 0x0010
            WM_QUERYENDSESSION = 0x0011
            GWLP_WNDPROC = -4

            # Window procedure function type
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM
            )

            def window_proc(hwnd, msg, wparam, lparam):
                """Custom window procedure to intercept close messages"""
                global _original_wndproc

                # Only log close-related messages to avoid spam
                if msg == WM_CLOSE or msg == WM_QUERYENDSESSION:
                    print(f"[DEBUG] Window message received: {msg} (WM_CLOSE={WM_CLOSE})")

                if msg == WM_CLOSE:
                    print(f"[DEBUG] WM_CLOSE detected! Showing confirmation dialog...")
                    # Call the same close handler
                    console_close_handler(CTRL_CLOSE_EVENT)
                    # Don't pass to original - we handled it
                    return 0

                if msg == WM_QUERYENDSESSION:
                    print(f"[DEBUG] WM_QUERYENDSESSION detected!")
                    # Windows is shutting down - allow it
                    return 1

                # Pass all other messages to original window procedure
                if _original_wndproc:
                    return user32.CallWindowProcW(_original_wndproc, hwnd, msg, wparam, lparam)
                return 0

            # Create the callback
            new_wndproc = WNDPROC(window_proc)
            print(f"[DEBUG] New window procedure callback created: {new_wndproc}")

            # Subclass the window
            print(f"[DEBUG] Hooking window procedure...")
            global _original_wndproc

            # For 64-bit, we need to use LONG_PTR type instead of regular int
            import platform
            is_64bit = platform.architecture()[0] == '64bit'

            if is_64bit:
                # 64-bit: SetWindowLongPtrW with LONG_PTR (which is c_int64 on 64-bit)
                # Define the correct function signature
                LONG_PTR = ctypes.c_int64
                user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
                user32.SetWindowLongPtrW.restype = LONG_PTR

                # Cast the callback to LONG_PTR
                new_wndproc_ptr = ctypes.cast(new_wndproc, ctypes.c_void_p).value
                print(f"[DEBUG] New window procedure pointer (64-bit): {hex(new_wndproc_ptr)}")

                _original_wndproc = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, new_wndproc_ptr)
            else:
                # 32-bit: SetWindowLongW with regular LONG
                user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
                user32.SetWindowLongW.restype = wintypes.LONG

                new_wndproc_ptr = ctypes.cast(new_wndproc, ctypes.c_void_p).value
                print(f"[DEBUG] New window procedure pointer (32-bit): {hex(new_wndproc_ptr)}")

                _original_wndproc = user32.SetWindowLongW(hwnd, GWLP_WNDPROC, new_wndproc_ptr)

            print(f"[DEBUG] Original window procedure: {hex(_original_wndproc) if _original_wndproc else '0x0'}")

            # Check for error
            if _original_wndproc == 0:
                error_code = kernel32.GetLastError()
                print(f"[DEBUG] ⚠️ SetWindowLong failed with error code: {error_code}")

            if _original_wndproc:
                # Keep reference to prevent garbage collection
                global _console_handler_ref
                _console_handler_ref = (handler_func, new_wndproc)
                print(f"[DEBUG] ✓ Window procedure hook installed successfully!")
                result = True
            else:
                print(f"[DEBUG] ✗ Failed to hook window procedure")

        print(f"[DEBUG] Final setup result: {result}")

        if result:
            if not is_frozen:
                # Running as Python script - warn user that close handler is limited
                return "limited"

            return True
        else:
            return False

    except Exception as e:
        print(f"⚠️  Could not set console close handler: {e}")
        import traceback
        traceback.print_exc()
        return False

# ==================== MAIN ====================

if __name__ == "__main__":
    # Import select for input monitoring (Windows compatible)
    try:
        import select
    except ImportError:
        # Windows doesn't have select for stdin, use msvcrt instead
        import msvcrt

        # Override console_monitor_thread for Windows
        def console_monitor_thread():
            """Thread to monitor console input for exit command (Windows version)"""
            global shutdown_event

            print("💡 To exit the agent, type 'close' and press Enter")
            print()
            print("📊 Live Status:")
            print("-" * 80)

            while not shutdown_event.is_set():
                try:
                    # Check if input is available
                    if msvcrt.kbhit():
                        # Read the full line
                        user_input = input().strip().lower()

                        if user_input == 'close':
                            print("\n")
                            print("=" * 80)
                            confirm = input("⚠️  Type 'YES' to confirm shutdown: ").strip().upper()

                            if confirm == 'YES':
                                print()
                                print("🛑 Shutting down Heartbeat Agent...")
                                shutdown_event.set()

                                # Stop tray icon
                                if tray_icon:
                                    try:
                                        tray_icon.stop()
                                    except:
                                        pass

                                cleanup_lock_file()
                                print("✓ Shutdown complete!")
                                time.sleep(1)
                                os._exit(0)
                            else:
                                print()
                                print("❌ Shutdown cancelled. Agent continues running.")
                                print()
                                print("📊 Live Status:")
                                print("-" * 80)
                        elif user_input == 'status':
                            print("\n")
                            print("=" * 80)
                            print(f"📊 STATUS REPORT")
                            print("=" * 80)
                            print(f"Device Name      : {device_name_global}")
                            print(f"Status           : {'🟢 ONLINE' if is_online else '🔴 OFFLINE'}")
                            print(f"Total Heartbeats : {heartbeat_count:,}")
                            print(f"Current Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                            print("=" * 80)
                            print()
                            print("📊 Live Status:")
                            print("-" * 80)
                        elif user_input == 'help':
                            print("\n")
                            print("=" * 80)
                            print("📖 AVAILABLE COMMANDS")
                            print("=" * 80)
                            print("status  - Show detailed status report")
                            print("help    - Show this help message")
                            print("close   - Exit the Heartbeat Agent (requires confirmation)")
                            print("=" * 80)
                            print()
                            print("📊 Live Status:")
                            print("-" * 80)
                        elif user_input:
                            print(f"\n❓ Unknown command: '{user_input}'. Type 'help' for available commands.\n")
                    else:
                        time.sleep(0.1)
                except:
                    time.sleep(0.5)

    # Print banner
    print_banner()

    # Setup console close handler (X button confirmation)
    handler_result = setup_console_close_handler()

    # Debug: Check if we're running as frozen executable
    is_frozen = getattr(sys, 'frozen', False)
    print(f"Debug: Running as {'EXE (frozen)' if is_frozen else 'Python script'}")

    if handler_result == True:
        print("✓ Console close handler installed successfully")
        print("  → Click the X button to test - you should see a confirmation dialog")
    elif handler_result == "limited":
        print("⚠️  Console close handler has limited functionality when running as Python script")
        print("   For full protection, use the compiled EXE (dist\\HeartbeatAgent.exe)")
    else:
        print("⚠️  Console close handler could not be installed")
    print()

    # Check for single instance
    if not check_single_instance():
        print("❌ ERROR: Heartbeat Agent is already running!")
        print()
        print("Check your system tray for the heartbeat icon.")
        print("If you don't see it, the previous instance may have crashed.")
        print("Restart your computer or end the process in Task Manager.")
        print()
        input("Press Enter to exit...")
        sys.exit(1)

    print("✓ Single instance check passed")
    print()

    # Get device name and server URL (from config or GUI on first run)
    device_name, server_url = get_device_name_gui()

    if not device_name or not server_url:
        # Configuration required to start agent
        print("❌ Configuration cancelled or incomplete")
        cleanup_lock_file()
        input("Press Enter to exit...")
        sys.exit(1)

    print("🚀 Starting Heartbeat Agent...")
    time.sleep(1)

    # Start console monitor thread
    monitor_thread = threading.Thread(target=console_monitor_thread, daemon=True)
    monitor_thread.start()

    # Run the agent
    run_heartbeat_agent(server_url, device_name)
