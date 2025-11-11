"""
HeartbeatAgent EXE Builder - GUI Version
=========================================
Double-click this file to build the EXE with a friendly GUI.
No command line needed!
"""

import tkinter as tk
from tkinter import messagebox, scrolledtext
import subprocess
import sys
import os
import threading

class ExeBuilder:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HeartbeatAgent EXE Builder")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.root.winfo_screenheight() // 2) - (500 // 2)
        self.root.geometry(f"+{x}+{y}")
        
        self.create_widgets()
        
    def create_widgets(self):
        # Header
        header_frame = tk.Frame(self.root, bg="#667eea", height=80)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)
        
        title = tk.Label(
            header_frame,
            text="🏗️ HeartbeatAgent EXE Builder",
            font=("Segoe UI", 16, "bold"),
            bg="#667eea",
            fg="white"
        )
        title.pack(pady=25)
        
        # Main content
        content_frame = tk.Frame(self.root, padx=30, pady=20)
        content_frame.pack(fill="both", expand=True)
        
        # Instructions
        instructions = tk.Label(
            content_frame,
            text="This will build HeartbeatAgent.exe from client_tray.py\n"
                 "Make sure client_tray.py is in the same folder as this script!",
            font=("Segoe UI", 10),
            justify="left",
            fg="#333"
        )
        instructions.pack(anchor="w", pady=(0, 20))
        
        # Status text area
        status_label = tk.Label(
            content_frame,
            text="Build Output:",
            font=("Segoe UI", 10, "bold"),
            fg="#333"
        )
        status_label.pack(anchor="w", pady=(0, 5))
        
        self.status_text = scrolledtext.ScrolledText(
            content_frame,
            height=15,
            width=65,
            font=("Consolas", 9),
            bg="#f5f5f5",
            fg="#333"
        )
        self.status_text.pack(pady=(0, 15))
        
        # Progress bar frame
        progress_frame = tk.Frame(content_frame)
        progress_frame.pack(fill="x", pady=(0, 15))
        
        self.progress_label = tk.Label(
            progress_frame,
            text="Ready to build",
            font=("Segoe UI", 9),
            fg="#666"
        )
        self.progress_label.pack()
        
        # Buttons
        button_frame = tk.Frame(content_frame)
        button_frame.pack()
        
        self.build_button = tk.Button(
            button_frame,
            text="🚀 Build EXE",
            command=self.start_build,
            bg="#10b981",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            width=15,
            height=2,
            relief="flat",
            cursor="hand2"
        )
        self.build_button.grid(row=0, column=0, padx=5)
        
        self.close_button = tk.Button(
            button_frame,
            text="Close",
            command=self.root.quit,
            bg="#6b7280",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            width=15,
            height=2,
            relief="flat",
            cursor="hand2"
        )
        self.close_button.grid(row=0, column=1, padx=5)
        
    def log(self, message):
        """Add message to status text"""
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.root.update()
        
    def run_command(self, cmd, description):
        """Run a command and show output"""
        self.log(f"\n{'='*50}")
        self.log(f"{description}")
        self.log('='*50)
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True
            )
            
            for line in process.stdout:
                self.log(line.rstrip())
            
            process.wait()
            return process.returncode == 0
        except Exception as e:
            self.log(f"ERROR: {str(e)}")
            return False
    
    def build_exe_thread(self):
        """Build process in separate thread"""
        try:
            # Disable build button
            self.build_button.config(state="disabled", text="Building...")
            self.progress_label.config(text="Building in progress...", fg="#f59e0b")
            
            # Check if client_tray.py exists
            if not os.path.exists("client_tray.py"):
                self.log("\n❌ ERROR: client_tray.py not found!")
                self.log("Please make sure client_tray.py is in the same folder as this script.")
                messagebox.showerror(
                    "File Not Found",
                    "client_tray.py not found!\n\n"
                    "Please place client_tray.py in the same folder as this builder script."
                )
                self.build_button.config(state="normal", text="🚀 Build EXE")
                self.progress_label.config(text="Build failed", fg="#ef4444")
                return
            
            self.log("✅ Found client_tray.py")
            
            # Step 1: Install dependencies
            self.progress_label.config(text="Step 1/3: Installing dependencies...")
            success = self.run_command(
                f'"{sys.executable}" -m pip install pyinstaller pillow pystray psutil requests',
                "STEP 1: Installing Dependencies"
            )
            
            if not success:
                self.log("\n❌ Failed to install dependencies")
                messagebox.showerror("Build Failed", "Failed to install dependencies.\nCheck the output above for details.")
                self.build_button.config(state="normal", text="🚀 Build EXE")
                self.progress_label.config(text="Build failed", fg="#ef4444")
                return
            
            self.log("\n✅ Dependencies installed")
            
            # Step 2: Build EXE
            self.progress_label.config(text="Step 2/3: Building executable...")
            success = self.run_command(
                f'"{sys.executable}" -m PyInstaller --onefile --name HeartbeatAgent client_tray.py',
                "STEP 2: Building Executable"
            )
            
            if not success:
                self.log("\n❌ Build failed")
                messagebox.showerror("Build Failed", "Failed to build EXE.\nCheck the output above for details.")
                self.build_button.config(state="normal", text="🚀 Build EXE")
                self.progress_label.config(text="Build failed", fg="#ef4444")
                return
            
            self.log("\n✅ EXE built successfully")
            
            # Step 3: Cleanup
            self.progress_label.config(text="Step 3/3: Cleaning up...")
            self.log("\n" + "="*50)
            self.log("STEP 3: Cleaning Up")
            self.log("="*50)
            
            # Remove build folder and spec file
            try:
                if os.path.exists("build"):
                    import shutil
                    shutil.rmtree("build")
                    self.log("✅ Removed build folder")
                
                if os.path.exists("HeartbeatAgent.spec"):
                    os.remove("HeartbeatAgent.spec")
                    self.log("✅ Removed spec file")
            except Exception as e:
                self.log(f"⚠️  Cleanup warning: {str(e)}")
            
            # Success!
            self.log("\n" + "="*50)
            self.log("🎉 BUILD COMPLETE!")
            self.log("="*50)
            self.log("\nYour executable is ready:")
            self.log(f"📁 Location: {os.path.abspath('dist/HeartbeatAgent.exe')}")
            
            if os.path.exists("dist/HeartbeatAgent.exe"):
                size = os.path.getsize("dist/HeartbeatAgent.exe") / (1024 * 1024)
                self.log(f"📊 Size: {size:.1f} MB")
            
            self.log("\n✅ You can now copy HeartbeatAgent.exe to your 33 PCs!")
            
            self.progress_label.config(text="✅ Build completed successfully!", fg="#10b981")
            
            messagebox.showinfo(
                "Build Complete! 🎉",
                "HeartbeatAgent.exe has been created successfully!\n\n"
                f"Location: dist\\HeartbeatAgent.exe\n\n"
                "You can now copy this file to your 33 Windows PCs.\n"
                "No Python installation needed on those PCs!"
            )
            
            # Ask if user wants to open folder
            if messagebox.askyesno("Open Folder?", "Do you want to open the dist folder?"):
                try:
                    os.startfile(os.path.abspath("dist"))
                except:
                    pass
            
        except Exception as e:
            self.log(f"\n❌ Unexpected error: {str(e)}")
            messagebox.showerror("Error", f"An unexpected error occurred:\n{str(e)}")
            self.progress_label.config(text="Build failed", fg="#ef4444")
        
        finally:
            self.build_button.config(state="normal", text="🚀 Build EXE")
    
    def start_build(self):
        """Start build in separate thread"""
        self.status_text.delete(1.0, tk.END)
        thread = threading.Thread(target=self.build_exe_thread, daemon=True)
        thread.start()
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    # Check if running with proper Python
    if sys.version_info < (3, 6):
        messagebox.showerror(
            "Python Version Error",
            "This script requires Python 3.6 or higher.\n"
            f"You are running Python {sys.version_info.major}.{sys.version_info.minor}"
        )
        sys.exit(1)
    
    app = ExeBuilder()
    app.run()
