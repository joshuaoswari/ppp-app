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
            mac_address TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP,
            total_heartbeats INTEGER DEFAULT 0,
            display_order INTEGER DEFAULT 999
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
    c.execute('CREATE INDEX IF NOT EXISTS idx_display_order ON devices(display_order)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_mac_address ON devices(mac_address)')
    
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
    Expected JSON: {"device_name": "Branch01", "timestamp": "2025-11-10 10:30:00", "mac_address": "00:11:22:33:44:55"}
    """
    try:
        data = request.get_json()
        
        if not data or 'device_name' not in data:
            return jsonify({"error": "device_name is required"}), 400
        
        device_name = data['device_name']
        mac_address = data.get('mac_address')
        client_timestamp = data.get('timestamp', datetime.now().isoformat())
        
        conn = get_db()
        c = conn.cursor()
        
        # Check if a device with this MAC address already exists with a different name
        if mac_address:
            c.execute('SELECT device_name FROM devices WHERE mac_address = ? AND device_name != ?', 
                     (mac_address, device_name))
            existing_device = c.fetchone()
            
            if existing_device:
                old_name = existing_device['device_name']
                
                # Update all heartbeat records to use new name
                c.execute('UPDATE heartbeats SET device_name = ? WHERE device_name = ?', 
                         (device_name, old_name))
                
                # Update device record with new name
                c.execute('''
                    UPDATE devices 
                    SET device_name = ?, last_seen = ?, total_heartbeats = total_heartbeats + 1
                    WHERE mac_address = ?
                ''', (device_name, datetime.now(), mac_address))
                
                print(f"✏️  Renamed device: {old_name} → {device_name} (MAC: {mac_address})")
            else:
                # Insert or update device
                c.execute('''
                    INSERT INTO devices (device_name, mac_address, last_seen, total_heartbeats)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(device_name) DO UPDATE SET
                        mac_address = ?,
                        last_seen = ?,
                        total_heartbeats = total_heartbeats + 1
                ''', (device_name, mac_address, datetime.now(), mac_address, datetime.now()))
        else:
            # No MAC address provided, use old logic
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

@app.route('/api/device/<device_name>', methods=['DELETE'])
def delete_device(device_name):
    """Delete a device and all its heartbeat history"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Delete heartbeats first (foreign key)
        c.execute('DELETE FROM heartbeats WHERE device_name = ?', (device_name,))
        
        # Delete device
        c.execute('DELETE FROM devices WHERE device_name = ?', (device_name,))
        
        deleted = c.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            return jsonify({"success": True, "message": f"Device '{device_name}' deleted"}), 200
        else:
            return jsonify({"success": False, "message": "Device not found"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device/<device_name>/uptime', methods=['GET'])
def get_device_uptime(device_name):
    """Get 7-day (current week) uptime visualization data for a device"""
    try:
        blocks = get_uptime_blocks(device_name, days=7)
        
        # Calculate overall uptime
        total_uptime = sum(b['uptime'] for b in blocks) / len(blocks) if blocks else 0
        
        return jsonify({
            "device_name": device_name,
            "blocks": blocks,
            "average_uptime": round(total_uptime, 2)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device/<device_name>/reorder', methods=['POST'])
def reorder_device(device_name):
    """Update device display order"""
    try:
        data = request.get_json()
        new_order = data.get('order')
        
        if new_order is None:
            return jsonify({"error": "Order number required"}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Update the device order
        c.execute('''
            UPDATE devices 
            SET display_order = ? 
            WHERE device_name = ?
        ''', (new_order, device_name))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "device_name": device_name, "order": new_order}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/devices/reorder', methods=['POST'])
def reorder_all_devices():
    """Reorder all devices at once"""
    try:
        data = request.get_json()
        device_order = data.get('devices')  # Array of device names in order
        
        if not device_order:
            return jsonify({"error": "Devices array required"}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Update each device with its new order
        for idx, device_name in enumerate(device_order):
            c.execute('''
                UPDATE devices 
                SET display_order = ? 
                WHERE device_name = ?
            ''', (idx + 1, device_name))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Devices reordered"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== DEVICE STATUS LOGIC ====================

def get_all_devices_status():
    """Get status of all devices with online/offline state and uptime"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM devices ORDER BY display_order ASC, device_name ASC')
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

def get_uptime_blocks(device_name, days=7):
    """Get uptime data for visualization blocks (7 days - Monday to Sunday)"""
    conn = get_db()
    c = conn.cursor()
    
    blocks = []
    now = datetime.now()
    
    # Calculate start of current week (Monday)
    days_since_monday = now.weekday()  # 0=Monday, 6=Sunday
    week_start = now - timedelta(days=days_since_monday, hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)
    
    # Generate blocks for Monday to Sunday (or until today if week not complete)
    for day_offset in range(7):
        day_start = week_start + timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        
        # Don't show future days
        if day_start > now:
            break
        
        # Count heartbeats for this day
        c.execute('''
            SELECT COUNT(*) FROM heartbeats
            WHERE device_name = ? AND timestamp >= ? AND timestamp < ?
        ''', (device_name, day_start, day_end))
        
        heartbeats = c.fetchone()[0]
        
        # If this is today, calculate expected based on hours elapsed
        if day_start.date() == now.date():
            hours_elapsed = (now - day_start).total_seconds() / 3600
            expected = hours_elapsed * 60  # 60 heartbeats per hour
        else:
            expected = 24 * 60  # 1440 heartbeats per day
        
        uptime_pct = min((heartbeats / expected) * 100, 100.0) if expected > 0 else 0
        
        # Categorize status
        if uptime_pct >= 95:
            status = 'operational'
        elif uptime_pct >= 50:
            status = 'degraded'
        else:
            status = 'outage'
        
        # Get day name
        day_name = day_start.strftime('%A')  # Monday, Tuesday, etc.
        
        blocks.append({
            'date': day_start.strftime('%Y-%m-%d'),
            'day_name': day_name,
            'uptime': round(uptime_pct, 1),
            'status': status,
            'hours_online': round((heartbeats / 60), 1)  # Convert heartbeats to hours
        })
    
    conn.close()
    return blocks

def create_dummy_device():
    """Create a dummy device with 7 days of realistic uptime data"""
    conn = get_db()
    c = conn.cursor()
    
    device_name = "Dummy-Example-PC"
    
    # Check if dummy already exists
    c.execute('SELECT device_name FROM devices WHERE device_name = ?', (device_name,))
    if c.fetchone():
        conn.close()
        return  # Already exists
    
    # Create device
    now = datetime.now()
    
    # Calculate start of current week (Monday)
    days_since_monday = now.weekday()
    week_start = now - timedelta(days=days_since_monday, hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)
    
    c.execute('''
        INSERT INTO devices (device_name, first_seen, last_seen, total_heartbeats)
        VALUES (?, ?, ?, ?)
    ''', (device_name, week_start, now, 10080))  # 7 days * 1440 heartbeats/day
    
    # Generate 7 days of heartbeat data with realistic patterns
    import random
    
    for day_offset in range(7):
        day_start = week_start + timedelta(days=day_offset)
        
        # Don't create future data
        if day_start > now:
            break
        
        # If this is today, only create heartbeats until now
        if day_start.date() == now.date():
            hours_elapsed = int((now - day_start).total_seconds() / 3600)
            max_heartbeats = hours_elapsed * 60
        else:
            max_heartbeats = 1440
        
        # Simulate different uptime scenarios
        if random.random() < 0.1:  # 10% chance of degraded day
            heartbeats_this_day = random.randint(int(max_heartbeats * 0.6), int(max_heartbeats * 0.9))
        else:  # 90% chance of operational day
            heartbeats_this_day = random.randint(int(max_heartbeats * 0.95), max_heartbeats)
        
        # Insert heartbeats for this day
        for i in range(heartbeats_this_day):
            heartbeat_time = day_start + timedelta(minutes=i)
            if heartbeat_time > now:
                break
            c.execute('''
                INSERT INTO heartbeats (device_name, timestamp)
                VALUES (?, ?)
            ''', (device_name, heartbeat_time))
    
    conn.commit()
    conn.close()
    print(f"✅ Created dummy device with 7 days of data: {device_name}")

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
                cursor: pointer;
                user-select: none;
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
            
            /* Uptime Blocks Visualization */
            .uptime-blocks {
                display: flex;
                gap: 4px;
                flex-wrap: wrap;
                max-width: 400px;
            }
            
            .uptime-block {
                width: 40px;
                height: 40px;
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.2s ease;
                position: relative;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 0.7em;
                font-weight: 600;
                color: white;
            }
            
            .uptime-block:hover {
                transform: scale(1.15);
                z-index: 10;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            }
            
            .uptime-block.operational {
                background: #10b981;
            }
            
            .uptime-block.degraded {
                background: #f59e0b;
            }
            
            .uptime-block.outage {
                background: #ef4444;
            }
            
            /* Tooltip */
            .uptime-tooltip {
                position: absolute;
                bottom: 110%;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(0, 0, 0, 0.9);
                color: white;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 0.75em;
                white-space: nowrap;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.2s;
                z-index: 1000;
            }
            
            .uptime-block:hover .uptime-tooltip {
                opacity: 1;
            }
            
            .uptime-tooltip::after {
                content: '';
                position: absolute;
                top: 100%;
                left: 50%;
                transform: translateX(-50%);
                border: 5px solid transparent;
                border-top-color: rgba(0, 0, 0, 0.9);
            }
            
            .uptime-legend {
                display: flex;
                gap: 15px;
                margin-top: 8px;
                font-size: 0.75em;
                color: #666;
            }
            
            .legend-item {
                display: flex;
                align-items: center;
                gap: 5px;
            }
            
            .legend-dot {
                width: 10px;
                height: 10px;
                border-radius: 2px;
            }
            
            .expand-btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 4px 10px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.75em;
                margin-top: 5px;
                transition: background 0.3s;
            }
            
            .expand-btn:hover {
                background: #5568d3;
            }
            
            .expanded-view {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.9);
                display: none;
                z-index: 2000;
                padding: 40px;
                overflow: auto;
            }
            
            .expanded-content {
                background: white;
                border-radius: 15px;
                padding: 30px;
                max-width: 1200px;
                margin: 0 auto;
                position: relative;
            }
            
            .close-expanded {
                position: absolute;
                top: 20px;
                right: 20px;
                background: #ef4444;
                color: white;
                border: none;
                width: 40px;
                height: 40px;
                border-radius: 50%;
                cursor: pointer;
                font-size: 1.5em;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .expanded-blocks {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(12px, 1fr));
                gap: 4px;
                margin-top: 20px;
            }
            
            .expanded-block {
                height: 40px;
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
            
            .delete-btn {
                background: #ef4444;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.85em;
                font-weight: 600;
                transition: background 0.3s;
                margin-right: 5px;
            }
            
            .delete-btn:hover {
                background: #dc2626;
            }
            
            .reorder-controls {
                display: flex;
                gap: 5px;
                align-items: center;
            }
            
            .reorder-btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.75em;
                font-weight: 600;
                transition: background 0.3s;
            }
            
            .reorder-btn:hover {
                background: #5568d3;
            }
            
            .reorder-btn:disabled {
                background: #d1d5db;
                cursor: not-allowed;
            }
            
            .order-number {
                background: #667eea;
                color: white;
                padding: 4px 10px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 0.85em;
                min-width: 30px;
                text-align: center;
            }
            
            /* Login Modal */
            .modal {
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.7);
                animation: fadeIn 0.3s;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            
            .modal-content {
                background: white;
                margin: 10% auto;
                padding: 40px;
                border-radius: 15px;
                width: 90%;
                max-width: 400px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                animation: slideDown 0.3s;
            }
            
            @keyframes slideDown {
                from {
                    transform: translateY(-50px);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }
            
            .modal-header {
                text-align: center;
                margin-bottom: 30px;
            }
            
            .modal-header h2 {
                color: #667eea;
                font-size: 1.8em;
                margin-bottom: 10px;
            }
            
            .modal-header p {
                color: #666;
                font-size: 0.9em;
            }
            
            .form-group {
                margin-bottom: 20px;
            }
            
            .form-group label {
                display: block;
                color: #333;
                font-weight: 600;
                margin-bottom: 8px;
            }
            
            .form-group input {
                width: 100%;
                padding: 12px;
                border: 2px solid #e5e7eb;
                border-radius: 8px;
                font-size: 1em;
                transition: border 0.3s;
            }
            
            .form-group input:focus {
                outline: none;
                border-color: #667eea;
            }
            
            .btn-group {
                display: flex;
                gap: 10px;
                margin-top: 30px;
            }
            
            .btn {
                flex: 1;
                padding: 12px;
                border: none;
                border-radius: 8px;
                font-size: 1em;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s;
            }
            
            .btn-login {
                background: #667eea;
                color: white;
            }
            
            .btn-login:hover {
                background: #5568d3;
            }
            
            .btn-cancel {
                background: #e5e7eb;
                color: #333;
            }
            
            .btn-cancel:hover {
                background: #d1d5db;
            }
            
            .error-message {
                background: #fee2e2;
                color: #991b1b;
                padding: 10px;
                border-radius: 6px;
                margin-bottom: 15px;
                text-align: center;
                display: none;
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
            <div class="header" id="header" onclick="handleHeaderClick()">
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
                            <th id="admin-header" style="display:none;">Actions</th>
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
                                    <div style="font-size: 0.85em; color: #666; margin-bottom: 8px; font-weight: 600;">This Week (Mon-Sun)</div>
                                    <div class="uptime-blocks" id="blocks-{{ loop.index0 }}">
                                        <div style="color: #999; font-size: 0.85em;">Loading...</div>
                                    </div>
                                    <div class="uptime-legend">
                                        <div class="legend-item">
                                            <div class="legend-dot operational"></div>
                                            <span>95%+</span>
                                        </div>
                                        <div class="legend-item">
                                            <div class="legend-dot degraded"></div>
                                            <span>50-95%</span>
                                        </div>
                                        <div class="legend-item">
                                            <div class="legend-dot outage"></div>
                                            <span>&lt;50%</span>
                                        </div>
                                    </div>
                                </td>
                                <td>{{ "{:,}".format(device.total_heartbeats) }}</td>
                                <td class="admin-actions" style="display:none;">
                                    <div class="reorder-controls">
                                        <span class="order-number">{{ loop.index }}</span>
                                        <button class="reorder-btn" onclick="moveDevice('{{ device.device_name }}', -1, {{ loop.index0 }})" {{ 'disabled' if loop.first else '' }}>↑</button>
                                        <button class="reorder-btn" onclick="moveDevice('{{ device.device_name }}', 1, {{ loop.index0 }})" {{ 'disabled' if loop.last else '' }}>↓</button>
                                        <button class="delete-btn" onclick="deleteDevice('{{ device.device_name }}')">Delete</button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="6" style="text-align: center; padding: 40px; color: #999;">
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
        
        <!-- Login Modal -->
        <div id="loginModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h2>🔐 Admin Login</h2>
                    <p>Enter password to access admin features</p>
                </div>
                <div class="error-message" id="errorMessage">Invalid password</div>
                <form onsubmit="return handleLogin(event)">
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" placeholder="Enter admin password" required>
                    </div>
                    <div class="btn-group">
                        <button type="button" class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                        <button type="submit" class="btn btn-login">Login</button>
                    </div>
                </form>
            </div>
        </div>
        
        <script>
            let clickCount = 0;
            let clickTimer = null;
            let isAdminMode = false;
            
            // Load uptime blocks for all devices
            document.addEventListener('DOMContentLoaded', () => {
                const devices = {{ devices | tojson }};
                devices.forEach((device, index) => {
                    loadUptimeBlocks(device.device_name, index);
                });
            });
            
            function loadUptimeBlocks(deviceName, index) {
                fetch(`/api/device/${encodeURIComponent(deviceName)}/uptime`)
                    .then(response => response.json())
                    .then(data => {
                        const container = document.getElementById(`blocks-${index}`);
                        if (!container) return;
                        
                        container.innerHTML = '';
                        
                        // Show all blocks for the week (Monday to Sunday)
                        data.blocks.forEach(block => {
                            const blockEl = document.createElement('div');
                            blockEl.className = `uptime-block ${block.status}`;
                            
                            // Show first letter of day (M, T, W, T, F, S, S)
                            blockEl.textContent = block.day_name.substring(0, 1);
                            
                            const tooltip = document.createElement('div');
                            tooltip.className = 'uptime-tooltip';
                            tooltip.innerHTML = `
                                <strong>${block.day_name}</strong><br>
                                ${block.date}<br>
                                Uptime: ${block.uptime}%<br>
                                Online: ${block.hours_online} hrs
                            `;
                            
                            blockEl.appendChild(tooltip);
                            container.appendChild(blockEl);
                        });
                        
                        // Add average uptime text
                        const avgText = document.createElement('div');
                        avgText.style.cssText = 'font-size: 0.85em; color: #666; margin-top: 8px;';
                        avgText.textContent = `Week average: ${data.average_uptime}%`;
                        container.appendChild(avgText);
                    })
                    .catch(error => {
                        console.error('Error loading uptime blocks:', error);
                        const container = document.getElementById(`blocks-${index}`);
                        if (container) {
                            container.innerHTML = '<div style="color: #ef4444; font-size: 0.85em;">Error loading data</div>';
                        }
                    });
            }
            
            function closeExpandedView() {
                document.getElementById('expandedView').style.display = 'none';
            }
            
            // Close expanded view on Escape
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    closeModal();
                }
            });
            
            // Triple-click detection
            function handleHeaderClick() {
                clickCount++;
                
                if (clickCount === 1) {
                    clickTimer = setTimeout(() => {
                        clickCount = 0;
                    }, 800);
                }
                
                if (clickCount === 3) {
                    clearTimeout(clickTimer);
                    clickCount = 0;
                    showLoginModal();
                }
            }
            
            function showLoginModal() {
                document.getElementById('loginModal').style.display = 'block';
                document.getElementById('password').focus();
                document.getElementById('errorMessage').style.display = 'none';
            }
            
            function closeModal() {
                document.getElementById('loginModal').style.display = 'none';
                document.getElementById('password').value = '';
                document.getElementById('errorMessage').style.display = 'none';
            }
            
            function handleLogin(event) {
                event.preventDefault();
                const password = document.getElementById('password').value;
                
                // Simple password check (change 'admin' to your desired password)
                if (password === 'admin123') {
                    isAdminMode = true;
                    closeModal();
                    enableAdminMode();
                } else {
                    document.getElementById('errorMessage').style.display = 'block';
                    document.getElementById('password').value = '';
                    document.getElementById('password').focus();
                }
                
                return false;
            }
            
            function enableAdminMode() {
                // Show delete column header
                document.getElementById('admin-header').style.display = 'table-cell';
                
                // Show all delete buttons
                const adminActions = document.querySelectorAll('.admin-actions');
                adminActions.forEach(action => {
                    action.style.display = 'table-cell';
                });
                
                // Change header color slightly to indicate admin mode
                document.getElementById('header').style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
                document.querySelector('h1').style.color = 'white';
                document.querySelector('.subtitle').style.color = 'rgba(255,255,255,0.9)';
            }
            
            function deleteDevice(deviceName) {
                if (!confirm(`Are you sure you want to delete "${deviceName}"?\\n\\nThis will remove all heartbeat history for this device.`)) {
                    return;
                }
                
                fetch(`/api/device/${encodeURIComponent(deviceName)}`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(`Device "${deviceName}" deleted successfully!`);
                        location.reload();
                    } else {
                        alert(`Error: ${data.message}`);
                    }
                })
                .catch(error => {
                    alert(`Error deleting device: ${error}`);
                });
            }
            
            function moveDevice(deviceName, direction, currentIndex) {
                // Get all device names in current order
                const devices = {{ devices | tojson }};
                const deviceNames = devices.map(d => d.device_name);
                
                // Swap positions
                const newIndex = currentIndex + direction;
                if (newIndex < 0 || newIndex >= deviceNames.length) return;
                
                [deviceNames[currentIndex], deviceNames[newIndex]] = [deviceNames[newIndex], deviceNames[currentIndex]];
                
                // Send new order to server
                fetch('/api/devices/reorder', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        devices: deviceNames
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    } else {
                        alert('Error reordering devices');
                    }
                })
                .catch(error => {
                    alert(`Error: ${error}`);
                });
            }
            
            // Close modal on Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    closeModal();
                }
            });
            
            // Close modal when clicking outside
            window.onclick = function(event) {
                const modal = document.getElementById('loginModal');
                if (event.target === modal) {
                    closeModal();
                }
            }
        </script>
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
    
    # Create dummy device with 90 days of data
    create_dummy_device()
    
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
