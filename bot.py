# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════╗
║        RS HOSTING BOT  —  by RS WONER           ║
║   Ultra-Professional Telegram Bot Hosting        ║
║   t.me/rs_woner  |  t.me/CARTOONFUNNY03         ║
╚══════════════════════════════════════════════════╝

Features:
  • Per-bot isolated venv  (no dependency conflicts)
  • Per-bot unique UUID folder  (safe delete)
  • Auto import scan → auto pip install
  • requirements.txt support inside ZIP
  • Persistent logs per bot  (live view)
  • Same-name file conflict handling
  • Crash-proof: hosted bots never crash the host bot
  • Profile photo welcome message
  • Polling mode (Termux / VPS)
"""

# ── Standard library ──────────────────────────────────────────────────────────
import os, sys, re, ast, json, uuid, time, shutil, zipfile
import sqlite3, logging, threading, tempfile, subprocess, atexit
from datetime import datetime, timedelta

# ── Third-party ───────────────────────────────────────────────────────────────
import requests
import psutil
import telebot
from telebot import types

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG  —  edit these or set as environment variables
# ══════════════════════════════════════════════════════════════════════════════
TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "6621572366"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6621572366"))
YOUR_USERNAME = os.environ.get("OWNER_USERNAME", "@rs_woner")
UPDATE_CHANNEL = "https://t.me/CARTOONFUNNY03"

FREE_LIMIT     = 1
PREMIUM_LIMIT  = 20
ADMIN_LIMIT    = 100
MAX_FILE_MB    = 30

# ══════════════════════════════════════════════════════════════════════════════
#  DIRECTORY LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
BASE   = os.path.abspath(os.path.dirname(__file__))
BOTS   = os.path.join(BASE, "bots")    # bots/<user_id>/<uid>/
DATA   = os.path.join(BASE, "data")    # data/db.sqlite
LOGS   = os.path.join(BASE, "logs")    # logs/<uid>.log

for _d in (BOTS, DATA, LOGS):
    os.makedirs(_d, exist_ok=True)

DB_PATH = os.path.join(DATA, "db.sqlite")

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOGS, "host.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("RSHOST")

# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════════════════════════════════════
_bot_locked        = False          # use getter/setter — avoids global-after-use
_instances: dict   = {}             # uid → {process, log_file, ...}
_admin_ids: set    = {OWNER_ID, ADMIN_ID}
_subscriptions: dict = {}           # user_id → expiry datetime
_active_users: set = set()
_DB_LOCK           = threading.Lock()
_THREAD_SEM        = threading.Semaphore(8)   # max 8 concurrent start-up threads

def is_locked() -> bool:   return _bot_locked
def set_locked(v: bool):
    global _bot_locked
    _bot_locked = v

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════════════════
def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bots (
                uid          TEXT PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                bot_folder   TEXT NOT NULL,
                main_script  TEXT NOT NULL,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subs (
                user_id INTEGER PRIMARY KEY,
                expiry  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            );
        """)
        c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (ADMIN_ID,))

def load_db():
    with _db() as c:
        for r in c.execute("SELECT user_id, expiry FROM subs"):
            try:
                _subscriptions[r["user_id"]] = datetime.fromisoformat(r["expiry"])
            except Exception:
                pass
        _active_users.update(r["user_id"] for r in c.execute("SELECT user_id FROM users"))
        _admin_ids.update(r["user_id"] for r in c.execute("SELECT user_id FROM admins"))
    logger.info(f"DB loaded — users:{len(_active_users)} subs:{len(_subscriptions)} admins:{len(_admin_ids)}")

def _db_exec(sql, params=()):
    with _DB_LOCK:
        with _db() as c:
            c.execute(sql, params)

# ── bot registry ──────────────────────────────────────────────────────────────
def db_add_bot(uid, user_id, display_name, folder, main):
    _db_exec(
        "INSERT OR REPLACE INTO bots VALUES (?,?,?,?,?,?)",
        (uid, user_id, display_name, folder, main, datetime.now().isoformat()),
    )

def db_del_bot(uid):
    _db_exec("DELETE FROM bots WHERE uid=?", (uid,))

def db_get_bot(uid):
    with _db() as c:
        return c.execute("SELECT * FROM bots WHERE uid=?", (uid,)).fetchone()

def db_user_bots(user_id):
    with _db() as c:
        return c.execute(
            "SELECT * FROM bots WHERE user_id=? ORDER BY created_at", (user_id,)
        ).fetchall()

def db_all_bots():
    with _db() as c:
        return c.execute("SELECT * FROM bots").fetchall()

