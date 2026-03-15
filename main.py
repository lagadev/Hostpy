# ================================
# HOSTPY PRO BACKEND — REBUILT
# Flask + SQLite + Telebot
# Multi-User Bot Hosting System
# ================================

import os
import sys
import shutil
import zipfile
import subprocess
import sqlite3
import time
import re
import threading
import telebot
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ================= CONFIG =================

app = Flask(__name__)
CORS(app)

# Secret Key for Admin Broadcast (Matches Frontend)
ADMIN_SECRET_KEY = "l@g@" 
UPLOAD_FOLDER = "user_uploads"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "hostpy.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Dictionary to keep track of running bot processes
# Key: "username_appname", Value: subprocess.Popen object
running_processes = {}
server_start_time = time.time()

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Added 'email' column for frontend compatibility
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT,
        password TEXT,
        bot_token TEXT,
        chat_id TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ================= UTILITIES =================

def extract_token_from_code(path):
    """Detect Telegram Bot Token from Python code"""
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read()

        # Regex to find Telegram Bot Token
        pattern = r'\b\d{9,10}:[A-Za-z0-9_-]{30,40}\b'
        match = re.search(pattern, content)

        if match:
            return match.group(0)

    except Exception as e:
        print(f"[ERROR] Token extraction failed: {e}")

    return None


def find_main_py(folder):
    """Find main bot file (priority based)"""
    priority = ["main.py", "app.py", "bot.py", "run.py", "start.py"]

    for f in priority:
        p = os.path.join(folder, f)
        if os.path.exists(p):
            return p, folder

    # Fallback: search recursively
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".py"):
                return os.path.join(root, f), root

    return None, None

# ================= CHAT ID COLLECTOR =================

def collect_chat_id(username, token):
    """
    Background task to capture chat_id.
    User must send /start to their bot within 60 seconds.
    """
    try:
        bot = telebot.TeleBot(token)
        print(f"[BOT] Listening for /start from {username}...")

        for _ in range(12):  # 12 x 5 sec = 60 sec timeout
            try:
                updates = bot.get_updates(limit=1, timeout=10)
                
                if updates:
                    upd = updates[0]
                    if upd.message and upd.message.text == '/start':
                        chat_id = str(upd.message.chat.id)

                        conn = get_db()
                        conn.execute(
                            "UPDATE users SET chat_id=? WHERE username=?",
                            (chat_id, username)
                        )
                        conn.commit()
                        conn.close()

                        print(f"[SUCCESS] Chat ID saved for {username}: {chat_id}")
                        return # Done

            except Exception as e:
                print(f"ChatID Loop Error: {e}")

            time.sleep(5)

        print(f"[TIMEOUT] No /start received for {username}")

    except Exception as e:
        print(f"[CRITICAL] Failed to init bot for chat collection: {e}")

# ================= HOME =================

@app.route("/")
def home():
    return jsonify({
        "status": "Hostpy Backend Running",
        "uptime": int(time.time() - server_start_time),
        "version": "2.0"
    })

