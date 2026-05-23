from flask import Flask, request, jsonify
from flask_cors import CORS
import time
import uuid
import sqlite3
import os
import base64
import threading

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scans.db")
FACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registered_faces")
os.makedirs(FACES_DIR, exist_ok=True)

# =========================
# DATABASE SETUP (with WAL and busy timeout)
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5 seconds if locked
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_scans (
            id TEXT PRIMARY KEY,
            member_id TEXT,
            timestamp REAL NOT NULL,
            image_base64 TEXT
        )
    ''')
    # Add column if upgrading an existing DB
    try:
        c.execute("ALTER TABLE pending_scans ADD COLUMN image_base64 TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS registered_faces (
            member_id TEXT PRIMARY KEY,
            image_path TEXT NOT NULL,
            registered_at REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# REGISTER FACE
# =========================
@app.route('/register', methods=['POST'])
def register_face():
    data = request.json or {}
    member_id = data.get("member_id")
    image_data = data.get("image")
    if not member_id or not image_data:
        return jsonify({"error": "member_id and image required"}), 400
    try:
        if "," in image_data:
            image_data = image_data.split(",")[1]
        image_bytes = base64.b64decode(image_data)
        image_path = os.path.join(FACES_DIR, f"{member_id}.jpg")
        with open(image_path, "wb") as f:
            f.write(image_bytes)
        conn = get_db()
        conn.execute('''
            INSERT OR REPLACE INTO registered_faces (member_id, image_path, registered_at)
            VALUES (?, ?, ?)
        ''', (member_id, image_path, time.time()))
        conn.commit()
        conn.close()
        print(f"📸 FACE REGISTERED: {member_id}")
        return jsonify({"success": True, "member_id": member_id})
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        return jsonify({"error": str(e)}), 500

# =========================
# ADD SCAN (with retry on lock)
# =========================
@app.route('/scan', methods=['POST'])
def receive_scan():
    data = request.json or {}
    member_id = data.get("member_id")
    image_base64 = data.get("image_base64")

    if member_id is None and not image_base64:
        return jsonify({"error": "image_base64 required for unknown scan"}), 400

    scan_id = str(uuid.uuid4())
    # Retry up to 3 times if database is locked
    for attempt in range(3):
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO pending_scans (id, member_id, timestamp, image_base64) VALUES (?, ?, ?, ?)",
                (scan_id, member_id, time.time(), image_base64)
            )
            conn.commit()
            conn.close()
            print(f"🔥 SCAN RECEIVED: {scan_id} | member={member_id}")
            return jsonify({"success": True, "scan_id": scan_id})
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 2:
                print(f"⚠️ DB locked, retry {attempt+1}/3")
                time.sleep(0.5 * (2 ** attempt))
                continue
            else:
                print(f"❌ Database error: {e}")
                return jsonify({"error": str(e)}), 500

# =========================
# POLL SCANS
# =========================
@app.route('/poll', methods=['GET'])
def poll_scans():
    last_timestamp = request.args.get('last_timestamp', type=float)
    last_id = request.args.get('last_id')
    if last_id is not None and last_timestamp is None:
        conn = get_db()
        row = conn.execute("SELECT timestamp FROM pending_scans WHERE id = ?", (last_id,)).fetchone()
        conn.close()
        if row:
            last_timestamp = row["timestamp"]
    conn = get_db()
    if last_timestamp is None:
        rows = conn.execute("SELECT * FROM pending_scans ORDER BY timestamp ASC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM pending_scans WHERE timestamp > ? ORDER BY timestamp ASC", (last_timestamp,)).fetchall()
    conn.close()
    scans = [dict(row) for row in rows]
    return jsonify({"scans": scans})

# =========================
# ACK SCAN
# =========================
@app.route('/ack', methods=['POST'])
def ack_scan():
    data = request.json or {}
    scan_id = data.get("scan_id")
    if not scan_id:
        return jsonify({"error": "scan_id required"}), 400
    conn = get_db()
    cur = conn.execute("DELETE FROM pending_scans WHERE id = ?", (scan_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    print(f"✅ ACK for {scan_id} – removed: {deleted}")
    return jsonify({"success": True})

# =========================
# DEBUG ENDPOINTS
# =========================
@app.route('/debug/pending', methods=['GET'])
def debug_pending():
    conn = get_db()
    rows = conn.execute("SELECT * FROM pending_scans ORDER BY timestamp ASC").fetchall()
    conn.close()
    return jsonify({
        "count": len(rows),
        "scans": [dict(r) for r in rows]
    })

@app.route('/debug/faces', methods=['GET'])
def debug_faces():
    conn = get_db()
    rows = conn.execute("SELECT * FROM registered_faces").fetchall()
    conn.close()
    return jsonify({
        "count": len(rows),
        "faces": [dict(r) for r in rows]
    })

@app.route('/test_unknown', methods=['GET'])
def test_unknown():
    dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    scan_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO pending_scans (id, member_id, timestamp, image_base64) VALUES (?, ?, ?, ?)",
        (scan_id, None, time.time(), dummy_b64)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "test unknown scan added", "scan_id": scan_id})

@app.route('/health', methods=['GET'])
def health():
    conn = get_db()
    pending = conn.execute("SELECT COUNT(*) as c FROM pending_scans").fetchone()["c"]
    faces = conn.execute("SELECT COUNT(*) as c FROM registered_faces").fetchone()["c"]
    conn.close()
    return jsonify({"status": "ok", "pending": pending, "registered_faces": faces})

# =========================
# CLEANUP OLD SCANS
# =========================
def cleanup_old_scans_loop():
    while True:
        time.sleep(3600)
        try:
            conn = get_db()
            cutoff = time.time() - 3600
            deleted = conn.execute("DELETE FROM pending_scans WHERE timestamp < ?", (cutoff,)).rowcount
            conn.commit()
            conn.close()
            if deleted:
                print(f"🧹 Cleaned up {deleted} old scans")
        except Exception as e:
            print(f"❌ Cleanup error: {e}")

# =========================
# START SERVER
# =========================
if __name__ == '__main__':
    init_db()
    print(f"🚀 Server starting. DB: {DB_PATH}")
    print(f"📸 Faces dir: {FACES_DIR}")
    threading.Thread(target=cleanup_old_scans_loop, daemon=True).start()
    # Use threaded=False to avoid concurrent writes (or keep True with retries)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)