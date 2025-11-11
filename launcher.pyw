"""
Launcher for HeartbeatAgent
This script launches the main application without a console window
The .pyw extension means Python runs it without creating a console
"""
import subprocess
import sys
import os

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
main_script = os.path.join(script_dir, "client_tray.py")

# Launch the main script with pythonw.exe (no console)
# Using CREATE_NO_WINDOW and DETACHED_PROCESS flags
if sys.platform == 'win32':
    # Windows-specific launch without console
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000

    subprocess.Popen(
        [sys.executable, main_script],
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True
    )
else:
    # For other platforms (shouldn't happen, but just in case)
    subprocess.Popen([sys.executable, main_script])