# ================= REGISTER =================

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    u = data.get("username")
    e = data.get("email")
    p = data.get("password")

    if not u or not p:
        return jsonify({"error": "Username and Password required"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, email, password, bot_token, chat_id) VALUES (?,?,?,?,?)",
            (u, e, generate_password_hash(p), "", "")
        )
        conn.commit()
        return jsonify({"message": "Registered Successfully"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 409
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500
    finally:
        conn.close()

# ================= LOGIN =================

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    u = data.get("username") # Frontend sends username (or email part)
    p = data.get("password")

    if not u or not p:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE username=?",
            (u,)
        ).fetchone()
        
        if user and check_password_hash(user["password"], p):
            return jsonify({"message": "Login success", "user": user["username"]})
        
        return jsonify({"error": "Invalid credentials"}), 401
    finally:
        conn.close()

# ================= UPLOAD BOT =================

@app.route("/upload", methods=["POST"])
def upload():
    username = request.form.get("username")
    file = request.files.get("file")

    if not username or not file:
        return jsonify({"error": "Missing data"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".zip", ".py"]:
        return jsonify({"error": "Invalid file type. Only .zip or .py"}), 400

    # Naming convention: filename becomes app name
    app_name = os.path.splitext(filename)[0]
    user_dir = os.path.join(UPLOAD_FOLDER, username, app_name)

    # Clean old files
    shutil.rmtree(user_dir, ignore_errors=True)
    os.makedirs(user_dir, exist_ok=True)

    save_path = os.path.join(user_dir, filename)
    file.save(save_path)

    token = None

    if ext == ".zip":
        try:
            with zipfile.ZipFile(save_path, "r") as z:
                z.extractall(user_dir)
            os.remove(save_path) # Remove zip after extraction

            main_file, _ = find_main_py(user_dir)
            if main_file:
                token = extract_token_from_code(main_file)
        except Exception as ex:
            return jsonify({"error": f"Extraction failed: {str(ex)}"}), 500
    else:
        # Single .py file
        token = extract_token_from_code(save_path)

    # Save token if found (Used for broadcasting)
    if token:
        conn = get_db()
        conn.execute(
            "UPDATE users SET bot_token=? WHERE username=?",
            (token, username)
        )
        conn.commit()
        conn.close()

    return jsonify({"message": "Upload successful", "token_found": bool(token)})

# ================= LIST APPS =================

@app.route("/my_apps", methods=["POST"])
def my_apps():
    username = request.json.get("username")
    user_path = os.path.join(UPLOAD_FOLDER, username)

    if not os.path.exists(user_path):
        return jsonify({"apps": []})

    apps = []

    for app_name in os.listdir(user_path):
        full_path = os.path.join(user_path, app_name)
        
        if os.path.isdir(full_path):
            pid_key = f"{username}_{app_name}"
            
            # Check if process is actually running
            proc = running_processes.get(pid_key)
            is_running = proc is not None and proc.poll() is None

            # Read logs
            log_file = os.path.join(full_path, "logs.txt")
            logs = ""
            if os.path.exists(log_file):
                with open(log_file, "r", errors="ignore") as f:
                    # Read last 3000 chars to prevent overload
                    logs = f.read()[-3000:]

            apps.append({
                "name": app_name,
                "running": is_running,
                "logs": logs
            })

    return jsonify({"apps": apps})

# ================= ACTION =================

@app.route("/action", methods=["POST"])
def action():
    data = request.json
    act = data.get("action")
    username = data.get("username")
    app_name = data.get("app_name")

    if not all([act, username, app_name]):
        return jsonify({"error": "Missing parameters"}), 400

    pid_key = f"{username}_{app_name}"
    app_dir = os.path.join(UPLOAD_FOLDER, username, app_name)

    # ---------- START ----------
    if act == "start":
        if pid_key in running_processes and running_processes[pid_key].poll() is None:
            return jsonify({"message": "Already running"})

        script, cwd = find_main_py(app_dir)

        if not script:
            return jsonify({"error": "No main Python file found"}), 404

        # Open log file in append mode
        try:
            log_f = open(os.path.join(app_dir, "logs.txt"), "a")
        except:
            log_f = None

        # Start Subprocess
        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.basename(script)],
            cwd=cwd,
            stdout=log_f,
            stderr=log_f,
            text=True
        )

        running_processes[pid_key] = proc

        # Try to extract token and start Chat ID collector thread
        token = extract_token_from_code(script)
        if token:
            # Save token to DB
            conn = get_db()
            conn.execute("UPDATE users SET bot_token=? WHERE username=?", (token, username))
            conn.commit()
            conn.close()
            
            # Start background thread
            threading.Thread(
                target=collect_chat_id,
                args=(username, token),
                daemon=True
            ).start()

        return jsonify({"message": "Bot started successfully"})

    # ---------- STOP ----------
    if act == "stop":
        if pid_key in running_processes:
            try:
                running_processes[pid_key].terminate()
                running_processes[pid_key].wait(timeout=5)
            except:
                running_processes[pid_key].kill()
            
            del running_processes[pid_key]
            return jsonify({"message": "Bot stopped"})
        return jsonify({"error": "Process not running"}), 400

    # ---------- DELETE ----------
    if act == "delete":
        if pid_key in running_processes:
            try:
                running_processes[pid_key].kill()
                del running_processes[pid_key]
            except: pass

        if os.path.exists(app_dir):
            shutil.rmtree(app_dir, ignore_errors=True)
            
        return jsonify({"message": "App deleted"})

    return jsonify({"error": "Invalid action"}), 400

# ================= BROADCAST =================

@app.route("/broadcast", methods=["POST"])
def broadcast():
    data = request.json

    # Security check
    if data.get("admin_key") != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized access"}), 403

    msg = data.get("message")
    img = data.get("image_url")
    btn_name = data.get("button_name")
    btn_url = data.get("button_url")

    if not msg:
        return jsonify({"error": "Message is empty"}), 400

    conn = get_db()
    users = conn.execute("SELECT bot_token, chat_id FROM users").fetchall()
    conn.close()

    if not users:
        return jsonify({"status": "No users to broadcast to"}), 200

    sent_count = 0

    def send_message(token, chat_id):
        nonlocal sent_count
        try:
            bot = telebot.TeleBot(token)
            
            markup = None
            if btn_name and btn_url:
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton(btn_name, url=btn_url))

            if img:
                bot.send_photo(chat_id, img, caption=msg, reply_markup=markup)
            else:
                bot.send_message(chat_id, msg, reply_markup=markup)
            
            print(f"[BCAST] Sent to {chat_id}")
            sent_count += 1
        except Exception as e:
            print(f"[BCAST FAIL] {chat_id}: {e}")

    threads = []
    for u in users:
        # Must have both token and chat_id
        if u["bot_token"] and u["chat_id"]:
            t = threading.Thread(target=send_message, args=(u["bot_token"], u["chat_id"]))
            t.start()
            threads.append(t)
            time.sleep(0.1) # Slight delay to prevent flooding

    # Wait for all threads to finish (optional, or return immediately)
    # return jsonify({"status": "Broadcast initiated", "targets": len(threads)})
    
    for t in threads:
        t.join(timeout=10)

    return jsonify({
        "status": "Broadcast completed",
        "sent_count": sent_count,
        "targets": len(threads)
    })

# ================= SERVER STATS =================

@app.route("/server_stats")
def stats():
    active_count = sum(1 for p in running_processes.values() if p.poll() is None)

    return jsonify({
        "uptime": int(time.time() - server_start_time),
        "active_bots": active_count
    })

# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)