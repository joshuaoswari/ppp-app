"""
PC Heartbeat Client Agent v2.0 - Background Service
====================================================
Complete background service with NO console window.
Only visible through system tray icon.

New in v2.0:
- No console window at all
- Runs completely in background
- Only system tray icon visible
- File-based logging
- GUI settings window on demand
- Status viewer window on demand
- Doesn't appear in taskbar
- Auto-start friendly
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
from tkinter import messagebox, simpledialog, ttk, scrolledtext
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item
import tempfile
import atexit
import uuid
import logging
from logging.handlers import RotatingFileHandler

# ==================== LOGGING SETUP ====================

def setup_logging():
    """Setup file-based logging since we have no console"""
    if sys.platform == 'win32':
        appdata = os.getenv('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        log_dir = os.path.join(appdata, 'HeartbeatAgent', 'logs')
    else:
        log_dir = os.path.expanduser('~/.heartbeat/logs')

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'heartbeat.log')

    # Create logger
    logger = logging.getLogger('HeartbeatAgent')
    logger.setLevel(logging.INFO)

    # Rotating file handler (max 5MB, keep 3 backups)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3
    )

    # Format
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

logger = setup_logging()

# ==================== SINGLE INSTANCE LOCK ====================

def get_lock_file_path():
    """Get lock file path"""
    if sys.platform == 'win32':
        appdata = os.getenv('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        return os.path.join(appdata, 'HeartbeatAgent', 'agent.lock')
    else:
        return os.path.join(tempfile.gettempdir(), 'heartbeat_agent.lock')

LOCK_FILE = get_lock_file_path()

def check_single_instance():
    """Ensure only one instance of the agent is running"""
    lock_dir = os.path.dirname(LOCK_FILE)
    os.makedirs(lock_dir, exist_ok=True)

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())

            # Check if process is still running
            try:
                import psutil
                if psutil.pid_exists(pid):
                    logger.warning(f"Another instance is already running (PID: {pid})")
                    return False
            except ImportError:
                # If psutil not available, assume process is running
                logger.warning("Lock file exists, assuming another instance is running")
                return False
        except Exception as e:
            logger.warning(f"Lock file corrupted: {e}, removing it")
            try:
                os.remove(LOCK_FILE)
            except:
                pass

    # Create lock file
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Lock file created: {LOCK_FILE}")
    except Exception as e:
        logger.error(f"Failed to create lock file: {e}")
        return False

    # Register cleanup on exit
    atexit.register(cleanup_lock_file)

    return True

def cleanup_lock_file():
    """Remove lock file on exit"""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock file removed")
    except Exception as e:
        logger.error(f"Failed to remove lock file: {e}")

# ==================== CONFIGURATION ====================

def get_config_path():
    """Get the configuration file path"""
    if sys.platform == 'win32':
        appdata = os.getenv('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        config_dir = os.path.join(appdata, 'HeartbeatAgent')
    else:
        config_dir = os.path.expanduser('~/.heartbeat')

    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'config.json')

CONFIG_FILE = get_config_path()

# Default configuration
DEFAULT_CONFIG = {
    'server_url': 'https://ppp-app-production-8aa2.up.railway.app',
    'device_name': None,
    'heartbeat_interval': 10,
    'max_retries': 3
}

def load_config():
    """Load configuration from file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                logger.info(f"Configuration loaded from {CONFIG_FILE}")
                return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")

    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        logger.info(f"Configuration saved to {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False

# ==================== MAC ADDRESS ====================

def get_mac_address():
    """Get the MAC address of the device"""
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff)
                       for ele in range(0,8*6,8)][::-1])
        return mac
    except Exception as e:
        logger.error(f"Failed to get MAC address: {e}")
        return "unknown"

# ==================== HEARTBEAT AGENT ====================

