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
import tkinter as tk
from tkinter import messagebox, simpledialog
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item
import tempfile
import atexit
import uuid

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

# Configuration file path
CONFIG_FILE = "heartbeat_config.json"

# Global variables for system tray
heartbeat_count = 0
is_online = False
tray_icon = None
device_name_global = ""

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
        print(f"✅ Configuration saved to {CONFIG_FILE}")
        return True
    except Exception as e:
        print(f"⚠️  Could not save config file: {e}")
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
    """Get device name via GUI popup"""
    saved_name, saved_server = load_config()
    
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

    # Create a temporary root window
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    try:
        messagebox.showinfo(
            "Heartbeat Agent Status",
            f"Device: {device_name_global}\n"
            f"Status: {status}\n"
            f"Total Heartbeats: {heartbeat_count}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parent=root
        )
    finally:
        # Ensure proper cleanup
        try:
            root.quit()
        except:
            pass
        try:
            root.destroy()
        except:
            pass

def change_device_name(icon, item):
    """Change device name"""
    global device_name_global

    root = tk.Tk()
    root.withdraw()

    try:
        new_name = simpledialog.askstring(
            "Change Device Name",
            f"Current name: {device_name_global}\n\nEnter new device name:",
            initialvalue=device_name_global,
            parent=root
        )

        if new_name and new_name.strip():
            new_name = new_name.strip()
            device_name_global = new_name

            # Save to config
            _, server_url = load_config()
            save_config(new_name, server_url)

            # Update tray icon tooltip
            update_tray_icon()

            messagebox.showinfo(
                "Success",
                f"Device name changed to: {new_name}\n\nThis will take effect on the next heartbeat.",
                parent=root
            )
    finally:
        # Ensure proper cleanup
        try:
            root.quit()
        except:
            pass
        try:
            root.destroy()
        except:
            pass

def exit_app(icon, item):
    """Exit the application"""
    global tray_icon
    print("\n🛑 Stopping heartbeat agent...")

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
    time.sleep(0.5)

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
            print(f"✅ Heartbeat #{heartbeat_count} sent | Device: {current_device_name} | {datetime.now().strftime('%H:%M:%S')}")
            return True, None
        else:
            is_online = False
            update_tray_icon()
            error_msg = f"Server returned status {response.status_code}"
            print(f"⚠️  {error_msg}")
            return False, error_msg
            
    except requests.exceptions.ConnectionError:
        is_online = False
        update_tray_icon()
        error_msg = "Connection failed - server unreachable"
        print(f"❌ {error_msg}")
        return False, error_msg
        
    except requests.exceptions.Timeout:
        is_online = False
        update_tray_icon()
        error_msg = "Request timeout"
        print(f"❌ {error_msg}")
        return False, error_msg
        
    except Exception as e:
        is_online = False
        update_tray_icon()
        error_msg = f"Unexpected error: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg

def send_heartbeat_with_retry(server_url, device_name, max_retries=MAX_RETRIES):
    """Send heartbeat with exponential backoff retry logic"""
    retry_delay = INITIAL_RETRY_DELAY
    
    for attempt in range(1, max_retries + 1):
        success, error = send_heartbeat(server_url, device_name)
        
        if success:
            return True
        
        if attempt < max_retries:
            print(f"🔄 Retry {attempt}/{max_retries} in {retry_delay} seconds...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
    
    print(f"❌ Failed to send heartbeat after {max_retries} attempts")
    return False

def run_heartbeat_agent(server_url, device_name):
    """Main loop that sends heartbeats at regular intervals"""
    
    print("=" * 60)
    print("🚀 PC Heartbeat Client Agent Started")
    print("=" * 60)
    print(f"📱 Device Name: {device_name}")
    print(f"🌐 Server URL: {server_url}")
    print(f"⏰ Heartbeat Interval: {HEARTBEAT_INTERVAL} seconds")
    print(f"🔄 Max Retries: {MAX_RETRIES}")
    print(f"📊 System Tray: Enabled (check taskbar)")
    print("=" * 60)
    print("Press Ctrl+C to stop\n")
    
    # Setup system tray icon
    setup_tray_icon(device_name)
    time.sleep(1)  # Give tray icon time to initialize
    
    consecutive_failures = 0
    
    while True:
        try:
            success = send_heartbeat_with_retry(server_url, device_name)
            
            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                print(f"⚠️  Consecutive failures: {consecutive_failures}")
                
                if consecutive_failures >= 5:
                    print(f"⚠️  Too many failures. Waiting {MAX_RETRY_DELAY} seconds...")
                    time.sleep(MAX_RETRY_DELAY)
                    continue
            
            time.sleep(HEARTBEAT_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Heartbeat agent stopped by user")
            if tray_icon:
                try:
                    tray_icon.stop()
                except:
                    pass
            cleanup_lock_file()
            print("=" * 60)
            os._exit(0)
            
        except Exception as e:
            print(f"❌ Unexpected error in main loop: {str(e)}")
            time.sleep(HEARTBEAT_INTERVAL)

# ==================== MAIN ====================

if __name__ == "__main__":
    # Check for single instance
    if not check_single_instance():
        messagebox.showerror(
            "Already Running",
            "Heartbeat Agent is already running!\n\n"
            "Check your system tray for the heartbeat icon.\n\n"
            "If you don't see it, the previous instance may have crashed.\n"
            "Restart your computer or end the process in Task Manager."
        )
        sys.exit(1)
    
    # Get device name and server URL via GUI
    device_name, server_url = get_device_name_gui()
    
    if not device_name or not server_url:
        print("❌ Configuration required to start agent")
        cleanup_lock_file()
        sys.exit(1)
    
    # Run the agent
    run_heartbeat_agent(server_url, device_name)