# ── users / admins / subs ─────────────────────────────────────────────────────
def db_add_user(user_id):
    _active_users.add(user_id)
    _db_exec("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))

def db_add_admin(aid):
    _admin_ids.add(aid)
    _db_exec("INSERT OR IGNORE INTO admins VALUES (?)", (aid,))

def db_del_admin(aid):
    if aid == OWNER_ID:
        return False
    _admin_ids.discard(aid)
    _db_exec("DELETE FROM admins WHERE user_id=?", (aid,))
    return True

def db_add_sub(user_id, expiry: datetime):
    _subscriptions[user_id] = expiry
    _db_exec("INSERT OR REPLACE INTO subs VALUES (?,?)", (user_id, expiry.isoformat()))

def db_del_sub(user_id):
    _subscriptions.pop(user_id, None)
    _db_exec("DELETE FROM subs WHERE user_id=?", (user_id,))

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def user_limit(uid) -> float:
    if uid == OWNER_ID:       return float("inf")
    if uid in _admin_ids:     return ADMIN_LIMIT
    exp = _subscriptions.get(uid)
    if exp and exp > datetime.now(): return PREMIUM_LIMIT
    return FREE_LIMIT

def user_status(uid) -> str:
    if uid == OWNER_ID:   return "👑 Owner"
    if uid in _admin_ids: return "🛡️ Admin"
    exp = _subscriptions.get(uid)
    if exp and exp > datetime.now(): return "⭐ Premium"
    return "🆓 Free"

def sub_info(uid) -> str:
    exp = _subscriptions.get(uid)
    if exp and exp > datetime.now():
        days = (exp - datetime.now()).days
        return f"\n⏳ Premium expires in {days} day(s)"
    return ""

def unique_name(user_id, fname) -> str:
    existing = {r["display_name"] for r in db_user_bots(user_id)}
    base, ext = os.path.splitext(fname)
    if fname not in existing:
        return fname
    i = 2
    while f"{base}_{i}{ext}" in existing:
        i += 1
    return f"{base}_{i}{ext}"

def bot_folder(user_id, uid) -> str:
    p = os.path.join(BOTS, str(user_id), uid)
    os.makedirs(p, exist_ok=True)
    return p

def venv_py(folder) -> str:
    """Return path to venv python inside bot folder."""
    return os.path.join(folder, ".venv",
                        "Scripts" if sys.platform == "win32" else "bin",
                        "python.exe" if sys.platform == "win32" else "python")

def log_path(uid) -> str:
    return os.path.join(LOGS, f"{uid}.log")

def is_running(uid) -> bool:
    info = _instances.get(uid)
    if not info:
        return False
    proc = info.get("process")
    if not proc:
        return False
    try:
        p = psutil.Process(proc.pid)
        ok = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        if not ok:
            _cleanup(uid)
        return ok
    except psutil.NoSuchProcess:
        _cleanup(uid)
        return False
    except Exception:
        return False

def _cleanup(uid):
    info = _instances.pop(uid, None)
    if info:
        lf = info.get("log_file")
        if lf and not getattr(lf, "closed", True):
            try: lf.close()
            except Exception: pass

def kill_bot(uid):
    info = _instances.get(uid)
    if not info:
        return
    lf = info.get("log_file")
    if lf and not getattr(lf, "closed", True):
        try: lf.close()
        except Exception: pass
    proc = info.get("process")
    if proc:
        try:
            parent = psutil.Process(proc.pid)
            for ch in parent.children(recursive=True):
                try: ch.kill()
                except Exception: pass
            parent.kill()
        except Exception:
            pass
    _instances.pop(uid, None)

def tail_log(uid, n=60) -> str:
    lp = log_path(uid)
    if not os.path.exists(lp):
        return "(No log yet)"
    try:
        size = os.path.getsize(lp)
        if size == 0:
            return "(Log is empty)"
        with open(lp, "rb") as f:
            f.seek(max(0, size - 10240))
            raw = f.read()
        text   = raw.decode("utf-8", errors="ignore")
        lines  = text.splitlines()
        return "\n".join(lines[-n:]) or "(Empty)"
    except Exception as e:
        return f"(Log read error: {e})"

def safe_send(chat_id, text, **kw):
    """Send message without raising — used inside threads."""
    try:
        bot.send_message(chat_id, text, **kw)
    except Exception as e:
        logger.warning(f"safe_send failed: {e}")

def safe_reply(msg, text, **kw):
    try:
        bot.reply_to(msg, text, **kw)
    except Exception as e:
        logger.warning(f"safe_reply failed: {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  AUTO IMPORT DETECTION
# ══════════════════════════════════════════════════════════════════════════════
IMPORT_MAP = {
    # Telegram
    "telebot":           "pyTelegramBotAPI",
    "telegram":          "python-telegram-bot",
    "pyrogram":          "pyrogram",
    "telethon":          "telethon",
    "aiogram":           "aiogram",
    "tgcrypto":          "tgcrypto",
    # HTTP / Web
    "requests":          "requests",
    "httpx":             "httpx",
    "aiohttp":           "aiohttp",
    "flask":             "Flask",
    "fastapi":           "fastapi",
    "uvicorn":           "uvicorn",
    "django":            "Django",
    # Scraping / parsing
    "bs4":               "beautifulsoup4",
    "lxml":              "lxml",
    "yaml":              "PyYAML",
    "toml":              "toml",
    "dotenv":            "python-dotenv",
    # Media
    "PIL":               "Pillow",
    "cv2":               "opencv-python",
    "ffmpeg":            "ffmpeg-python",
    "yt_dlp":            "yt-dlp",
    "pytube":            "pytube",
    # Data
    "numpy":             "numpy",
    "pandas":            "pandas",
    "scipy":             "scipy",
    "sklearn":           "scikit-learn",
    "matplotlib":        "matplotlib",
    # DB
    "pymongo":           "pymongo",
    "motor":             "motor",
    "redis":             "redis",
    "sqlalchemy":        "SQLAlchemy",
    "pymysql":           "PyMySQL",
    "psycopg2":          "psycopg2-binary",
    "firebase_admin":    "firebase-admin",
    # Utils
    "psutil":            "psutil",
    "dateutil":          "python-dateutil",
    "pytz":              "pytz",
    "rich":              "rich",
    "tqdm":              "tqdm",
    "click":             "click",
    "pydantic":          "pydantic",
    "cryptography":      "cryptography",
    "jwt":               "PyJWT",
    "googletrans":       "googletrans==4.0.0rc1",
    "colorama":          "colorama",
    # Stdlib → skip (None)
    "os":None,"sys":None,"re":None,"json":None,"time":None,
    "math":None,"random":None,"datetime":None,"logging":None,
    "threading":None,"subprocess":None,"zipfile":None,"tempfile":None,
    "shutil":None,"sqlite3":None,"asyncio":None,"io":None,
    "pathlib":None,"collections":None,"itertools":None,"functools":None,
    "typing":None,"enum":None,"abc":None,"copy":None,"uuid":None,
    "hashlib":None,"hmac":None,"base64":None,"struct":None,
    "socket":None,"ssl":None,"http":None,"urllib":None,
    "email":None,"html":None,"xml":None,"csv":None,
    "configparser":None,"argparse":None,"traceback":None,
    "inspect":None,"operator":None,"contextlib":None,
    "gc":None,"signal":None,"atexit":None,"warnings":None,
    "string":None,"textwrap":None,"queue":None,
    "multiprocessing":None,"concurrent":None,"pprint":None,
    "dataclasses":None,"ast":None,"dis":None,"token":None,
}

def scan_imports(code: str) -> set:
    names = set()
    try:
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
    except SyntaxError:
        for ln in code.splitlines():
            m = re.match(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", ln)
            if m:
                names.add(m.group(1))
    return names

def imports_to_packages(names: set) -> list:
    pkgs = []
    for n in names:
        if n in IMPORT_MAP:
            p = IMPORT_MAP[n]
            if p:
                pkgs.append(p)
        # unknown → skip (don't guess)
    return list(set(pkgs))

def venv_installed(py: str) -> set:
    try:
        r = subprocess.run([py, "-m", "pip", "list", "--format=json"],
                           capture_output=True, text=True, timeout=20)
        return {p["name"].lower().replace("-","_") for p in json.loads(r.stdout)}
    except Exception:
        return set()

def pip_install(py: str, packages: list, folder: str) -> tuple:
    """Install packages into venv. Returns (success, failed_list)."""
    failed = []
    for pkg in packages:
        try:
            r = subprocess.run(
                [py, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"],
                capture_output=True, text=True, timeout=300, cwd=folder
            )
            if r.returncode != 0:
                with open(os.path.join(folder, "install.log"), "a") as lf:
                    lf.write(f"\n[FAIL] {pkg}\n{r.stderr}\n")
                failed.append(pkg)
        except subprocess.TimeoutExpired:
            failed.append(pkg)
        except Exception as e:
            logger.error(f"pip install {pkg}: {e}")
            failed.append(pkg)
    return len(failed) == 0, failed

def pip_requirements(py: str, req: str, folder: str) -> tuple:
    try:
        r = subprocess.run(
            [py, "-m", "pip", "install", "-r", req, "--quiet", "--no-warn-script-location"],
            capture_output=True, text=True, timeout=600, cwd=folder
        )
        with open(os.path.join(folder, "install.log"), "a") as lf:
            lf.write(f"\n[requirements.txt]\n{r.stdout}\n{r.stderr}\n")
        return r.returncode == 0, r.stderr[-500:]
    except subprocess.TimeoutExpired:
        return False, "Timeout (>10 min)"
    except Exception as e:
        return False, str(e)

# ══════════════════════════════════════════════════════════════════════════════
#  VENV CREATION
# ══════════════════════════════════════════════════════════════════════════════
def ensure_venv(folder: str) -> str:
    """Create venv if missing. Return python path."""
    venv_dir = os.path.join(folder, ".venv")
    py       = venv_py(folder)
    if not os.path.exists(py):
        logger.info(f"Creating venv in {folder}")
        subprocess.run(
            [sys.executable, "-m", "venv", venv_dir, "--clear"],
            check=True, timeout=120, capture_output=True
        )
        subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"],
                       capture_output=True, timeout=60)
    return py

# ══════════════════════════════════════════════════════════════════════════════
#  CRASH-PROOF BOT RUNNER
# ══════════════════════════════════════════════════════════════════════════════
def run_bot(uid: str, user_id: int, folder: str, main: str,
            notify_chat: int, attempt: int = 1):
    """
    Full pipeline inside a daemon thread.
    ALL exceptions are caught — this function NEVER crashes the host bot.
    """
    MAX_ATTEMPTS = 2
    script = os.path.join(folder, main)

    with _THREAD_SEM:   # limit concurrent launches
        try:
            # ── sanity check ──────────────────────────────────────────────────
            if not os.path.exists(script):
                safe_send(notify_chat, f"❌ Script `{main}` not found. Please re-upload.", parse_mode="Markdown")
                db_del_bot(uid)
                return

            # ── create venv ───────────────────────────────────────────────────
            try:
                py = ensure_venv(folder)
            except Exception as e:
                safe_send(notify_chat, f"❌ Could not create virtualenv:\n`{e}`", parse_mode="Markdown")
                return

            # ── requirements.txt ──────────────────────────────────────────────
            req = os.path.join(folder, "requirements.txt")
            if os.path.exists(req):
                safe_send(notify_chat, "📦 Installing `requirements.txt`...", parse_mode="Markdown")
                ok, err = pip_requirements(py, req, folder)
                if ok:
                    safe_send(notify_chat, "✅ `requirements.txt` installed.", parse_mode="Markdown")
                else:
                    safe_send(notify_chat,
                        f"⚠️ Some packages failed:\n```\n{err}\n```\nContinuing...",
                        parse_mode="Markdown")

            # ── auto import scan ──────────────────────────────────────────────
            try:
                with open(script, "r", encoding="utf-8", errors="ignore") as f:
                    code = f.read()
                names  = scan_imports(code)
                pkgs   = imports_to_packages(names)
                done   = venv_installed(py)
                needed = [p for p in pkgs
                          if p.split("==")[0].lower().replace("-","_") not in done]
                if needed:
                    safe_send(notify_chat,
                        f"🔍 Auto-installing {len(needed)} package(s):\n`{'`, `'.join(needed)}`",
                        parse_mode="Markdown")
                    ok, failed = pip_install(py, needed, folder)
                    if failed:
                        safe_send(notify_chat,
                            f"⚠️ Could not install: `{'`, `'.join(failed)}`",
                            parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Import scan error uid={uid}: {e}")

            # ── pre-check (8 s timeout) ───────────────────────────────────────
            if attempt == 1:
                try:
                    chk = subprocess.run(
                        [py, script],
                        capture_output=True, text=True,
                        timeout=8, cwd=folder,
                        encoding="utf-8", errors="ignore"
                    )
                    if chk.returncode != 0 and chk.stderr:
                        m = re.search(r"ModuleNotFoundError: No module named '([^']+)'", chk.stderr)
                        if m and attempt < MAX_ATTEMPTS:
                            mod = m.group(1).split(".")[0]
                            pkg = IMPORT_MAP.get(mod, mod)
                            if pkg:
                                safe_send(notify_chat,
                                    f"🔧 Missing `{mod}` → installing `{pkg}`...",
                                    parse_mode="Markdown")
                                pip_install(py, [pkg], folder)
                                # retry
                                threading.Thread(
                                    target=run_bot,
                                    args=(uid, user_id, folder, main, notify_chat, 2),
                                    daemon=True
                                ).start()
                                return
                        elif chk.returncode != 0:
                            err_text = (chk.stderr or chk.stdout)[-800:]
                            safe_send(notify_chat,
                                f"❌ Script error (pre-check):\n```\n{err_text}\n```",
                                parse_mode="Markdown")
                            _write_log(uid, f"[PRE-CHECK FAIL]\n{chk.stderr}\n")
                            return
                except subprocess.TimeoutExpired:
                    pass   # long-running — normal
                except Exception as e:
                    logger.error(f"Pre-check exception uid={uid}: {e}")

            # ── open persistent log ───────────────────────────────────────────
            lp = log_path(uid)
            try:
                lf = open(lp, "a", encoding="utf-8", errors="ignore", buffering=1)
                lf.write(f"\n{'='*50}\n[START] {datetime.now()}\n{'='*50}\n")
                lf.flush()
            except Exception as e:
                safe_send(notify_chat, f"❌ Cannot open log file: {e}")
                return

            # ── launch process ────────────────────────────────────────────────
            try:
                proc = subprocess.Popen(
                    [py, script],
                    cwd=folder,
                    stdout=lf, stderr=lf,
                    stdin=subprocess.DEVNULL,
                    encoding="utf-8", errors="ignore"
                )
            except Exception as e:
                lf.close()
                safe_send(notify_chat,
                    f"❌ Failed to launch `{main}`:\n`{e}`", parse_mode="Markdown")
                return

            _instances[uid] = {
                "process":    proc,
                "log_file":   lf,
                "log_path":   lp,
                "user_id":    user_id,
                "main":       main,
                "folder":     folder,
                "started_at": datetime.now(),
            }
            logger.info(f"Bot uid={uid} pid={proc.pid} started")
            safe_send(notify_chat,
                f"✅ `{main}` is running!  PID: `{proc.pid}`",
                parse_mode="Markdown")

        except Exception as ex:
            # TOP-LEVEL GUARD — nothing inside a run_bot thread can kill the host
            logger.error(f"CRITICAL error in run_bot uid={uid}: {ex}", exc_info=True)
            try:
                safe_send(notify_chat,
                    f"❌ Unexpected error starting `{main}`:\n`{ex}`",
                    parse_mode="Markdown")
            except Exception:
                pass

def _write_log(uid, text):
    with open(log_path(uid), "a", encoding="utf-8", errors="ignore") as f:
        f.write(text)

def _safe_thread(target, args=()):
    """Daemon thread with top-level exception guard."""
    def _wrapper():
        try:
            target(*args)
        except Exception as e:
            logger.error(f"Thread {target.__name__} crashed: {e}", exc_info=True)
    t = threading.Thread(target=_wrapper, daemon=True)
    t.start()
    return t

# ══════════════════════════════════════════════════════════════════════════════
#  FILE HANDLING
# ══════════════════════════════════════════════════════════════════════════════
def process_upload(message, content: bytes, filename: str):
    """Entry point for file uploads — runs in thread."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    if len(db_user_bots(user_id)) >= user_limit(user_id):
        safe_send(chat_id, "⚠️ Bot limit reached. Please delete one first.")
        return

    ext = os.path.splitext(filename)[1].lower()
    uid = str(uuid.uuid4())[:8]
    folder = bot_folder(user_id, uid)

    try:
        if ext == ".py":
            _upload_py(message, content, filename, user_id, uid, folder)
        elif ext == ".zip":
            _upload_zip(message, content, filename, user_id, uid, folder)
        else:
            safe_send(chat_id, "⚠️ Only `.py` and `.zip` files are supported.")
            shutil.rmtree(folder, ignore_errors=True)
    except Exception as e:
        logger.error(f"process_upload error: {e}", exc_info=True)
        safe_send(chat_id, f"❌ Upload error: {e}")
        shutil.rmtree(folder, ignore_errors=True)
        db_del_bot(uid)

def _upload_py(message, content, filename, user_id, uid, folder):
    dname = unique_name(user_id, filename)
    dest  = os.path.join(folder, filename)
    with open(dest, "wb") as f:
        f.write(content)
    db_add_bot(uid, user_id, dname, folder, filename)
    safe_send(message.chat.id,
        f"✅ Uploaded `{dname}` (ID: `{uid}`)\n🚀 Starting bot...",
        parse_mode="Markdown")
    _safe_thread(run_bot, (uid, user_id, folder, filename, message.chat.id))

def _upload_zip(message, content, zipname, user_id, uid, folder):
    chat_id = message.chat.id
    tmp = tempfile.mkdtemp(prefix=f"rsbot_{uid}_")
    try:
        zp = os.path.join(tmp, zipname)
        with open(zp, "wb") as f:
            f.write(content)

        # Security check + extract
        with zipfile.ZipFile(zp, "r") as zf:
            for m in zf.infolist():
                if os.path.abspath(os.path.join(tmp, m.filename)) \
                        .startswith(os.path.abspath(tmp)) is False:
                    safe_send(chat_id, f"❌ Unsafe path in ZIP: `{m.filename}`")
                    return
            zf.extractall(tmp)

        # Collect files
        all_files = []
        for root, _, files in os.walk(tmp):
            for fn in files:
                fp   = os.path.join(root, fn)
                rel  = os.path.relpath(fp, tmp)
                if rel != zipname:
                    all_files.append((fp, rel))

        py_files = [r for _, r in all_files if r.endswith(".py")]
        if not py_files:
            safe_send(chat_id, "❌ No `.py` file found inside ZIP.")
            return

        # Pick main script
        main_script = None
        for pref in ["main.py", "bot.py", "app.py", "start.py", "run.py"]:
            for r in py_files:
                if os.path.basename(r) == pref:
                    main_script = r
                    break
            if main_script:
                break
        if not main_script:
            main_script = py_files[0]

        # Copy everything to isolated bot folder
        for src, rel in all_files:
            dst = os.path.join(folder, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        main_base = os.path.basename(main_script)
        dname     = unique_name(user_id, main_base)
        db_add_bot(uid, user_id, dname, folder, main_script)

        safe_send(chat_id,
            f"✅ ZIP extracted!  Main: `{dname}`  (ID: `{uid}`)\n🚀 Starting...",
            parse_mode="Markdown")
        _safe_thread(run_bot, (uid, user_id, folder, main_script, chat_id))

    except zipfile.BadZipFile:
        safe_send(chat_id, "❌ Invalid or corrupted ZIP file.")
        shutil.rmtree(folder, ignore_errors=True)
    except Exception as e:
        logger.error(f"ZIP error uid={uid}: {e}", exc_info=True)
        safe_send(chat_id, f"❌ ZIP processing error: {e}")
        shutil.rmtree(folder, ignore_errors=True)
        db_del_bot(uid)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  BOT INIT
# ══════════════════════════════════════════════════════════════════════════════
bot = telebot.TeleBot(TOKEN, parse_mode=None, threaded=True,
                      num_threads=4)

# ══════════════════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════
def kb_reply(uid):
    rows = [["📢 Updates", "📤 Upload Bot"],
            ["📂 My Bots", "⚡ Speed"],
            ["📊 Stats",   "📞 Contact"]]
    if uid in _admin_ids:
        rows += [["💳 Subscriptions", "📢 Broadcast"],
                 ["🔒 Lock/Unlock",   "🟢 Run All"],
                 ["👑 Admin Panel"]]
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for row in rows:
        m.add(*[types.KeyboardButton(t) for t in row])
    return m

def kb_controls(uid, running: bool):
    m = types.InlineKeyboardMarkup(row_width=2)
    if running:
        m.row(types.InlineKeyboardButton("🔴 Stop",     callback_data=f"stop|{uid}"),
              types.InlineKeyboardButton("🔄 Restart",  callback_data=f"restart|{uid}"))
        m.row(types.InlineKeyboardButton("📜 Live Log", callback_data=f"log|{uid}"),
              types.InlineKeyboardButton("🗑️ Delete",   callback_data=f"del|{uid}"))
    else:
        m.row(types.InlineKeyboardButton("🟢 Start",   callback_data=f"start|{uid}"),
              types.InlineKeyboardButton("🗑️ Delete",  callback_data=f"del|{uid}"))
        m.row(types.InlineKeyboardButton("📜 Log",     callback_data=f"log|{uid}"))
    m.add(types.InlineKeyboardButton("🔙 My Bots", callback_data="bots"))
    return m

def kb_confirm_del(uid):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(types.InlineKeyboardButton("✅ Yes, Delete", callback_data=f"delok|{uid}"),
          types.InlineKeyboardButton("❌ Cancel",       callback_data=f"bot|{uid}"))
    return m

def kb_sub():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(types.InlineKeyboardButton("➕ Add",    callback_data="sub_add"),
          types.InlineKeyboardButton("➖ Remove", callback_data="sub_rm"))
    m.add(types.InlineKeyboardButton("🔍 Check", callback_data="sub_chk"))
    m.add(types.InlineKeyboardButton("🔙 Back",  callback_data="back"))
    return m

def kb_admin():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(types.InlineKeyboardButton("➕ Add Admin",    callback_data="adm_add"),
          types.InlineKeyboardButton("➖ Remove Admin", callback_data="adm_rm"))
    m.add(types.InlineKeyboardButton("📋 List Admins", callback_data="adm_list"))
    m.add(types.InlineKeyboardButton("🔙 Back",        callback_data="back"))
    return m

def kb_bots(user_id):
    rows = db_user_bots(user_id)
    m    = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        icon = "🟢" if is_running(r["uid"]) else "🔴"
        dt   = r["created_at"][:10]
        m.add(types.InlineKeyboardButton(
            f"{icon} {r['display_name']} [{dt}]",
            callback_data=f"bot|{r['uid']}"
        ))
    m.add(types.InlineKeyboardButton("🔙 Back", callback_data="back"))
    return m

# ══════════════════════════════════════════════════════════════════════════════
#  WELCOME TEXT
# ══════════════════════════════════════════════════════════════════════════════
def welcome_text(user_id, first_name):
    lim   = user_limit(user_id)
    count = len(db_user_bots(user_id))
    lstr  = "∞" if lim == float("inf") else str(int(lim))
    return (
        f"〽️ *Welcome, {first_name}!*\n\n"
        f"🆔 Your ID: `{user_id}`\n"
        f"🔰 Status: {user_status(user_id)}{sub_info(user_id)}\n"
        f"📁 Bots: `{count}` / `{lstr}`\n\n"
        f"📤 Upload `.py` or `.zip` to host your bot.\n"
        f"Each bot runs in its own isolated environment.\n\n"
        f"👇 Use the buttons below:"
    )

def bot_panel_text(row):
    uid     = row["uid"]
    running = is_running(uid)
    status  = "🟢 Running" if running else "🔴 Stopped"
    uptime  = ""
    if running and uid in _instances:
        st = _instances[uid].get("started_at")
        if st:
            d = datetime.now() - st
            h, rem = divmod(int(d.total_seconds()), 3600)
            mn, s  = divmod(rem, 60)
            uptime = f"\n⏱ Uptime: `{h}h {mn}m {s}s`"
    return (
        f"⚙️ *Bot Control Panel*\n\n"
        f"📛 Name: `{row['display_name']}`\n"
        f"🆔 UID: `{uid}`\n"
        f"📄 Script: `{row['main_script']}`\n"
        f"🕒 Added: `{row['created_at'][:16]}`\n"
        f"📊 Status: {status}{uptime}"
    )

# ══════════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    uid_s  = message.from_user.id
    chat   = message.chat.id
    fname  = message.from_user.first_name

    if is_locked() and uid_s not in _admin_ids:
        bot.reply_to(message, "⚠️ Bot is currently locked by admin.")
        return

    is_new = uid_s not in _active_users
    if is_new:
        db_add_user(uid_s)
        try:
            bot.send_message(OWNER_ID,
                f"🎉 *New user joined!*\n"
                f"👤 {fname}\n"
                f"✳️ @{message.from_user.username or 'N/A'}\n"
                f"🆔 `{uid_s}`",
                parse_mode="Markdown")
        except Exception:
            pass

    # Send profile photo + welcome
    try:
        photos = bot.get_user_profile_photos(uid_s, limit=1)
        if photos and photos.photos:
            fid = photos.photos[0][-1].file_id
            bot.send_photo(chat, fid,
                caption=welcome_text(uid_s, fname),
                reply_markup=kb_reply(uid_s),
                parse_mode="Markdown")
            return
    except Exception:
        pass

    # No photo fallback
    bot.send_message(chat, welcome_text(uid_s, fname),
                     reply_markup=kb_reply(uid_s), parse_mode="Markdown")

@bot.message_handler(commands=["ping"])
def cmd_ping(message):
    t  = time.time()
    m2 = bot.reply_to(message, "🏓 Pong!")
    lat = round((time.time() - t) * 1000, 1)
    try:
        bot.edit_message_text(f"🏓 Pong!  `{lat}ms`",
                              message.chat.id, m2.message_id, parse_mode="Markdown")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  REPLY KEYBOARD DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════
_BTN_LABELS = {"📢 Updates","📤 Upload Bot","📂 My Bots","⚡ Speed",
               "📊 Stats","📞 Contact","💳 Subscriptions","📢 Broadcast",
               "🔒 Lock/Unlock","🟢 Run All","👑 Admin Panel"}

@bot.message_handler(func=lambda m: m.text in _BTN_LABELS)
def btn_handler(message):
    uid_s = message.from_user.id
    chat  = message.chat.id
    t     = message.text

    if t == "📢 Updates":
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("📢 Channel", url=UPDATE_CHANNEL))
        bot.reply_to(message, "📢 Follow our updates channel:", reply_markup=mk)

    elif t == "📤 Upload Bot":
        if is_locked() and uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Bot is locked."); return
        if len(db_user_bots(uid_s)) >= user_limit(uid_s):
            bot.reply_to(message, "⚠️ Bot limit reached. Delete one first."); return
        bot.reply_to(message, "📤 Send your `.py` or `.zip` file now.", parse_mode="Markdown")

    elif t == "📂 My Bots":
        rows = db_user_bots(uid_s)
        if not rows:
            bot.reply_to(message, "📂 You have no bots uploaded yet."); return
        bot.reply_to(message, "📂 *Your Bots:*",
                     reply_markup=kb_bots(uid_s), parse_mode="Markdown")

    elif t == "⚡ Speed":
        t0  = time.time()
        m2  = bot.reply_to(message, "⏱ Testing...")
        lat = round((time.time() - t0) * 1000, 1)
        st  = "🔒 Locked" if is_locked() else "🔓 Unlocked"
        try:
            bot.edit_message_text(
                f"⚡ *Speed*\n\n⏱ Latency: `{lat}ms`\n🚦 Status: {st}\n👤 {user_status(uid_s)}",
                chat, m2.message_id, parse_mode="Markdown")
        except Exception:
            pass

    elif t == "📊 Stats":
        total_u = len(_active_users)
        running = sum(1 for u in list(_instances) if is_running(u))
        with _db() as c:
            total_b = c.execute("SELECT COUNT(*) FROM bots").fetchone()[0]
        bot.reply_to(message,
            f"📊 *Statistics*\n\n"
            f"👥 Total Users: `{total_u}`\n"
            f"🤖 Registered Bots: `{total_b}`\n"
            f"🟢 Currently Running: `{running}`\n"
            f"🔒 Host Status: `{'Locked' if is_locked() else 'Unlocked'}`",
            parse_mode="Markdown")

    elif t == "📞 Contact":
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("📞 Owner", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}"))
        bot.reply_to(message, "Contact the owner:", reply_markup=mk)

    elif t == "💳 Subscriptions":
        if uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Admin only."); return
        bot.reply_to(message, "💳 *Subscription Management*",
                     reply_markup=kb_sub(), parse_mode="Markdown")

    elif t == "📢 Broadcast":
        if uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Admin only."); return
        m2 = bot.reply_to(message, "📢 Send the message to broadcast.\n/cancel to abort.")
        bot.register_next_step_handler(m2, _ns_broadcast)

    elif t == "🔒 Lock/Unlock":
        if uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Admin only."); return
        set_locked(not is_locked())
        bot.reply_to(message,
            "🔒 Bot *locked*." if is_locked() else "🔓 Bot *unlocked*.",
            parse_mode="Markdown")

    elif t == "🟢 Run All":
        if uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Admin only."); return
        _run_all(message)

    elif t == "👑 Admin Panel":
        if uid_s not in _admin_ids:
            bot.reply_to(message, "⚠️ Admin only."); return
        bot.reply_to(message, "👑 *Admin Panel*",
                     reply_markup=kb_admin(), parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════════════════════
#  DOCUMENT HANDLER
# ══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(content_types=["document"])
def doc_handler(message):
    uid_s = message.from_user.id
    chat  = message.chat.id

    if is_locked() and uid_s not in _admin_ids:
        bot.reply_to(message, "⚠️ Bot is locked."); return

    doc  = message.document
    name = doc.file_name or "upload.py"
    ext  = os.path.splitext(name)[1].lower()

    if ext not in (".py", ".zip"):
        bot.reply_to(message, "⚠️ Only `.py` and `.zip` files.", parse_mode="Markdown"); return
    if doc.file_size > MAX_FILE_MB * 1024 * 1024:
        bot.reply_to(message, f"⚠️ File too large (max {MAX_FILE_MB} MB)."); return
    if len(db_user_bots(uid_s)) >= user_limit(uid_s):
        bot.reply_to(message, "⚠️ Bot limit reached. Delete one first."); return

    try:
        try:
            bot.forward_message(OWNER_ID, chat, message.message_id)
        except Exception:
            pass

        wm = bot.reply_to(message, f"⏳ Downloading `{name}`...", parse_mode="Markdown")
        fi  = bot.get_file(doc.file_id)
        raw = bot.download_file(fi.file_path)
        try:
            bot.edit_message_text(f"✅ Downloaded. Processing...", chat, wm.message_id)
        except Exception:
            pass

        _safe_thread(process_upload, (message, raw, name))

    except telebot.apihelper.ApiTelegramException as e:
        bot.reply_to(message, f"❌ Telegram API error: {e}")
    except Exception as e:
        logger.error(f"doc_handler: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    uid_s  = call.from_user.id
    chat   = call.message.chat.id
    mid    = call.message.message_id
    data   = call.data
    parts  = data.split("|", 1)
    action = parts[0]
    target = parts[1] if len(parts) > 1 else None

    try:
        # ── navigation ────────────────────────────────────────────────────────
        if action == "back":
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(welcome_text(uid_s, call.from_user.first_name),
                                      chat, mid, parse_mode="Markdown")
            except Exception:
                pass

        elif action == "bots":
            bot.answer_callback_query(call.id)
            rows = db_user_bots(uid_s)
            if not rows:
                bot.edit_message_text("📂 No bots yet.", chat, mid); return
            try:
                bot.edit_message_text("📂 *Your Bots:*", chat, mid,
                                      reply_markup=kb_bots(uid_s), parse_mode="Markdown")
            except Exception:
                pass

        # ── bot control panel ─────────────────────────────────────────────────
        elif action == "bot":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(bot_panel_text(row), chat, mid,
                                      reply_markup=kb_controls(target, is_running(target)),
                                      parse_mode="Markdown")
            except Exception:
                pass

        # ── start ─────────────────────────────────────────────────────────────
        elif action == "start":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            if is_running(target):
                bot.answer_callback_query(call.id, "Already running!", show_alert=True); return
            bot.answer_callback_query(call.id, "▶️ Starting...")
            _safe_thread(run_bot, (target, row["user_id"],
                                   row["bot_folder"], row["main_script"], chat))
            time.sleep(1.5)
            try:
                bot.edit_message_reply_markup(chat, mid,
                    reply_markup=kb_controls(target, is_running(target)))
            except Exception:
                pass

        # ── stop ──────────────────────────────────────────────────────────────
        elif action == "stop":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            if not is_running(target):
                bot.answer_callback_query(call.id, "Already stopped!", show_alert=True); return
            kill_bot(target)
            bot.answer_callback_query(call.id, "🔴 Stopped.")
            try:
                bot.edit_message_reply_markup(chat, mid,
                    reply_markup=kb_controls(target, False))
            except Exception:
                pass

        # ── restart ───────────────────────────────────────────────────────────
        elif action == "restart":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            bot.answer_callback_query(call.id, "🔄 Restarting...")
            if is_running(target):
                kill_bot(target)
                time.sleep(0.8)
            _safe_thread(run_bot, (target, row["user_id"],
                                   row["bot_folder"], row["main_script"], chat))
            time.sleep(1.5)
            try:
                bot.edit_message_reply_markup(chat, mid,
                    reply_markup=kb_controls(target, is_running(target)))
            except Exception:
                pass

        # ── delete (confirm) ──────────────────────────────────────────────────
        elif action == "del":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(
                    f"⚠️ *Confirm delete* `{row['display_name']}`?\n\nThis will remove all files.",
                    chat, mid, reply_markup=kb_confirm_del(target), parse_mode="Markdown")
            except Exception:
                pass

        # ── delete confirmed ──────────────────────────────────────────────────
        elif action == "delok":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Already deleted.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            if is_running(target):
                kill_bot(target)
            folder = row["bot_folder"]
            if os.path.exists(folder):
                shutil.rmtree(folder, ignore_errors=True)
            lp = log_path(target)
            if os.path.exists(lp):
                try: os.remove(lp)
                except Exception: pass
            db_del_bot(target)
            bot.answer_callback_query(call.id, "🗑️ Deleted.")
            try:
                bot.edit_message_text(f"🗑️ Bot `{row['display_name']}` deleted.",
                                      chat, mid, parse_mode="Markdown")
            except Exception:
                pass

        # ── live log ──────────────────────────────────────────────────────────
        elif action == "log":
            row = db_get_bot(target)
            if not row:
                bot.answer_callback_query(call.id, "Not found.", show_alert=True); return
            if uid_s != row["user_id"] and uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "⚠️ No permission.", show_alert=True); return
            bot.answer_callback_query(call.id)
            log_text = tail_log(target, 60)
            if len(log_text) > 3600:
                log_text = "...(truncated)\n" + log_text[-3600:]
            mk = types.InlineKeyboardMarkup()
            mk.add(types.InlineKeyboardButton("🔄 Refresh", callback_data=f"log|{target}"))
            mk.add(types.InlineKeyboardButton("🔙 Back",    callback_data=f"bot|{target}"))
            status = "🟢 Running" if is_running(target) else "🔴 Stopped"
            try:
                bot.edit_message_text(
                    f"📜 *Live Log* — {status}\n```\n{log_text}\n```",
                    chat, mid, reply_markup=mk, parse_mode="Markdown")
            except Exception:
                safe_send(chat,
                    f"📜 *Log* `{target}`:\n```\n{log_text}\n```",
                    parse_mode="Markdown")

        # ── subscription management ───────────────────────────────────────────
        elif action == "sub_add":
            if uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            m2 = safe_send(chat, "💳 Enter: `USER_ID DAYS`  (e.g. `123456789 30`)\n/cancel to abort.")
            bot.register_next_step_handler_by_chat_id(chat, _ns_sub_add)

        elif action == "sub_rm":
            if uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            safe_send(chat, "💳 Enter User ID to remove subscription.\n/cancel to abort.")
            bot.register_next_step_handler_by_chat_id(chat, _ns_sub_rm)

        elif action == "sub_chk":
            if uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            safe_send(chat, "💳 Enter User ID to check.\n/cancel to abort.")
            bot.register_next_step_handler_by_chat_id(chat, _ns_sub_chk)

        # ── admin panel ───────────────────────────────────────────────────────
        elif action == "adm_add":
            if uid_s != OWNER_ID:
                bot.answer_callback_query(call.id, "Owner only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            safe_send(chat, "👑 Enter User ID to promote to Admin.\n/cancel to abort.")
            bot.register_next_step_handler_by_chat_id(chat, _ns_adm_add)

        elif action == "adm_rm":
            if uid_s != OWNER_ID:
                bot.answer_callback_query(call.id, "Owner only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            safe_send(chat, "👑 Enter Admin User ID to demote.\n/cancel to abort.")
            bot.register_next_step_handler_by_chat_id(chat, _ns_adm_rm)

        elif action == "adm_list":
            if uid_s not in _admin_ids:
                bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
            bot.answer_callback_query(call.id)
            lines = "\n".join(
                f"• `{a}` {'👑 Owner' if a == OWNER_ID else ''}"
                for a in sorted(_admin_ids)
            )
            try:
                bot.edit_message_text(f"👑 *Admins:*\n\n{lines}",
                                      chat, mid, reply_markup=kb_admin(), parse_mode="Markdown")
            except Exception:
                pass

        else:
            bot.answer_callback_query(call.id, "Unknown action.")

    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            logger.error(f"API error in callback '{data}': {e}")
            try: bot.answer_callback_query(call.id, "Telegram error.", show_alert=True)
            except Exception: pass
    except Exception as e:
        logger.error(f"Callback '{data}' error: {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error occurred.", show_alert=True)
        except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
#  NEXT-STEP HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
def _cancelled(msg) -> bool:
    return bool(msg.text and msg.text.strip().lower() == "/cancel")

def _ns_sub_add(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id not in _admin_ids: return
    try:
        uid_t, days = int(msg.text.split()[0]), int(msg.text.split()[1])
        cur = _subscriptions.get(uid_t)
        base = max(datetime.now(), cur) if cur else datetime.now()
        exp  = base + timedelta(days=days)
        db_add_sub(uid_t, exp)
        safe_reply(msg, f"✅ Sub for `{uid_t}`: +{days} days → expires `{exp:%Y-%m-%d}`",
                   parse_mode="Markdown")
        try: bot.send_message(uid_t, f"🎉 Subscription extended by {days} days! Expires {exp:%Y-%m-%d}.")
        except Exception: pass
    except Exception:
        safe_reply(msg, "⚠️ Format: `USER_ID DAYS`", parse_mode="Markdown")

def _ns_sub_rm(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id not in _admin_ids: return
    try:
        uid_t = int(msg.text.strip())
        db_del_sub(uid_t)
        safe_reply(msg, f"✅ Subscription removed for `{uid_t}`.", parse_mode="Markdown")
    except Exception:
        safe_reply(msg, "⚠️ Invalid User ID.")

def _ns_sub_chk(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id not in _admin_ids: return
    try:
        uid_t = int(msg.text.strip())
        exp   = _subscriptions.get(uid_t)
        if exp and exp > datetime.now():
            d = (exp - datetime.now()).days
            safe_reply(msg, f"✅ `{uid_t}` active — expires `{exp:%Y-%m-%d}` ({d} days left)",
                       parse_mode="Markdown")
        elif exp:
            db_del_sub(uid_t)
            safe_reply(msg, f"⚠️ `{uid_t}` expired on `{exp:%Y-%m-%d}`.", parse_mode="Markdown")
        else:
            safe_reply(msg, f"ℹ️ `{uid_t}` has no subscription.", parse_mode="Markdown")
    except Exception:
        safe_reply(msg, "⚠️ Invalid User ID.")

def _ns_adm_add(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id != OWNER_ID: return
    try:
        new_id = int(msg.text.strip())
        if new_id in _admin_ids:
            safe_reply(msg, f"⚠️ `{new_id}` is already an admin.", parse_mode="Markdown"); return
        db_add_admin(new_id)
        safe_reply(msg, f"✅ `{new_id}` promoted to Admin.", parse_mode="Markdown")
        try: bot.send_message(new_id, "🎉 You are now an Admin!")
        except Exception: pass
    except Exception:
        safe_reply(msg, "⚠️ Invalid User ID.")

def _ns_adm_rm(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id != OWNER_ID: return
    try:
        rm_id = int(msg.text.strip())
        if db_del_admin(rm_id):
            safe_reply(msg, f"✅ `{rm_id}` removed from admins.", parse_mode="Markdown")
            try: bot.send_message(rm_id, "ℹ️ You are no longer an admin.")
            except Exception: pass
        else:
            safe_reply(msg, "⚠️ Cannot remove Owner.", parse_mode="Markdown")
    except Exception:
        safe_reply(msg, "⚠️ Invalid User ID.")

def _ns_broadcast(msg):
    if _cancelled(msg): safe_send(msg.chat.id, "Cancelled."); return
    if msg.from_user.id not in _admin_ids: return
    if not msg.text:
        safe_reply(msg, "⚠️ Text-only broadcast supported."); return
    text  = msg.text
    count = len(_active_users)
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(
        types.InlineKeyboardButton("✅ Send", callback_data=f"bc_ok|{msg.message_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="bc_cancel")
    )
    bot.reply_to(msg,
        f"📢 Preview:\n```\n{text[:500]}\n```\nSend to *{count}* users?",
        reply_markup=mk, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("bc_"))
def cb_broadcast(call):
    uid_s = call.from_user.id
    if uid_s not in _admin_ids:
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return

    if call.data == "bc_cancel":
        bot.answer_callback_query(call.id, "Cancelled.")
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        return

    if call.data.startswith("bc_ok|"):
        orig = call.message.reply_to_message
        if not orig or not orig.text:
            bot.answer_callback_query(call.id, "Message not found.", show_alert=True); return
        text = orig.text
        bot.answer_callback_query(call.id, "🚀 Broadcasting...")
        try:
            bot.edit_message_text(f"📢 Broadcasting to {len(_active_users)} users...",
                                  call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        _safe_thread(_do_broadcast, (text, call.message.chat.id))

def _do_broadcast(text, admin_chat):
    sent = failed = blocked = 0
    for uid_u in list(_active_users):
        try:
            bot.send_message(uid_u, text, parse_mode="Markdown")
            sent += 1
        except telebot.apihelper.ApiTelegramException as e:
            err = str(e).lower()
            if any(s in err for s in ("blocked","deactivated","not found","kicked")):
                blocked += 1
            elif "flood" in err or "too many" in err:
                time.sleep(5)
                try:
                    bot.send_message(uid_u, text, parse_mode="Markdown")
                    sent += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(0.05)
    safe_send(admin_chat,
        f"✅ Broadcast done!\n✅ Sent: {sent}\n🚫 Blocked: {blocked}\n❌ Failed: {failed}")

# ══════════════════════════════════════════════════════════════════════════════
#  RUN ALL BOTS
# ══════════════════════════════════════════════════════════════════════════════
def _run_all(message):
    safe_reply(message, "⏳ Starting all stopped bots...")
    rows    = db_all_bots()
    started = skipped = errors = 0
    for r in rows:
        uid = r["uid"]
        if is_running(uid):
            skipped += 1
            continue
        folder = r["bot_folder"]
        main   = r["main_script"]
        if not os.path.exists(os.path.join(folder, main)):
            errors += 1
            continue
        _safe_thread(run_bot, (uid, r["user_id"], folder, main, message.chat.id))
        started += 1
        time.sleep(0.3)
    safe_reply(message,
        f"✅ Done!\n▶️ Started: {started}\n⏭ Skipped: {skipped}\n❌ Missing: {errors}")

# ══════════════════════════════════════════════════════════════════════════════
#  CLEANUP
# ══════════════════════════════════════════════════════════════════════════════
def _shutdown():
    logger.info("Shutdown: killing all bot processes...")
    for uid in list(_instances):
        try: kill_bot(uid)
        except Exception: pass
    logger.info("All bots stopped.")

atexit.register(_shutdown)

# ══════════════════════════════════════════════════════════════════════════════
#  CRASH-PROOF POLLING  —  never stops
# ══════════════════════════════════════════════════════════════════════════════
def start_polling():
    logger.info("="*55)
    logger.info("🤖  RS HOSTING BOT  —  Polling Mode")
    logger.info(f"🐍  Python {sys.version.split()[0]}")
    logger.info(f"📁  Bots   : {BOTS}")
    logger.info(f"📊  Data   : {DATA}")
    logger.info(f"📋  Logs   : {LOGS}")
    logger.info(f"👑  Owner  : {OWNER_ID}")
    logger.info("="*55)

    while True:
        try:
            logger.info("🚀 Polling started.")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                logger_level=logging.WARNING,
                allowed_updates=["message", "callback_query"],
            )
        except requests.exceptions.ReadTimeout:
            logger.warning("ReadTimeout — reconnecting in 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"ConnectionError: {e} — reconnecting in 15s...")
            time.sleep(15)
        except requests.exceptions.SSLError as e:
            logger.error(f"SSLError: {e} — reconnecting in 10s...")
            time.sleep(10)
        except telebot.apihelper.ApiTelegramException as e:
            logger.error(f"Telegram API error: {e} — reconnecting in 10s...")
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — shutting down.")
            _shutdown()
            sys.exit(0)
        except Exception as e:
            logger.critical(f"Polling crash: {e}", exc_info=True)
            logger.info("Restarting polling in 30s...")
            time.sleep(30)
        finally:
            time.sleep(1)

if __name__ == "__main__":
    init_db()
    load_db()
    start_polling()