class HeartbeatAgent:
    def __init__(self):
        self.config = load_config()
        self.running = False
        self.heartbeat_thread = None
        self.heartbeat_count = 0
        self.last_success = None
        self.last_error = None
        self.tray_icon = None
        self.mac_address = get_mac_address()

        logger.info("=" * 60)
        logger.info("Heartbeat Agent v2.0 Starting")
        logger.info("=" * 60)
        logger.info(f"MAC Address: {self.mac_address}")
        logger.info(f"Config file: {CONFIG_FILE}")
        logger.info(f"Log file: {os.path.dirname(logger.handlers[0].baseFilename)}")

    def send_heartbeat(self):
        """Send heartbeat to server"""
        device_name = self.config.get('device_name')
        if not device_name:
            logger.error("Device name not configured")
            return False

        server_url = self.config.get('server_url', '').rstrip('/')
        if not server_url:
            logger.error("Server URL not configured")
            return False

        try:
            data = {
                'device_name': device_name,
                'mac_address': self.mac_address,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            response = requests.post(
                f"{server_url}/heartbeat",
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                self.heartbeat_count += 1
                self.last_success = datetime.now()
                self.last_error = None
                logger.info(f"Heartbeat #{self.heartbeat_count} sent successfully")
                return True
            else:
                error_msg = f"Server returned status {response.status_code}"
                self.last_error = error_msg
                logger.error(error_msg)
                return False

        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False

    def heartbeat_loop(self):
        """Main heartbeat loop"""
        logger.info("Heartbeat loop started")

        while self.running:
            self.send_heartbeat()
            self.update_tray_icon()

            interval = self.config.get('heartbeat_interval', 10)
            time.sleep(interval)

        logger.info("Heartbeat loop stopped")

    def start(self):
        """Start the heartbeat agent"""
        if self.running:
            logger.warning("Agent already running")
            return

        device_name = self.config.get('device_name')
        if not device_name:
            logger.info("First run - showing configuration GUI")
            self.show_settings(first_run=True)
            if not self.config.get('device_name'):
                logger.error("Configuration cancelled, exiting")
                return False

        self.running = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        logger.info("Heartbeat agent started")
        return True

    def stop(self):
        """Stop the heartbeat agent"""
        if not self.running:
            return

        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
        logger.info("Heartbeat agent stopped")

    def create_tray_icon_image(self):
        """Create system tray icon with heartbeat count"""
        # Create image
        size = (64, 64)
        image = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Determine color based on status
        if self.last_error:
            color = (239, 68, 68)  # Red
        elif self.last_success:
            time_since = (datetime.now() - self.last_success).total_seconds()
            if time_since < 60:
                color = (34, 197, 94)  # Green
            else:
                color = (251, 191, 36)  # Yellow
        else:
            color = (156, 163, 175)  # Gray

        # Draw heart shape
        draw.ellipse([8, 12, 28, 32], fill=color)
        draw.ellipse([36, 12, 56, 32], fill=color)
        draw.polygon([(32, 56), (8, 32), (56, 32)], fill=color)

        # Draw heartbeat count (if any)
        if self.heartbeat_count > 0:
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except:
                font = ImageFont.load_default()

            count_text = str(self.heartbeat_count)
            if self.heartbeat_count > 999:
                count_text = "999+"

            # Text background
            bbox = draw.textbbox((0, 0), count_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            bg_x = (size[0] - text_width) // 2
            bg_y = size[1] - text_height - 4

            draw.rectangle(
                [bg_x - 2, bg_y - 2, bg_x + text_width + 2, bg_y + text_height + 2],
                fill=(0, 0, 0, 180)
            )
            draw.text((bg_x, bg_y), count_text, fill=(255, 255, 255), font=font)

        return image

    def update_tray_icon(self):
        """Update the tray icon image and tooltip"""
        if self.tray_icon:
            self.tray_icon.icon = self.create_tray_icon_image()

            # Update tooltip
            device_name = self.config.get('device_name', 'Not configured')
            status = "Connected" if not self.last_error else "Disconnected"
            tooltip = f"Heartbeat Agent v2.0\n{device_name}\n{status}\nHeartbeats: {self.heartbeat_count}"
            self.tray_icon.title = tooltip

    def show_status(self):
        """Show status window"""
        logger.info("Opening status window")

        root = tk.Tk()
        root.title("Heartbeat Agent Status")
        root.geometry("500x400")
        root.resizable(False, False)

        # Device info frame
        info_frame = ttk.LabelFrame(root, text="Device Information", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(info_frame, text=f"Device Name: {self.config.get('device_name', 'Not configured')}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"MAC Address: {self.mac_address}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"Server: {self.config.get('server_url', 'Not configured')}").pack(anchor=tk.W)

        # Status frame
        status_frame = ttk.LabelFrame(root, text="Status", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=5)

        status_text = "Running" if self.running else "Stopped"
        status_color = "green" if self.running else "red"
        status_label = ttk.Label(status_frame, text=f"Agent Status: {status_text}", foreground=status_color)
        status_label.pack(anchor=tk.W)

        ttk.Label(status_frame, text=f"Total Heartbeats: {self.heartbeat_count}").pack(anchor=tk.W)

        if self.last_success:
            ttk.Label(status_frame, text=f"Last Success: {self.last_success.strftime('%Y-%m-%d %H:%M:%S')}").pack(anchor=tk.W)

        if self.last_error:
            ttk.Label(status_frame, text=f"Last Error: {self.last_error}", foreground="red").pack(anchor=tk.W)

        # Log viewer frame
        log_frame = ttk.LabelFrame(root, text="Recent Logs", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        log_text = scrolledtext.ScrolledText(log_frame, height=10, width=60)
        log_text.pack(fill=tk.BOTH, expand=True)

        # Load recent logs
        try:
            log_file = logger.handlers[0].baseFilename
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    # Show last 20 lines
                    recent_lines = lines[-20:] if len(lines) > 20 else lines
                    log_text.insert(tk.END, ''.join(recent_lines))
                    log_text.see(tk.END)
        except Exception as e:
            log_text.insert(tk.END, f"Error loading logs: {e}")

        log_text.config(state=tk.DISABLED)

        # Close button
        ttk.Button(root, text="Close", command=root.destroy).pack(pady=10)

        root.mainloop()

    def show_settings(self, first_run=False):
        """Show settings window"""
        logger.info("Opening settings window")

        root = tk.Tk()
        root.title("Heartbeat Agent Settings" + (" - First Run" if first_run else ""))
        root.geometry("450x300")
        root.resizable(False, False)

        if first_run:
            ttk.Label(root, text="Welcome to Heartbeat Agent v2.0!", font=('Arial', 14, 'bold')).pack(pady=10)
            ttk.Label(root, text="Please configure your device:").pack()

        # Settings frame
        settings_frame = ttk.Frame(root, padding=20)
        settings_frame.pack(fill=tk.BOTH, expand=True)

        # Device name
        ttk.Label(settings_frame, text="Device Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        device_name_var = tk.StringVar(value=self.config.get('device_name', socket.gethostname()))
        device_name_entry = ttk.Entry(settings_frame, textvariable=device_name_var, width=40)
        device_name_entry.grid(row=0, column=1, pady=5)

        # Server URL
        ttk.Label(settings_frame, text="Server URL:").grid(row=1, column=0, sticky=tk.W, pady=5)
        server_url_var = tk.StringVar(value=self.config.get('server_url', DEFAULT_CONFIG['server_url']))
        server_url_entry = ttk.Entry(settings_frame, textvariable=server_url_var, width=40)
        server_url_entry.grid(row=1, column=1, pady=5)

        # Heartbeat interval
        ttk.Label(settings_frame, text="Heartbeat Interval (seconds):").grid(row=2, column=0, sticky=tk.W, pady=5)
        interval_var = tk.IntVar(value=self.config.get('heartbeat_interval', 10))
        interval_spinbox = ttk.Spinbox(settings_frame, from_=5, to=300, textvariable=interval_var, width=38)
        interval_spinbox.grid(row=2, column=1, pady=5)

        # MAC address (read-only)
        ttk.Label(settings_frame, text="MAC Address:").grid(row=3, column=0, sticky=tk.W, pady=5)
        mac_label = ttk.Label(settings_frame, text=self.mac_address, foreground="gray")
        mac_label.grid(row=3, column=1, sticky=tk.W, pady=5)

        # Save function
        def save_settings():
            device_name = device_name_var.get().strip()
            server_url = server_url_var.get().strip().rstrip('/')

            if not device_name:
                messagebox.showerror("Error", "Device name cannot be empty!")
                return

            if not server_url:
                messagebox.showerror("Error", "Server URL cannot be empty!")
                return

            self.config['device_name'] = device_name
            self.config['server_url'] = server_url
            self.config['heartbeat_interval'] = interval_var.get()

            if save_config(self.config):
                messagebox.showinfo("Success", "Settings saved successfully!\n\nThe agent will restart with new settings.")
                logger.info("Settings saved, restarting agent")

                # Restart agent
                self.stop()
                self.start()

                root.destroy()
            else:
                messagebox.showerror("Error", "Failed to save settings!")

        # Cancel function
        def cancel_settings():
            if first_run and not self.config.get('device_name'):
                if messagebox.askyesno("Exit", "Configuration is required. Exit application?"):
                    root.destroy()
                    self.exit_app()
            else:
                root.destroy()

        # Buttons
        button_frame = ttk.Frame(root)
        button_frame.pack(pady=10)

        ttk.Button(button_frame, text="Save", command=save_settings, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel_settings, width=15).pack(side=tk.LEFT, padx=5)

        root.protocol("WM_DELETE_WINDOW", cancel_settings)
        root.mainloop()

    def exit_app(self):
        """Exit the application"""
        logger.info("Exit requested")
        self.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        cleanup_lock_file()
        logger.info("Application exited")
        sys.exit(0)

    def setup_tray_icon(self):
        """Setup system tray icon"""
        logger.info("Setting up system tray icon")

        # Create menu
        menu = pystray.Menu(
            item('View Status', lambda: threading.Thread(target=self.show_status, daemon=True).start()),
            item('Settings', lambda: threading.Thread(target=self.show_settings, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            item('Exit', self.exit_app)
        )

        # Create icon
        image = self.create_tray_icon_image()
        self.tray_icon = pystray.Icon(
            "heartbeat_agent",
            image,
            "Heartbeat Agent v2.0",
            menu
        )

        logger.info("System tray icon created")

    def run(self):
        """Run the agent"""
        if not self.start():
            logger.error("Failed to start agent")
            return

        self.setup_tray_icon()

        # Run tray icon (blocking)
        logger.info("Starting system tray icon")
        self.tray_icon.run()

# ==================== MAIN ====================

def main():
    """Main entry point"""
    # Check for single instance
    if not check_single_instance():
        # Show error dialog
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Heartbeat Agent",
            "Another instance of Heartbeat Agent is already running!\n\n"
            "Check the system tray for the heartbeat icon."
        )
        root.destroy()
        return

    try:
        # Create and run agent
        agent = HeartbeatAgent()
        agent.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)

        # Show error dialog
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Heartbeat Agent Error",
            f"A fatal error occurred:\n\n{str(e)}\n\n"
            f"Check the log file for more details."
        )
        root.destroy()

if __name__ == '__main__':
    main()
