# RS BOT HOST 🤖

<div align="center">

![RS Hosting Bot](https://img.shields.io/badge/RS-Hosting%20Bot-blue?style=for-the-badge&logo=telegram)
![Version](https://img.shields.io/badge/Version-3.2-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.7+-yellow?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-MIT-red?style=flat-square)

**Ultra-Professional Telegram Bot Hosting Platform**

[![Telegram](https://img.shields.io/badge/Telegram-@rs__woner-blue?style=flat-square&logo=telegram)](https://t.me/rs_woner)
[![Channel](https://img.shields.io/badge/Channel-@CARTOONFUNNY03-blue?style=flat-square&logo=telegram)](https://t.me/CARTOONFUNNY03)

</div>

---

## 📋 Table of Contents
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [How It Works](#-how-it-works)
- [Commands & Buttons](#-commands--buttons)
- [Bot Management](#-bot-management)
- [Admin Panel](#-admin-panel)
- [Database Structure](#-database-structure)
- [File Structure](#-file-structure)
- [Security Features](#-security-features)
- [Contributing](#-contributing)
- [License](#-license)
- [Contact](#-contact)

---

## ✨ Features

### Core Features
- ✅ **Isolated Virtual Environments** - Each bot runs in its own venv (no dependency conflicts)
- ✅ **Unique UUID Folders** - Safe deletion without affecting other bots
- ✅ **Auto-Import Detection** - Scans your code and automatically installs required packages
- ✅ **requirements.txt Support** - Works with existing requirements.txt files inside ZIP
- ✅ **Persistent Logs** - Live log viewing per bot
- ✅ **Crash-Proof Architecture** - Hosted bots never crash the main host bot
- ✅ **Smart File Management** - Automatic duplicate name handling
- ✅ **Profile Photo Support** - Welcome message with user's profile photo

### User Features
- 📤 Upload `.py` or `.zip` files
- 📂 View all your hosted bots
- 🟢 Start/Stop/Restart bots
- 📜 View live logs
- 🗑️ Delete bots
- 💳 Premium subscription system

### Admin Features
- 👑 Admin panel
- 💳 Manage subscriptions
- 📢 Broadcast messages
- 🔒 Lock/Unlock bot
- 🟢 Run all bots
- 👥 User management

---

## 🔧 Requirements

### System Requirements
```bash
Python 3.7 or higher
pip (Python package manager)
Internet connection
Telegram Bot Token
```

Required Python Packages

```txt
pyTelegramBotAPI==4.24.0
requests==2.31.0
psutil==5.9.5
python-dotenv==1.0.0
colorama==0.4.6
```

Installation Commands

```bash
# Install all requirements
pip install -r requirements.txt

# Or install individually
pip install pyTelegramBotAPI requests psutil
```

---

🚀 Installation

1. Clone or Download the Repository

```bash
git clone https://github.com/yourusername/rs-hosting-bot.git
cd rs-hosting-bot
```

2. Install Dependencies

```bash
pip install -r requirements.txt
```

3. Configure Environment Variables

Create a .env file or set environment variables:

```env
BOT_TOKEN=your_bot_token_here
OWNER_ID=your_telegram_id
ADMIN_ID=admin_telegram_id
OWNER_USERNAME=@your_username
UPDATE_CHANNEL=https://t.me/your_channel
```

4. Run the Bot

```bash
python bot.py
```

For Termux (Android)

```bash
pkg install python
pip install pyTelegramBotAPI requests psutil
python bot.py
```

---

⚙️ Configuration

Environment Variables

Variable Description Default
BOT_TOKEN Your Telegram Bot Token Required
OWNER_ID Owner's Telegram User ID Required
ADMIN_ID Admin's Telegram User ID Same as Owner
OWNER_USERNAME Owner's Telegram Username @rs_woner
UPDATE_CHANNEL Channel for updates https://t.me/CARTOONFUNNY03

Limits Configuration

```python
FREE_LIMIT     = 1      # Free users can host 1 bot
PREMIUM_LIMIT  = 20     # Premium users can host 20 bots
ADMIN_LIMIT    = 100    # Admins can host 100 bots
MAX_FILE_MB    = 30     # Maximum file size: 30MB
```

---

🎯 How It Works

1. File Upload Process

```
User Uploads File (.py or .zip)
        ↓
File Size Check (<30MB)
        ↓
Bot Limit Check
        ↓
Extract/Process Files
        ↓
Create Isolated Virtual Environment
        ↓
Scan Imports & Install Dependencies
        ↓
Run Bot in Subprocess
        ↓
Monitor & Log Everything
```

2. Bot Lifecycle

```
🟢 Running → Can be Stopped/Restarted
🔴 Stopped → Can be Started/Deleted
📜 Logs → Always accessible
🗑️ Deleted → All files removed
```

3. Dependency Management

· 🔍 Auto-scans Python files for imports
· 📦 Installs missing packages automatically
· 📄 Supports requirements.txt
· ⚡ Uses isolated virtual environments

---

📱 Commands & Buttons

User Commands

Command Description
/start Start the bot and show welcome message
/help Show help information
/ping Check bot latency

Main Menu Buttons

Button Function
📢 Updates Show update channel
📤 Upload Bot Upload .py or .zip file
📂 My Bots View all hosted bots
⚡ Speed Check bot speed and status
📊 Stats View bot statistics
📞 Contact Contact owner

Bot Control Buttons

Button Function
🟢 Start Start a stopped bot
🔴 Stop Stop a running bot
🔄 Restart Restart a bot
📜 Log View live logs
🗑️ Delete Delete a bot (with confirmation)

---

👑 Admin Panel

Admin Features

💳 Subscription Management

```python
# Add Subscription
/format: USER_ID DAYS
Example: 123456789 30

# Remove Subscription
USER_ID

# Check Subscription
USER_ID
```

📢 Broadcast

· Send messages to all users
· Preview before sending
· Anti-flood protection
· Shows delivery statistics

🔒 Lock/Unlock

· Lock bot for maintenance
· Only admins can use locked bot
· Prevents new uploads from users

🟢 Run All

· Start all stopped bots
· Handles missing files gracefully
· Reports success/failure

👑 Admin Panel

· Add/Remove admins (Owner only)
· List all admins
· Manage subscriptions

---

📊 Database Structure

SQLite Database Schema

```sql
-- Bots Table
CREATE TABLE bots (
    uid          TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    bot_folder   TEXT NOT NULL,
    main_script  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Subscriptions Table
CREATE TABLE subs (
    user_id INTEGER PRIMARY KEY,
    expiry  TEXT NOT NULL
);

-- Users Table
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY
);

-- Admins Table
CREATE TABLE admins (
    user_id INTEGER PRIMARY KEY
);
```

---

📁 File Structure

```
rs-hosting-bot/
├── bot.py                 # Main bot file
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── bots/                  # Hosted bots directory
│   └── user_id/
│       └── uuid/
│           ├── .venv/     # Virtual environment
│           ├── *.py       # User bot files
│           └── requirements.txt
├── data/
│   └── db.sqlite          # SQLite database
└── logs/
    ├── host.log           # Host bot logs
    └── uid.log            # Per-bot logs
```

---

🔒 Security Features

File Security

· ✅ ZIP path traversal protection
· ✅ File size limits (30MB)
· ✅ Only .py and .zip allowed
· ✅ Isolated bot directories
· ✅ Safe file deletion

Process Security

· ✅ Subprocess isolation
· ✅ Crash-proof design
· ✅ Process killing on stop/delete
· ✅ Resource monitoring

User Security

· ✅ Bot limit enforcement
· ✅ Permission checks
· ✅ Admin-only features
· ✅ Lock system

---

🛠️ Troubleshooting

Common Issues

Bot won't start

```bash
# Check Python version
python --version

# Check dependencies
pip list | grep -E "pyTelegramBotAPI|requests|psutil"

# Check token
echo $BOT_TOKEN
```

Import errors in hosted bots

· Automatic import detection will handle most cases
· Check logs for missing packages
· Add missing packages to IMPORT_MAP in bot.py

Performance issues

· Increase MAX_FILE_MB if needed
· Adjust _THREAD_SEM for concurrent startups
· Monitor system resources

---

🤝 Contributing

1. Fork the repository
2. Create your feature branch (git checkout -b feature/AmazingFeature)
3. Commit your changes (git commit -m 'Add some AmazingFeature')
4. Push to the branch (git push origin feature/AmazingFeature)
5. Open a Pull Request

Development Guidelines

· Follow PEP 8 style guide
· Add comments for complex logic
· Update documentation
· Test thoroughly

---

📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

📞 Contact

<div align="center">

Developer: @rs_woner
Channel: @CARTOONFUNNY03
Support: Telegram Support Group

https://img.shields.io/badge/Telegram-@rs__woner-2CA5E0?style=for-the-badge&logo=telegram
https://img.shields.io/badge/Channel-@CARTOONFUNNY03-2CA5E0?style=for-the-badge&logo=telegram

</div>

---

⭐ Support Us

If you like this project, please:

· ⭐ Star the repository
· 🔄 Share with friends
· 📢 Join our channel
· 💬 Report issues

---

<div align="center">

Made with ❤️ by RS WONER

Ultra-Professional Telegram Bot Hosting

</div>
