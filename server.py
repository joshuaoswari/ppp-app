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
import requests

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
            display_order INTEGER DEFAULT 999,
            is_archived INTEGER DEFAULT 0
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
    
    # Login statistics table
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            mac_address TEXT,
            ip_address TEXT,
            country TEXT,
            region TEXT,
            city TEXT,
            latitude REAL,
            longitude REAL,
            isp TEXT,
            ping_ms INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_name) REFERENCES devices(device_name)
        )
    ''')

    # Index for faster queries
    c.execute('CREATE INDEX IF NOT EXISTS idx_device_name ON heartbeats(device_name)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON heartbeats(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_display_order ON devices(display_order)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_mac_address ON devices(mac_address)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_login_device ON login_statistics(device_name)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_login_timestamp ON login_statistics(timestamp)')

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

# ==================== GEOLOCATION HELPERS ====================

def get_client_ip():
    """Get the real client IP address from request"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr

def get_geolocation(ip_address):
    """Get geolocation data for an IP address using ip-api.com (free, no key needed)"""
    try:
        # Skip local IPs
        if ip_address in ['127.0.0.1', 'localhost', '::1'] or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            return {
                'country': 'Local Network',
                'region': 'N/A',
                'city': 'N/A',
                'latitude': None,
                'longitude': None,
                'isp': 'Local'
            }

        # Use ip-api.com free service (no API key required, 45 requests/minute limit)
        response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=3)

        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return {
                    'country': data.get('country', 'Unknown'),
                    'region': data.get('regionName', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'latitude': data.get('lat'),
                    'longitude': data.get('lon'),
                    'isp': data.get('isp', 'Unknown')
                }
    except Exception as e:
        print(f"⚠️  Geolocation lookup failed for {ip_address}: {str(e)}")

    # Return defaults if lookup fails
    return {
        'country': 'Unknown',
        'region': 'Unknown',
        'city': 'Unknown',
        'latitude': None,
        'longitude': None,
        'isp': 'Unknown'
    }

# ==================== API ENDPOINTS ====================

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """
    Receive heartbeat from client devices
    Expected JSON: {"device_name": "Branch01", "timestamp": "2025-11-10 10:30:00", "mac_address": "00:11:22:33:44:55", "ping_ms": 45}
    """
    try:
        request_start_time = datetime.now()
        data = request.get_json()

        if not data or 'device_name' not in data:
            return jsonify({"error": "device_name is required"}), 400

        device_name = data['device_name']
        mac_address = data.get('mac_address')
        client_timestamp = data.get('timestamp', datetime.now().isoformat())
        ping_ms = data.get('ping_ms')  # Client can send their measured ping

        # Get client IP and geolocation
        client_ip = get_client_ip()

        conn = get_db()
        c = conn.cursor()

        # Check if this is a new connection (device hasn't sent heartbeat in last 10 minutes)
        # This helps us distinguish logins from regular heartbeats
        c.execute('''
            SELECT last_seen FROM devices
            WHERE device_name = ?
        ''', (device_name,))
        result = c.fetchone()

        is_new_login = False
        if result:
            last_seen = datetime.fromisoformat(result['last_seen']) if result['last_seen'] else None
            if last_seen:
                time_since_last = (datetime.now() - last_seen).total_seconds() / 60
                # Consider it a new login if more than 10 minutes since last heartbeat
                is_new_login = time_since_last > 10
            else:
                is_new_login = True
        else:
            is_new_login = True  # First time seeing this device
        
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

        # Log login statistics if this is a new connection/login
        if is_new_login:
            # Get geolocation data
            geo_data = get_geolocation(client_ip)

            # Calculate server response time if not provided by client
            if not ping_ms:
                ping_ms = int((datetime.now() - request_start_time).total_seconds() * 1000)

            c.execute('''
                INSERT INTO login_statistics (
                    device_name, mac_address, ip_address, country, region, city,
                    latitude, longitude, isp, ping_ms, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                device_name,
                mac_address,
                client_ip,
                geo_data['country'],
                geo_data['region'],
                geo_data['city'],
                geo_data['latitude'],
                geo_data['longitude'],
                geo_data['isp'],
                ping_ms,
                datetime.now()
            ))

            print(f"📍 New login: {device_name} from {client_ip} ({geo_data['city']}, {geo_data['country']}) - {ping_ms}ms")

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "device_name": device_name,
            "server_time": datetime.now().isoformat(),
            "is_new_login": is_new_login
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

