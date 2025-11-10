"""
PC Heartbeat Monitoring Server
===============================
Flask server that receives heartbeat POST requests from remote Windows PCs
and displays their online/offline status in a real-time dashboard.

Features:
- Heartbeat API endpoint
- SQLite database for device tracking
- Auto-refresh web dashboard
- Uptime percentage calculation
- Background cleanup task
"""

from flask import Flask, render_template_string, request, jsonify
from datetime import datetime, timedelta
from threading import Thread
import sqlite3
import time
import os

app = Flask(__name__)

# Configuration
DATABASE = 'heartbeat.db'
OFFLINE_THRESHOLD_MINUTES = 5  # Device marked offline if no heartbeat for 5 minutes
CLEANUP_INTERVAL_HOURS = 24    # Clean old records every 24 hours

# ==================== DATABASE SETUP ====================

def init_db():
    """Initialize SQLite database with devices and heartbeats tables"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Devices table
    c.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT UNIQUE NOT NULL,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP,
            total_heartbeats INTEGER DEFAULT 0
        )
    ''')
    
    # Heartbeats history table (for uptime calculation)
    c.execute('''
        CREATE TABLE IF NOT EXISTS heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_name) REFERENCES devices(device_name)
        )
    ''')
    
    # Index for faster queries
    c.execute('CREATE INDEX IF NOT EXISTS idx_device_name ON heartbeats(device_name)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON heartbeats(timestamp)')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

# ==================== API ENDPOINTS ====================

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """
    Receive heartbeat from client devices
    Expected JSON: {"device_name": "Branch01", "timestamp": "2025-11-10 10:30:00"}
    """
    try:
        data = request.get_json()
        
        if not data or 'device_name' not in data:
            return jsonify({"error": "device_name is required"}), 400
        
        device_name = data['device_name']
        client_timestamp = data.get('timestamp', datetime.now().isoformat())
        
        conn = get_db()
        c = conn.cursor()
        
        # Insert or update device
        c.execute('''
            INSERT INTO devices (device_name, last_seen, total_heartbeats)
            VALUES (?, ?, 1)
            ON CONFLICT(device_name) DO UPDATE SET
                last_seen = ?,
                total_heartbeats = total_heartbeats + 1
        ''', (device_name, datetime.now(), datetime.now()))
        
        # Log heartbeat for uptime calculation
        c.execute('''
            INSERT INTO heartbeats (device_name, timestamp)
            VALUES (?, ?)
        ''', (device_name, datetime.now()))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "status": "success",
            "device_name": device_name,
            "server_time": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        print(f"❌ Error in heartbeat endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """API endpoint to get all devices status (JSON)"""
    try:
        devices = get_all_devices_status()
        return jsonify({"devices": devices, "total": len(devices)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== DEVICE STATUS LOGIC ====================

def get_all_devices_status():
    """Get status of all devices with online/offline state and uptime"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM devices ORDER BY device_name')
    devices = c.fetchall()
    
    device_list = []
    now = datetime.now()
    offline_threshold = now - timedelta(minutes=OFFLINE_THRESHOLD_MINUTES)
    
    for device in devices:
        last_seen = datetime.fromisoformat(device['last_seen']) if device['last_seen'] else None
        
        # Determine online/offline status
        is_online = last_seen and last_seen >= offline_threshold
        
        # Calculate uptime percentage (last 24 hours)
        uptime_pct = calculate_uptime(device['device_name'], hours=24)
        
        # Format last seen
        if last_seen:
            time_diff = now - last_seen
            if time_diff.total_seconds() < 60:
                last_seen_str = "Just now"
            elif time_diff.total_seconds() < 3600:
                minutes = int(time_diff.total_seconds() / 60)
                last_seen_str = f"{minutes} min ago"
            elif time_diff.total_seconds() < 86400:
                hours = int(time_diff.total_seconds() / 3600)
                last_seen_str = f"{hours} hr ago"
            else:
                days = int(time_diff.total_seconds() / 86400)
                last_seen_str = f"{days} days ago"
        else:
            last_seen_str = "Never"
        
        device_list.append({
            "device_name": device['device_name'],
            "status": "online" if is_online else "offline",
            "last_seen": last_seen_str,
            "last_seen_timestamp": last_seen.isoformat() if last_seen else None,
            "total_heartbeats": device['total_heartbeats'],
            "uptime_24h": uptime_pct,
            "first_seen": device['first_seen']
        })
    
    conn.close()
    return device_list