@app.route('/api/devices/archived', methods=['GET'])
def get_archived_devices():
    """API endpoint to get archived devices"""
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT * FROM devices WHERE is_archived = 1 ORDER BY device_name ASC')
        devices = c.fetchall()

        device_list = []
        for device in devices:
            device_list.append({
                "device_name": device['device_name'],
                "mac_address": device['mac_address'],
                "first_seen": device['first_seen'],
                "last_seen": device['last_seen'],
                "total_heartbeats": device['total_heartbeats']
            })

        conn.close()
        return jsonify({"devices": device_list, "total": len(device_list)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device/<device_name>', methods=['DELETE'])
def delete_device(device_name):
    """Archive a device (soft delete) - moves to archived section"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Mark device as archived instead of deleting
        c.execute('UPDATE devices SET is_archived = 1 WHERE device_name = ?', (device_name,))

        updated = c.rowcount
        conn.commit()
        conn.close()

        if updated > 0:
            return jsonify({"success": True, "message": f"Device '{device_name}' archived"}), 200
        else:
            return jsonify({"success": False, "message": "Device not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device/<device_name>/permanent', methods=['DELETE'])
def permanent_delete_device(device_name):
    """Permanently delete a device and all its data (cannot be undone)"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Delete heartbeats first (foreign key)
        c.execute('DELETE FROM heartbeats WHERE device_name = ?', (device_name,))

        # Delete login statistics
        c.execute('DELETE FROM login_statistics WHERE device_name = ?', (device_name,))

        # Delete device
        c.execute('DELETE FROM devices WHERE device_name = ?', (device_name,))

        deleted = c.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            return jsonify({"success": True, "message": f"Device '{device_name}' permanently deleted"}), 200
        else:
            return jsonify({"success": False, "message": "Device not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device/<device_name>/restore', methods=['POST'])
def restore_device(device_name):
    """Restore an archived device back to active status"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Mark device as not archived
        c.execute('UPDATE devices SET is_archived = 0 WHERE device_name = ?', (device_name,))

        updated = c.rowcount
        conn.commit()
        conn.close()

        if updated > 0:
            return jsonify({"success": True, "message": f"Device '{device_name}' restored"}), 200
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

@app.route('/api/device/<device_name>/statistics', methods=['GET'])
def get_device_statistics(device_name):
    """Get login statistics for a specific device"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Get statistics with limit (default to last 50 logins)
        limit = request.args.get('limit', 50, type=int)

        c.execute('''
            SELECT * FROM login_statistics
            WHERE device_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (device_name, limit))

        stats = c.fetchall()

        # Convert to list of dicts
        stats_list = []
        for stat in stats:
            stats_list.append({
                'id': stat['id'],
                'device_name': stat['device_name'],
                'mac_address': stat['mac_address'],
                'ip_address': stat['ip_address'],
                'country': stat['country'],
                'region': stat['region'],
                'city': stat['city'],
                'latitude': stat['latitude'],
                'longitude': stat['longitude'],
                'isp': stat['isp'],
                'ping_ms': stat['ping_ms'],
                'timestamp': stat['timestamp']
            })

        # Calculate statistics summary
        if stats_list:
            avg_ping = sum(s['ping_ms'] for s in stats_list if s['ping_ms']) / len([s for s in stats_list if s['ping_ms']]) if any(s['ping_ms'] for s in stats_list) else 0
            unique_ips = len(set(s['ip_address'] for s in stats_list))
            unique_locations = len(set(f"{s['city']}, {s['country']}" for s in stats_list))
            most_common_location = max(set(f"{s['city']}, {s['country']}" for s in stats_list), key=lambda x: sum(1 for s in stats_list if f"{s['city']}, {s['country']}" == x))
        else:
            avg_ping = 0
            unique_ips = 0
            unique_locations = 0
            most_common_location = "N/A"

        conn.close()

        return jsonify({
            "device_name": device_name,
            "total_logins": len(stats_list),
            "statistics": stats_list,
            "summary": {
                "average_ping_ms": round(avg_ping, 1),
                "unique_ips": unique_ips,
                "unique_locations": unique_locations,
                "most_common_location": most_common_location
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/statistics/recent', methods=['GET'])
def get_recent_statistics():
    """Get recent login statistics across all devices"""
    try:
        conn = get_db()
        c = conn.cursor()

        limit = request.args.get('limit', 20, type=int)

        c.execute('''
            SELECT * FROM login_statistics
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))

        stats = c.fetchall()

        stats_list = []
        for stat in stats:
            stats_list.append({
                'device_name': stat['device_name'],
                'mac_address': stat['mac_address'],
                'ip_address': stat['ip_address'],
                'location': f"{stat['city']}, {stat['region']}, {stat['country']}",
                'isp': stat['isp'],
                'ping_ms': stat['ping_ms'],
                'timestamp': stat['timestamp']
            })

        conn.close()

        return jsonify({
            "recent_logins": stats_list,
            "total": len(stats_list)
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== DEVICE STATUS LOGIC ====================

def get_all_devices_status(include_archived=False):
    """Get status of all devices with online/offline state and uptime"""
    conn = get_db()
    c = conn.cursor()

    if include_archived:
        c.execute('SELECT * FROM devices ORDER BY display_order ASC, device_name ASC')
    else:
        c.execute('SELECT * FROM devices WHERE is_archived = 0 ORDER BY display_order ASC, device_name ASC')
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
                background: #f59e0b;
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
                background: #d97706;
            }

            .permanent-delete-btn {
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

            .permanent-delete-btn:hover {
                background: #dc2626;
            }

            .restore-btn {
                background: #10b981;
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

            .restore-btn:hover {
                background: #059669;
            }

            .archived-section {
                margin-top: 40px;
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                padding: 30px;
            }

            .section-header {
                font-size: 1.5em;
                color: #333;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .toggle-section-btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.85em;
                font-weight: 600;
                transition: background 0.3s;
            }

            .toggle-section-btn:hover {
                background: #5568d3;
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

            /* Statistics Display */
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 25px;
            }

            .stats-card-small {
                background: #f3f4f6;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }

            .stats-card-small .stat-value {
                font-size: 2em;
                font-weight: bold;
                color: #667eea;
                margin-bottom: 5px;
            }

            .stats-card-small .stat-label {
                color: #666;
                font-size: 0.9em;
            }

            .statistics-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
                font-size: 0.9em;
            }

            .statistics-table th {
                background: #f3f4f6;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #e5e7eb;
            }

            .statistics-table td {
                padding: 10px 12px;
                border-bottom: 1px solid #e5e7eb;
            }

            .statistics-table tr:hover {
                background: #f9fafb;
            }

            .ping-badge {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: 600;
                font-size: 0.85em;
            }

            .ping-good {
                background: #d1fae5;
                color: #065f46;
            }

            .ping-medium {
                background: #fef3c7;
                color: #92400e;
            }

            .ping-bad {
                background: #fee2e2;
                color: #991b1b;
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
                <button id="logoutBtn" onclick="handleLogout(event)" style="display: none; position: absolute; top: 20px; right: 20px; padding: 8px 16px; background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3); color: white; border-radius: 4px; cursor: pointer; font-size: 14px;">🔓 Logout</button>
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
                            <th id="stats-header" style="display:none;">Login Stats</th>
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
                                <td class="stats-actions" style="display:none;">
                                    <button class="expand-btn" onclick="showStatistics('{{ device.device_name }}')">View Stats 📊</button>
                                </td>
                                <td class="admin-actions" style="display:none;">
                                    <div class="reorder-controls">
                                        <span class="order-number">{{ loop.index }}</span>
                                        <button class="reorder-btn" onclick="moveDevice('{{ device.device_name }}', -1, {{ loop.index0 }})" {{ 'disabled' if loop.first else '' }}>↑</button>
                                        <button class="reorder-btn" onclick="moveDevice('{{ device.device_name }}', 1, {{ loop.index0 }})" {{ 'disabled' if loop.last else '' }}>↓</button>
                                        <button class="delete-btn" onclick="archiveDevice('{{ device.device_name }}')">Archive</button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="7" style="text-align: center; padding: 40px; color: #999;">
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

            <!-- Archived Devices Section -->
            <div class="archived-section" id="archivedSection" style="display:none;">
                <div class="section-header">
                    📦 Archived Devices
                    <button class="toggle-section-btn" onclick="toggleArchivedSection()">Hide</button>
                </div>
                <div id="archivedDevicesContent">
                    <p style="color: #666;">Loading archived devices...</p>
                </div>
            </div>

            <!-- Show Archived Button (only visible in admin mode) -->
            <div style="text-align: center; margin-top: 20px;" id="showArchivedBtn" class="admin-actions" style="display:none;">
                <button class="toggle-section-btn" onclick="toggleArchivedSection()">Show Archived Devices</button>
            </div>
        </div>
        
        <!-- Statistics Modal -->
        <div id="statisticsModal" class="modal">
            <div class="modal-content" style="max-width: 900px;">
                <div class="modal-header">
                    <h2 id="statsDeviceName">📊 Login Statistics</h2>
                    <p id="statsSummary">Loading statistics...</p>
                </div>
                <button class="close-expanded" onclick="closeStatisticsModal()" style="position: absolute; top: 15px; right: 15px;">×</button>

                <div id="statisticsContent">
                    <div style="text-align: center; padding: 40px; color: #999;">
                        Loading...
                    </div>
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

            // Auto-refresh every 30 seconds (preserves admin mode via localStorage)
            setTimeout(() => {
                location.reload();
            }, 30000);

            // Load admin mode from localStorage on page load
            window.addEventListener('DOMContentLoaded', () => {
                // Check if admin mode was previously enabled
                const savedAdminMode = localStorage.getItem('heartbeat_admin_mode');
                if (savedAdminMode === 'true') {
                    isAdminMode = true;
                    enableAdminMode();
                }

                // Load uptime blocks for all devices
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
                    // Save admin mode to localStorage so it persists across page refreshes
                    localStorage.setItem('heartbeat_admin_mode', 'true');
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
                // Show stats column header
                document.getElementById('stats-header').style.display = 'table-cell';

                // Show admin column header
                document.getElementById('admin-header').style.display = 'table-cell';

                // Show all stats buttons
                const statsActions = document.querySelectorAll('.stats-actions');
                statsActions.forEach(action => {
                    action.style.display = 'table-cell';
                });

                // Show all admin action buttons
                const adminActions = document.querySelectorAll('.admin-actions');
                adminActions.forEach(action => {
                    action.style.display = 'table-cell';
                });

                // Show archived section button
                const showArchivedBtn = document.getElementById('showArchivedBtn');
                if (showArchivedBtn) {
                    showArchivedBtn.style.display = 'block';
                }

                // Show logout button
                document.getElementById('logoutBtn').style.display = 'block';

                // Change header color slightly to indicate admin mode
                document.getElementById('header').style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
                document.querySelector('h1').style.color = 'white';
                document.querySelector('.subtitle').style.color = 'rgba(255,255,255,0.9)';
            }

            function handleLogout(event) {
                event.stopPropagation(); // Prevent header click from triggering
                if (confirm('Logout from admin mode?')) {
                    // Clear admin mode from localStorage
                    localStorage.removeItem('heartbeat_admin_mode');
                    // Reload page to exit admin mode
                    location.reload();
                }
            }
            
            function archiveDevice(deviceName) {
                if (!confirm(`Archive "${deviceName}"?\\n\\nThe device will be moved to the archived section and can be restored later.`)) {
                    return;
                }

                fetch(`/api/device/${encodeURIComponent(deviceName)}`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(`Device "${deviceName}" archived successfully!`);
                        location.reload();
                    } else {
                        alert(`Error: ${data.message}`);
                    }
                })
                .catch(error => {
                    alert(`Error archiving device: ${error}`);
                });
            }

            function restoreDevice(deviceName) {
                if (!confirm(`Restore "${deviceName}"?\\n\\nThe device will be moved back to active devices.`)) {
                    return;
                }

                fetch(`/api/device/${encodeURIComponent(deviceName)}/restore`, {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(`Device "${deviceName}" restored successfully!`);
                        location.reload();
                    } else {
                        alert(`Error: ${data.message}`);
                    }
                })
                .catch(error => {
                    alert(`Error restoring device: ${error}`);
                });
            }

            function permanentDeleteDevice(deviceName) {
                if (!confirm(`⚠️ PERMANENTLY DELETE "${deviceName}"?\\n\\nThis will PERMANENTLY remove the device and ALL its data including heartbeat history and login statistics.\\n\\nThis action CANNOT be undone!\\n\\nType the device name to confirm.`)) {
                    return;
                }

                const confirmation = prompt(`Type "${deviceName}" to confirm permanent deletion:`);
                if (confirmation !== deviceName) {
                    alert('Deletion cancelled - device name did not match.');
                    return;
                }

                fetch(`/api/device/${encodeURIComponent(deviceName)}/permanent`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(`Device "${deviceName}" permanently deleted!`);
                        location.reload();
                    } else {
                        alert(`Error: ${data.message}`);
                    }
                })
                .catch(error => {
                    alert(`Error deleting device: ${error}`);
                });
            }

            function toggleArchivedSection() {
                const section = document.getElementById('archivedSection');
                const btn = document.getElementById('showArchivedBtn');

                if (section.style.display === 'none') {
                    section.style.display = 'block';
                    if (btn) btn.style.display = 'none';
                    loadArchivedDevices();
                } else {
                    section.style.display = 'none';
                    if (btn) btn.style.display = 'block';
                }
            }

            function loadArchivedDevices() {
                fetch('/api/devices/archived')
                    .then(response => response.json())
                    .then(data => {
                        const content = document.getElementById('archivedDevicesContent');

                        if (data.total === 0) {
                            content.innerHTML = '<p style="color: #999; text-align: center; padding: 20px;">No archived devices</p>';
                            return;
                        }

                        let html = `
                            <table style="width: 100%; border-collapse: collapse;">
                                <thead style="background: #f3f4f6;">
                                    <tr>
                                        <th style="padding: 12px; text-align: left;">Device Name</th>
                                        <th style="padding: 12px; text-align: left;">MAC Address</th>
                                        <th style="padding: 12px; text-align: left;">First Seen</th>
                                        <th style="padding: 12px; text-align: left;">Last Seen</th>
                                        <th style="padding: 12px; text-align: left;">Total Heartbeats</th>
                                        <th style="padding: 12px; text-align: left;">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                        `;

                        data.devices.forEach(device => {
                            const mac = device.mac_address || 'N/A';
                            html += `
                                <tr style="border-bottom: 1px solid #e5e7eb;">
                                    <td style="padding: 12px;"><strong>${device.device_name}</strong></td>
                                    <td style="padding: 12px;"><code>${mac}</code></td>
                                    <td style="padding: 12px;">${device.first_seen}</td>
                                    <td style="padding: 12px;">${device.last_seen}</td>
                                    <td style="padding: 12px;">${device.total_heartbeats.toLocaleString()}</td>
                                    <td style="padding: 12px;">
                                        <button class="restore-btn" onclick="restoreDevice('${device.device_name}')">Restore</button>
                                        <button class="permanent-delete-btn" onclick="permanentDeleteDevice('${device.device_name}')">Delete Forever</button>
                                    </td>
                                </tr>
                            `;
                        });

                        html += `
                                </tbody>
                            </table>
                        `;

                        content.innerHTML = html;
                    })
                    .catch(error => {
                        console.error('Error loading archived devices:', error);
                        document.getElementById('archivedDevicesContent').innerHTML =
                            '<p style="color: #ef4444;">Error loading archived devices</p>';
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
                const loginModal = document.getElementById('loginModal');
                const statsModal = document.getElementById('statisticsModal');
                if (event.target === loginModal) {
                    closeModal();
                } else if (event.target === statsModal) {
                    closeStatisticsModal();
                }
            }

            // Statistics Modal Functions
            function showStatistics(deviceName) {
                document.getElementById('statisticsModal').style.display = 'block';
                document.getElementById('statsDeviceName').textContent = `📊 Login Statistics - ${deviceName}`;
                document.getElementById('statsSummary').textContent = 'Loading statistics...';
                document.getElementById('statisticsContent').innerHTML = '<div style="text-align: center; padding: 40px; color: #999;">Loading...</div>';

                // Fetch statistics
                fetch(`/api/device/${encodeURIComponent(deviceName)}/statistics`)
                    .then(response => response.json())
                    .then(data => {
                        displayStatistics(data);
                    })
                    .catch(error => {
                        document.getElementById('statisticsContent').innerHTML =
                            '<div style="text-align: center; padding: 40px; color: #ef4444;">Error loading statistics</div>';
                        console.error('Error fetching statistics:', error);
                    });
            }

            function closeStatisticsModal() {
                document.getElementById('statisticsModal').style.display = 'none';
            }

            function displayStatistics(data) {
                if (data.total_logins === 0) {
                    document.getElementById('statisticsContent').innerHTML =
                        '<div style="text-align: center; padding: 40px; color: #999;">No login statistics available yet.</div>';
                    return;
                }

                // Update summary
                document.getElementById('statsSummary').textContent =
                    `${data.total_logins} total logins tracked`;

                // Build summary cards
                let html = `
                    <div class="stats-grid">
                        <div class="stats-card-small">
                            <div class="stat-value">${data.total_logins}</div>
                            <div class="stat-label">Total Logins</div>
                        </div>
                        <div class="stats-card-small">
                            <div class="stat-value">${data.summary.average_ping_ms} ms</div>
                            <div class="stat-label">Avg Ping</div>
                        </div>
                        <div class="stats-card-small">
                            <div class="stat-value">${data.summary.unique_ips}</div>
                            <div class="stat-label">Unique IPs</div>
                        </div>
                        <div class="stats-card-small">
                            <div class="stat-value">${data.summary.unique_locations}</div>
                            <div class="stat-label">Locations</div>
                        </div>
                    </div>

                    <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                        <strong>Most Common Location:</strong> ${data.summary.most_common_location}
                    </div>

                    <h3 style="margin-bottom: 15px; color: #333;">Recent Logins</h3>
                    <table class="statistics-table">
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>IP Address</th>
                                <th>Location</th>
                                <th>ISP</th>
                                <th>MAC Address</th>
                                <th>Ping</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                // Add rows
                data.statistics.forEach(stat => {
                    const timestamp = new Date(stat.timestamp).toLocaleString();
                    const location = `${stat.city}, ${stat.region}, ${stat.country}`;
                    const mac = stat.mac_address || 'N/A';

                    // Determine ping badge class
                    let pingClass = 'ping-good';
                    if (stat.ping_ms > 100) pingClass = 'ping-medium';
                    if (stat.ping_ms > 200) pingClass = 'ping-bad';

                    html += `
                        <tr>
                            <td>${timestamp}</td>
                            <td><code>${stat.ip_address}</code></td>
                            <td>${location}</td>
                            <td>${stat.isp}</td>
                            <td><code style="font-size: 0.85em;">${mac}</code></td>
                            <td><span class="ping-badge ${pingClass}">${stat.ping_ms} ms</span></td>
                        </tr>
                    `;
                });

                html += `
                        </tbody>
                    </table>
                `;

                document.getElementById('statisticsContent').innerHTML = html;
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