def calculate_uptime(device_name, hours=24):
    """Calculate uptime percentage for the last N hours"""
    conn = get_db()
    c = conn.cursor()
    
    time_threshold = datetime.now() - timedelta(hours=hours)
    
    # Count heartbeats in the period (expected: 1 per minute = 60 per hour)
    c.execute('''
        SELECT COUNT(*) FROM heartbeats
        WHERE device_name = ? AND timestamp >= ?
    ''', (device_name, time_threshold))
    
    actual_heartbeats = c.fetchone()[0]
    expected_heartbeats = hours * 60  # 1 heartbeat per minute
    
    conn.close()
    
    if expected_heartbeats == 0:
        return 0.0
    
    uptime = min((actual_heartbeats / expected_heartbeats) * 100, 100.0)
    return round(uptime, 1)

# ==================== WEB DASHBOARD ====================

@app.route('/')
def dashboard():
    """Main dashboard page with auto-refresh"""
    devices = get_all_devices_status()
    
    # Statistics
    total_devices = len(devices)
    online_devices = sum(1 for d in devices if d['status'] == 'online')
    offline_devices = total_devices - online_devices
    
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PC Heartbeat Monitor</title>
        <meta http-equiv="refresh" content="30">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            
            .header {
                background: white;
                padding: 30px;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                margin-bottom: 30px;
            }
            
            h1 {
                color: #333;
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            
            .subtitle {
                color: #666;
                font-size: 1.1em;
            }
            
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            
            .stat-card {
                background: white;
                padding: 25px;
                border-radius: 12px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                text-align: center;
            }
            
            .stat-number {
                font-size: 3em;
                font-weight: bold;
                margin-bottom: 10px;
            }
            
            .stat-label {
                color: #666;
                font-size: 1.1em;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            .stat-card.total .stat-number { color: #667eea; }
            .stat-card.online .stat-number { color: #10b981; }
            .stat-card.offline .stat-number { color: #ef4444; }
            
            .devices-table {
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                overflow: hidden;
            }
            
            table {
                width: 100%;
                border-collapse: collapse;
            }
            
            thead {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            
            th {
                padding: 20px;
                text-align: left;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                font-size: 0.9em;
            }
            
            tbody tr {
                border-bottom: 1px solid #e5e7eb;
                transition: background 0.3s ease;
            }
            
            tbody tr:hover {
                background: #f9fafb;
            }
            
            tbody tr:last-child {
                border-bottom: none;
            }
            
            td {
                padding: 20px;
                color: #333;
            }
            
            .status-badge {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 16px;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.9em;
            }
            
            .status-badge.online {
                background: #d1fae5;
                color: #065f46;
            }
            
            .status-badge.offline {
                background: #fee2e2;
                color: #991b1b;
            }
            
            .status-dot {
                width: 10px;
                height: 10px;
                border-radius: 50%;
                animation: pulse 2s infinite;
            }
            
            .status-badge.online .status-dot {
                background: #10b981;
            }
            
            .status-badge.offline .status-dot {
                background: #ef4444;
            }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            
            .uptime-bar {
                width: 100%;
                height: 8px;
                background: #e5e7eb;
                border-radius: 4px;
                overflow: hidden;
                margin-top: 5px;
            }
            
            .uptime-fill {
                height: 100%;
                background: linear-gradient(90deg, #10b981 0%, #059669 100%);
                transition: width 0.3s ease;
            }
            
            .uptime-text {
                font-size: 0.85em;
                color: #666;
                margin-top: 3px;
            }
            
            .last-updated {
                text-align: center;
                color: white;
                margin-top: 20px;
                font-size: 0.9em;
                opacity: 0.9;
            }
            
            .refresh-notice {
                background: rgba(255,255,255,0.2);
                padding: 10px 20px;
                border-radius: 8px;
                display: inline-block;
                margin-top: 10px;
            }
            
            @media (max-width: 768px) {
                h1 { font-size: 1.8em; }
                .stats { grid-template-columns: 1fr; }
                table { font-size: 0.85em; }
                th, td { padding: 12px 8px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🖥️ PC Heartbeat Monitor</h1>
                <p class="subtitle">Real-time monitoring of {{ total_devices }} Windows PCs across multiple locations</p>
            </div>
            
            <div class="stats">
                <div class="stat-card total">
                    <div class="stat-number">{{ total_devices }}</div>
                    <div class="stat-label">Total Devices</div>
                </div>
                <div class="stat-card online">
                    <div class="stat-number">{{ online_devices }}</div>
                    <div class="stat-label">Online</div>
                </div>
                <div class="stat-card offline">
                    <div class="stat-number">{{ offline_devices }}</div>
                    <div class="stat-label">Offline</div>
                </div>
            </div>
            
            <div class="devices-table">
                <table>
                    <thead>
                        <tr>
                            <th>Device Name</th>
                            <th>Status</th>
                            <th>Last Seen</th>
                            <th>Uptime (24h)</th>
                            <th>Total Heartbeats</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if devices %}
                            {% for device in devices %}
                            <tr>
                                <td><strong>{{ device.device_name }}</strong></td>
                                <td>
                                    <span class="status-badge {{ device.status }}">
                                        <span class="status-dot"></span>
                                        {{ device.status|upper }}
                                    </span>
                                </td>
                                <td>{{ device.last_seen }}</td>
                                <td>
                                    <div class="uptime-bar">
                                        <div class="uptime-fill" style="width: {{ device.uptime_24h }}%"></div>
                                    </div>
                                    <div class="uptime-text">{{ device.uptime_24h }}%</div>
                                </td>
                                <td>{{ "{:,}".format(device.total_heartbeats) }}</td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="5" style="text-align: center; padding: 40px; color: #999;">
                                    No devices registered yet. Start the client script on your Windows PCs.
                                </td>
                            </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
            
            <div class="last-updated">
                <div class="refresh-notice">
                    🔄 Auto-refreshing every 30 seconds | Last updated: {{ now }}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return render_template_string(
        html_template,
        devices=devices,
        total_devices=total_devices,
        online_devices=online_devices,
        offline_devices=offline_devices,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

# ==================== BACKGROUND CLEANUP TASK ====================

def cleanup_old_heartbeats():
    """Background task to clean up old heartbeat records (keeps last 7 days)"""
    while True:
        try:
            time.sleep(CLEANUP_INTERVAL_HOURS * 3600)  # Run every N hours
            
            conn = get_db()
            c = conn.cursor()
            
            # Delete heartbeats older than 7 days
            cutoff_date = datetime.now() - timedelta(days=7)
            c.execute('DELETE FROM heartbeats WHERE timestamp < ?', (cutoff_date,))
            deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            print(f"🧹 Cleanup: Deleted {deleted} old heartbeat records")
            
        except Exception as e:
            print(f"❌ Error in cleanup task: {str(e)}")

def start_background_tasks():
    """Start background cleanup thread"""
    cleanup_thread = Thread(target=cleanup_old_heartbeats, daemon=True)
    cleanup_thread.start()
    print("✅ Background cleanup task started")

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Starting PC Heartbeat Monitoring Server")
    print("=" * 60)
    
    # Initialize database
    init_db()
    
    # Start background tasks
    start_background_tasks()
    
    # Get port from environment (for Render deployment) or use 5000
    port = int(os.environ.get('PORT', 5000))
    
    print(f"📡 Server starting on port {port}")
    print(f"🌐 Dashboard will be available at http://localhost:{port}")
    print(f"📨 Heartbeat endpoint: http://localhost:{port}/heartbeat")
    print(f"🔄 Auto-refresh: 30 seconds")
    print(f"⏰ Offline threshold: {OFFLINE_THRESHOLD_MINUTES} minutes")
    print("=" * 60)
    
    # Run Flask server
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False  # Set to False in production
    )
