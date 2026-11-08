import os
import json
import logging
import asyncio
import re
from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIGURATION & CONSTANTS =================

CONFIG_FILE = "bot_config.json"
STATE_FILE = "vault_state.json"

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Master Bot Owner Telegram IDs (Super Admins with Global Inspection & System Rights)
SUPER_ADMIN_IDS = [5331007152]

# Default Tenant Configuration Template for Multi-Tenant Support
DEFAULT_TENANT_CONFIG = {
    "main_hub_id": 0,
    "admin_proof_group_id": 0,
    "proof_archive_id": 0,
    "shop_name": "Digital Vault Store",
    "co_owners": [],
    "payments": {
        "pay_gcash": "📱 **GCash Payment**\nNumber: `09171234567`\nAccount Name: Admin",
        "pay_maya": "📱 **Maya Payment**\nNumber: `09171234567`\nAccount Name: Admin",
        "pay_bank": "🏦 **MariBank / Bank Transfer**\nAccount Number: `1234-5678-9012`\nBank: MariBank\nAccount Name: Admin",
    },
    "messages": {
        "welcome": "👋 **Welcome to {shop_name}, {name}!**\n\nGet access to our complete library of courses and ebooks.\n\nPlease select your preferred payment method below:",
        "help": "📖 **MEMBER HELP & INSTRUCTIONS**\n\nWelcome {name}! Here is how to purchase access:\n\n1️⃣ **Start Checkout:** Select a payment method below.\n2️⃣ **Make Transfer:** Pay the exact amount using the payment details shown.\n3️⃣ **Send Receipt:** Take a screenshot of your successful transaction and send the photo directly to this chat.\n4️⃣ **Instant Access:** Once approved, you will automatically receive a private single-use invite link to the hub!",
        "receipt": "⌛ **Receipt Submitted!**\n\nThank you {name}. Our admin team is verifying your payment. Once approved, you will automatically receive your invite link here!"
    },
    "moderation": {
        "enabled": True,
        "bad_words": ["scam", "hack", "free money", "gambling", "crypto free"],
        "block_links": True,
        "whitelisted_domains": ["t.me", "telegram.org", "drive.google.com"]
    },
    "security": {
        "phishing_keywords": ["bot token", "session file", "otp code", "telegram login", "stealer", "token grabber"],
        "suspicious_extensions": [".exe", ".scr", ".bat", ".cmd", ".vbs", ".apk"]
    }
}

DEFAULT_GLOBAL_CONFIG = {
    "bot_token": os.getenv("TELEGRAM_TOKEN", "9118312201:AAFvZ6-cRZZCZqtbSz9dXTChxKYIKkTt9e8"),
    "super_admin_ids": SUPER_ADMIN_IDS,
    "settings": {
        "allow_admin_member_cmds": False,  # If False, /start and /help display Admin Notices to Admins in groups
    },
    "tenants": {},
    "chat_tenant_map": {}
}

# ================= PERSISTENT STORAGE HELPERS =================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if "tenants" not in config:
                    config["tenants"] = {}
                if "chat_tenant_map" not in config:
                    config["chat_tenant_map"] = {}
                if "super_admin_ids" not in config:
                    config["super_admin_ids"] = SUPER_ADMIN_IDS
                if "bot_token" not in config:
                    config["bot_token"] = DEFAULT_GLOBAL_CONFIG["bot_token"]
                if "settings" not in config:
                    config["settings"] = DEFAULT_GLOBAL_CONFIG["settings"]
                return config
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            return DEFAULT_GLOBAL_CONFIG
    return DEFAULT_GLOBAL_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving config file: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"Error loading state file: {e}")
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving state file: {e}")

GLOBAL_CONFIG = load_config()
VAULT_STATE = load_state()
PENDING_PROMOTIONS = {}

# Flask App Initialization for Render.com Webhook Hosting
app = Flask(__name__)

def normalize_title(title: str) -> str:
    return title.strip().lower()

def get_tenant_config(owner_id: int):
    owner_str = str(owner_id)
    tenants = GLOBAL_CONFIG.setdefault("tenants", {})
    if owner_str not in tenants:
        tenants[owner_str] = json.loads(json.dumps(DEFAULT_TENANT_CONFIG))
        save_config(GLOBAL_CONFIG)
    return tenants[owner_str]

def get_tenant_by_chat(chat_id: int):
    chat_str = str(chat_id)
    chat_map = GLOBAL_CONFIG.get("chat_tenant_map", {})
    if chat_str in chat_map:
        owner_id = chat_map[chat_str]
        return owner_id, get_tenant_config(owner_id)
    return None, None

def is_super_admin(user_id: int) -> bool:
    return user_id in GLOBAL_CONFIG.get("super_admin_ids", SUPER_ADMIN_IDS)

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if not user:
        if chat and chat.type in ["channel", "group", "supergroup"]:
            return True
        return False

    user_id = user.id
    if is_super_admin(user_id):
        return True

    if chat:
        owner_id, tenant_cfg = get_tenant_by_chat(chat.id)
        if owner_id and (user_id == owner_id or user_id in tenant_cfg.get("co_owners", [])):
            return True

        if chat.type in ["group", "supergroup", "channel"]:
            try:
                member = await context.bot.get_chat_member(chat.id, user_id)
                if member.status in ["administrator", "creator"]:
                    return True
            except Exception as e:
                logger.error(f"Error checking chat permissions: {e}")

    owner_str = str(user_id)
    if owner_str in GLOBAL_CONFIG.get("tenants", {}):
        return True

    return False

# ================= MULTI-TENANT USER & SETUP FLOWS =================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Universal Start Command: Distinguishes between customers and room managers."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    is_admin = await is_admin_or_owner(update, context)
    allow_admin = GLOBAL_CONFIG.get("settings", {}).get("allow_admin_member_cmds", False)

    if is_admin and not allow_admin and msg.chat.type != "private":
        await msg.reply_text(
            "ℹ️ **ADMIN NOTICE**\n\n"
            "Member checkout (`/start`) is currently hidden for admins in group chats.\n"
            "• Type `/admin` to open your **Admin Control Panel**.",
            parse_mode="Markdown"
        )
        return

    tenant_cfg = get_tenant_config(user.id)
    shop_name = tenant_cfg.get("shop_name", "Digital Vault Store")

    keyboard = [
        [InlineKeyboardButton("🛒 Browse Store & Buy Access", callback_data=f"mode_customer_{user.id}")],
        [InlineKeyboardButton("⚙️ Setup & Manage My Own Vault / Groups", callback_data=f"mode_manager_{user.id}")],
    ]

    welcome_text = (
        f"👋 **Welcome to {shop_name}, {user.full_name}!**\n\n"
        "How would you like to proceed?\n\n"
        "• Click **Browse Store** to view products and purchase access.\n"
        "• Click **Setup & Manage My Own Vault** to use this bot for managing your own Telegram channels, groups, payment links, and automated course indexing!"
    )
    await msg.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_mode_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    if data.startswith("mode_customer"):
        parts = data.split("_")
        owner_id = int(parts[2]) if len(parts) > 2 else user.id
        tenant_cfg = get_tenant_config(owner_id)
        shop_name = tenant_cfg.get("shop_name", "Digital Vault Store")

        template = tenant_cfg["messages"].get("welcome", DEFAULT_TENANT_CONFIG["messages"]["welcome"])
        welcome_text = template.replace("{name}", user.full_name).replace("{shop_name}", shop_name)

        keyboard = []
        payments = tenant_cfg.get("payments", DEFAULT_TENANT_CONFIG["payments"])
        for key, val in payments.items():
            title_line = val.split("\n")[0].replace("*", "").replace("📱", "").replace("🏦", "").replace("💰", "").strip()
            keyboard.append([InlineKeyboardButton(title_line, callback_data=f"payusr_{owner_id}_{key}")])

        await query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("mode_manager"):
        tenant_cfg = get_tenant_config(user.id)
        hub_id = tenant_cfg.get("main_hub_id", 0)
        admin_id = tenant_cfg.get("admin_proof_group_id", 0)
        proof_id = tenant_cfg.get("proof_archive_id", 0)

        manager_text = (
            f"🛠️ **VAULT MANAGER SELF-SERVICE DESK**\n\n"
            f"Hello {user.full_name}! You have full control to manage your own Telegram channels, groups, automated indexing, and receipt approvals.\n\n"
            "📋 **YOUR ACTIVE ROOM CONFIGURATION:**\n"
            f"• 📍 **Main Hub Directory:** `{hub_id if hub_id else 'Not Set'}`\n"
            f"• 📍 **Admin Verification Group:** `{admin_id if admin_id else 'Not Set'}`\n"
            f"• 📍 **Proof Archive:** `{proof_id if proof_id else 'Not Set'}`\n\n"
            "────────────────────────────────────────\n"
            "🚀 **HOW TO SETUP YOUR ROOMS:**\n"
            "1️⃣ Add this bot as an **Administrator** in your target group or channel.\n"
            "2️⃣ Open your Main Hub Directory channel and type `/sethub`.\n"
            "3️⃣ Open your Admin Review group and type `/setadmin`.\n"
            "4️⃣ Open your Proof Archive channel and type `/setproof`.\n"
            "5️⃣ Setup your payment accounts using `/setpayment gcash <Number> | <Name>`.\n"
            "6️⃣ Inspect all indexed videos & ebook files anytime using `/viewvault`!\n\n"
            "💡 Type `/admin` in your group or here anytime to open your full management panel."
        )
        await query.edit_message_text(manager_text, parse_mode="Markdown")

async def member_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    is_admin = await is_admin_or_owner(update, context)
    allow_admin = GLOBAL_CONFIG.get("settings", {}).get("allow_admin_member_cmds", False)

    if is_admin and not allow_admin and msg.chat.type != "private":
        await msg.reply_text(
            "ℹ️ **ADMIN NOTICE**\n\n"
            "Member help instructions (`/help`) are currently hidden for Admins in groups to keep your view clean.\n"
            "• Type `/admin` to open the **Admin Control Desk**.",
            parse_mode="Markdown"
        )
        return

    tenant_cfg = get_tenant_config(user.id)
    template = tenant_cfg["messages"].get("help", DEFAULT_TENANT_CONFIG["messages"]["help"])
    text = template.replace("{name}", user.full_name)
    await msg.reply_text(text, parse_mode="Markdown")

async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not update.message or not update.message.new_chat_members:
        return

    for new_member in update.message.new_chat_members:
        if new_member.id == context.bot.id:
            await msg.reply_text(
                "🤖 **Digital Vault Manager Bot Online!**\n\n"
                "Thank you for adding me to this room! Admins can run setup commands here:\n"
                "• `/sethub` (or `/sethub remove`) - Bind / Unbind Main Hub Directory\n"
                "• `/setadmin` (or `/setadmin remove`) - Bind / Unbind Admin Verification Group\n"
                "• `/setproof` (or `/setproof remove`) - Bind / Unbind Proof Archive\n"
                "• `/admin` - Open Control Desk",
                parse_mode="Markdown"
            )
            continue

        owner_id, tenant_cfg = get_tenant_by_chat(msg.chat.id)
        if not tenant_cfg:
            tenant_cfg = get_tenant_config(new_member.id)

        shop_name = tenant_cfg.get("shop_name", "Digital Vault Store")
        template = tenant_cfg["messages"].get("welcome", DEFAULT_TENANT_CONFIG["messages"]["welcome"])
        welcome_text = template.replace("{name}", new_member.full_name).replace("{shop_name}", shop_name)
        help_template = tenant_cfg["messages"].get("help", DEFAULT_TENANT_CONFIG["messages"]["help"]).replace("{name}", new_member.full_name)

        full_welcome_text = (
            f"👋 **Welcome to the group, {new_member.full_name}!**\n\n"
            f"{welcome_text}\n\n"
            f"────────────────────────────────────────\n"
            f"📖 **ONBOARDING HELP:**\n"
            f"{help_template}"
        )

        await msg.reply_text(full_welcome_text, parse_mode="Markdown")

# ================= TELEGRAM JUMP LINK INSPECTOR FOR REAL OWNER =================

async def open_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows Master Super Admins and Vault Owners to inspect and open any Telegram jump link directly."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Only administrators or vault owners can inspect links.")
        return

    text = msg.text or ""
    links = re.findall(r"https://t\.me/c/(\d+)/(?:(\d+)/)?(\d+)", text)

    if not links and context.args:
        arg_text = " ".join(context.args)
        links = re.findall(r"https://t\.me/c/(\d+)/(?:(\d+)/)?(\d+)", arg_text)

    if not links:
        await msg.reply_text(
            "⚠️ **Usage:** Send or paste a Telegram jump link, e.g.:\n"
            "`/openlink https://t.me/c/123456789/45`\n"
            "or simply paste the jump link directly in a private DM with the bot!",
            parse_mode="Markdown"
        )
        return

    for link_match in links:
        raw_chat_id = link_match[0]
        thread_id = link_match[1] if link_match[1] else None
        msg_id = link_match[2]

        full_chat_id = int(f"-100{raw_chat_id}")
        chat_data = VAULT_STATE.get(full_chat_id, {})
        cat_name = chat_data.get("category_name", f"Chat {full_chat_id}")
        courses = chat_data.get("courses", {})

        found_item = None
        found_course = None

        for c_key, c_info in courses.items():
            for item in c_info.get("items", []):
                if str(item.get("msg_id")) == str(msg_id):
                    found_item = item
                    found_course = c_info
                    break
            if found_item:
                break

        full_link = f"https://t.me/c/{raw_chat_id}/{thread_id}/{msg_id}" if thread_id else f"https://t.me/c/{raw_chat_id}/{msg_id}"

        if found_item and found_course:
            icon = "🎬" if found_item.get("type") == "video" else "📚"
            reply_text = (
                f"🔍 **INDEXED VAULT FILE FOUND!**\n\n"
                f"📁 **Category:** {cat_name}\n"
                f"📖 **Module:** {found_course.get('display_title')}\n"
                f"{icon} **Item #{found_item.get('num')}:** {found_item.get('title')}\n"
                f"🆔 **Message ID:** `{msg_id}`\n\n"
                f"🔗 **Direct Link:** [{full_link}]({full_link})"
            )
        else:
            reply_text = (
                f"🔍 **TELEGRAM JUMP LINK INSPECTOR**\n\n"
                f"📁 **Chat ID:** `{full_chat_id}`\n"
                f"🆔 **Message ID:** `{msg_id}`\n"
                f"📍 **Thread ID:** `{thread_id if thread_id else 'Main Chat'}`\n\n"
                f"🔗 **Direct Link:** [{full_link}]({full_link})\n\n"
                f"ℹ️ _Note: Click the link above to view or download the file/video inside Telegram._"
            )

        await msg.reply_text(reply_text, parse_mode="Markdown", disable_web_page_preview=False)

async def handle_direct_link_paste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically detects and inspects Telegram jump links pasted into private DM with the bot."""
    msg = update.effective_message
    if not msg or msg.chat.type != "private":
        return

    text = msg.text or ""
    if "t.me/c/" in text:
        await open_link_command(update, context)

# ================= VAULT CONTENT INSPECTOR & FILE BROWSER =================

async def view_vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Administrator or Vault Owner permission required.")
        return

    if not VAULT_STATE:
        await msg.reply_text("📂 **Vault Inspector:** No indexed content or courses found yet.")
        return

    keyboard = []
    for chat_id, data in VAULT_STATE.items():
        cat_name = data.get("category_name", f"Chat {chat_id}")
        keyboard.append([InlineKeyboardButton(f"📁 Browse: {cat_name}", callback_data=f"browsechat_{chat_id}")])

    await msg.reply_text(
        "🔍 **VAULT CONTENT & FILE INSPECTOR**\n\nSelect a channel/group below to view all indexed videos, ebooks, and modules:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_vault_browser_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("browsechat_"):
        chat_id = int(data.replace("browsechat_", ""))
        chat_data = VAULT_STATE.get(chat_id, {})
        cat_name = chat_data.get("category_name", "Vault")
        courses = chat_data.get("courses", {})

        if not courses:
            await query.edit_message_text(f"📂 **{cat_name}:** No modules indexed yet.")
            return

        keyboard = []
        for norm_key, info in courses.items():
            title = info.get("display_title", norm_key)
            item_count = info.get("file_count", 0)
            keyboard.append([InlineKeyboardButton(f"📖 {title} ({item_count} items)", callback_data=f"browsetit_{chat_id}_{norm_key[:20]}")])

        keyboard.append([InlineKeyboardButton("🔙 Back to Vaults", callback_data="browse_BACK")])
        await query.edit_message_text(f"📁 **CATEGORY:** {cat_name}\nSelect a course module to view files:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("browsetit_"):
        parts = data.split("_", 2)
        chat_id = int(parts[1])
        short_key = parts[2]
        chat_data = VAULT_STATE.get(chat_id, {})
        courses = chat_data.get("courses", {})

        target_course = None
        for key, info in courses.items():
            if key.startswith(short_key):
                target_course = info
                break

        if not target_course:
            await query.edit_message_text("❌ Module files not found.")
            return

        items = target_course.get("items", [])
        title = target_course.get("display_title", "Module")

        text = f"📖 **MODULE:** {title}\n📊 **Total Indexed Files:** {len(items)}\n────────────────────────────────────────\n"
        for item in items[:15]:
            icon = "🎬" if item.get("type") == "video" else "📚"
            text += f"{icon} **#{item.get('num')}:** [{item.get('title')}]({item.get('link')})\n"

        keyboard = [[InlineKeyboardButton("🔙 Back to Category", callback_data=f"browsechat_{chat_id}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", disable_web_page_preview=True)

    elif data == "browse_BACK":
        keyboard = []
        for chat_id, data_val in VAULT_STATE.items():
            cat_name = data_val.get("category_name", f"Chat {chat_id}")
            keyboard.append([InlineKeyboardButton(f"📁 Browse: {cat_name}", callback_data=f"browsechat_{chat_id}")])

        await query.edit_message_text("🔍 **VAULT CONTENT & FILE INSPECTOR**", reply_markup=InlineKeyboardMarkup(keyboard))

# ================= DYNAMIC ROOM BINDING COMMANDS (MULTI-TENANT) =================

async def set_hub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not chat or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Only administrators or room owners can set room roles.")
        return

    tenant_cfg = get_tenant_config(user.id)
    chat_str = str(chat.id)
    args = [a.lower() for a in context.args] if context.args else []

    if any(kw in args for kw in ["remove", "clear", "unset", "off", "del"]) or (tenant_cfg.get("main_hub_id") == chat.id and not args):
        tenant_cfg["main_hub_id"] = 0
        GLOBAL_CONFIG.get("chat_tenant_map", {}).pop(chat_str, None)
        save_config(GLOBAL_CONFIG)
        await msg.reply_text("🗑️ Chat **unbound / removed** as your Main Hub Directory!", parse_mode="Markdown")
        return

    tenant_cfg["main_hub_id"] = chat.id
    GLOBAL_CONFIG.setdefault("chat_tenant_map", {})[chat_str] = user.id
    save_config(GLOBAL_CONFIG)

    await msg.reply_text(
        f"✅ **SUCCESS!** Current chat (`{chat.id}`) registered as **YOUR MAIN HUB DIRECTORY**!\n"
        f"👤 **Vault Owner:** {user.full_name} (`{user.id}`)\n\n"
        "💡 _To unbind later, type `/sethub remove` or `/sethub` again in this chat._",
        parse_mode="Markdown"
    )

async def set_admin_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not chat or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Administrator permission required.")
        return

    tenant_cfg = get_tenant_config(user.id)
    chat_str = str(chat.id)
    args = [a.lower() for a in context.args] if context.args else []

    if any(kw in args for kw in ["remove", "clear", "unset", "off", "del"]) or (tenant_cfg.get("admin_proof_group_id") == chat.id and not args):
        tenant_cfg["admin_proof_group_id"] = 0
        GLOBAL_CONFIG.get("chat_tenant_map", {}).pop(chat_str, None)
        save_config(GLOBAL_CONFIG)
        await msg.reply_text("🗑️ Group **unbound / removed** as your Admin Verification Group!", parse_mode="Markdown")
        return

    tenant_cfg["admin_proof_group_id"] = chat.id
    GLOBAL_CONFIG.setdefault("chat_tenant_map", {})[chat_str] = user.id
    save_config(GLOBAL_CONFIG)

    await msg.reply_text(
        f"✅ **SUCCESS!** Current group (`{chat.id}`) registered as **YOUR ADMIN VERIFICATION GROUP**!\n"
        f"👤 **Vault Owner:** {user.full_name} (`{user.id}`)\n\n"
        "💡 _Receipt screenshot submissions from your customers will be forwarded here for approval!_",
        parse_mode="Markdown"
    )

async def set_proof_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not chat or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Administrator permission required.")
        return

    tenant_cfg = get_tenant_config(user.id)
    chat_str = str(chat.id)
    args = [a.lower() for a in context.args] if context.args else []

    if any(kw in args for kw in ["remove", "clear", "unset", "off", "del"]) or (tenant_cfg.get("proof_archive_id") == chat.id and not args):
        tenant_cfg["proof_archive_id"] = 0
        GLOBAL_CONFIG.get("chat_tenant_map", {}).pop(chat_str, None)
        save_config(GLOBAL_CONFIG)
        await msg.reply_text("🗑️ Chat **unbound / removed** as your Proof Archive!", parse_mode="Markdown")
        return

    tenant_cfg["proof_archive_id"] = chat.id
    GLOBAL_CONFIG.setdefault("chat_tenant_map", {})[chat_str] = user.id
    save_config(GLOBAL_CONFIG)

    await msg.reply_text(
        f"✅ **SUCCESS!** Current chat (`{chat.id}`) registered as **YOUR PROOF ARCHIVE**!\n"
        f"👤 **Vault Owner:** {user.full_name} (`{user.id}`)",
        parse_mode="Markdown"
    )

# ================= ADMIN CONTROL DESK & PROFILE SETUP =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    if not await is_admin_or_owner(update, context):
        await msg.reply_text("⛔ **Access Denied:** Only administrators or vault owners can access this panel.")
        return

    tenant_cfg = get_tenant_config(user.id)
    shop_name = tenant_cfg.get("shop_name", "Digital Vault Store")

    admin_help_text = (
        f"🛠️ **ADMIN CONTROL DESK: {shop_name.upper()}**\n\n"
        "🤖 **Bot Profile Commands:**\n"
        "• `/setbotname <Name>` - Change bot display name live\n"
        "• `/setbotusername` - View current username & change guide\n\n"
        "📍 **Room Setup & Binding (Run in target chats):**\n"
        "• `/sethub` (or `/sethub remove`) - Bind/Unbind Main Hub Directory\n"
        "• `/setadmin` (or `/setadmin remove`) - Bind/Unbind Admin Review Group\n"
        "• `/setproof` (or `/setproof remove`) - Bind/Unbind Proof Archive\n\n"
        "🔍 **File & Video Inspection:**\n"
        "• `/viewvault` - Inspect and browse all uploaded videos & ebooks\n"
        "• `/openlink <link>` - Inspect any Telegram jump link directly\n\n"
        "💳 **Payment Management:**\n"
        "• `/setpayment gcash <Number> | <Name>`\n"
        "• `/addpayment <key> <Label> | <Instructions>`\n"
        "• `/delpayment <key>`\n\n"
        "💬 **Custom Messages & Settings:**\n"
        "• `/setmsg welcome|help|receipt <Text|reset>`\n"
        "• `/setconfig shop_name <New Name>` - Change your shop title\n"
        "• `/addcoowner <User_ID>` - Add co-administrator ID\n\n"
        "📢 **Content & Group Moderation:**\n"
        "• `/promote <Message>` - Broadcast promotional posts\n"
        "• `/groupmodule <Category> <Title> | <Items>`\n"
        "• `/renameitem <Category> <Old> | <New>`\n"
        "• `/addbadword <word>` - Add word to group auto-moderation\n"
        "• `/delindex` - Remove course module from index\n"
        "• `/config` - View active configuration audit"
    )
    await msg.reply_text(admin_help_text, parse_mode="Markdown")

async def add_coowner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args:
        await msg.reply_text("⚠️ **Usage:** `/addcoowner <USER_ID>`", parse_mode="Markdown")
        return

    try:
        new_co_id = int(args[0])
        tenant_cfg = get_tenant_config(user.id)
        co_list = tenant_cfg.setdefault("co_owners", [])
        if new_co_id not in co_list:
            co_list.append(new_co_id)
            save_config(GLOBAL_CONFIG)
            await msg.reply_text(f"✅ **Success!** Added User ID `{new_co_id}` as Co-Owner for your store!", parse_mode="Markdown")
        else:
            await msg.reply_text(f"ℹ️ User ID `{new_co_id}` is already a co-owner.")
    except ValueError:
        await msg.reply_text("❌ Invalid User ID format. Must be numerical.")

async def set_bot_name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Administrator permission required.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/setbotname <NEW_BOT_NAME>`", parse_mode="Markdown")
        return

    new_name = " ".join(context.args).strip()
    try:
        await context.bot.set_my_name(name=new_name)
        await update.message.reply_text(f"✅ **SUCCESS!** Bot display name updated to: `{new_name}`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to set bot name: {e}")
        await update.message.reply_text(f"❌ Error updating bot name: {e}")

async def set_bot_username_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Administrator permission required.")
        return

    bot_info = await context.bot.get_me()
    guide_text = (
        f"🤖 **BOT PROFILE INFORMATION**\n\n"
        f"📛 **Display Name:** `{bot_info.first_name}`\n"
        f"👤 **Username:** @{bot_info.username}\n"
        f"🆔 **Bot User ID:** `{bot_info.id}`\n\n"
        "────────────────────────────────────────\n"
        "ℹ️ **TO CHANGE BOT USERNAME (@handle):**\n"
        "1. Open Telegram and search for `@BotFather`.\n"
        "2. Send `/setusername` to `@BotFather`.\n"
        "3. Select this bot and enter your new username ending in `bot`."
    )
    await update.message.reply_text(guide_text, parse_mode="Markdown")

# ================= PAYMENTS, MODERATION & SECURITY =================

async def set_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args or len(args) < 2:
        await msg.reply_text("⚠️ **Usage:** `/setpayment gcash <Number> | <Name>`", parse_mode="Markdown")
        return

    tenant_cfg = get_tenant_config(user.id)
    method_key = args[0].lower()
    payload = " ".join(args[1:])
    parts = [p.strip() for p in payload.split("|")]

    if method_key == "gcash":
        tenant_cfg["payments"]["pay_gcash"] = f"📱 **GCash Payment**\nNumber: `{parts[0]}`\nAccount Name: {parts[1] if len(parts) > 1 else 'N/A'}"
    elif method_key == "maya":
        tenant_cfg["payments"]["pay_maya"] = f"📱 **Maya Payment**\nNumber: `{parts[0]}`\nAccount Name: {parts[1] if len(parts) > 1 else 'N/A'}"
    elif method_key in ["bank", "maribank"]:
        tenant_cfg["payments"]["pay_bank"] = f"🏦 **{parts[1] if len(parts) > 1 else 'Bank'} Payment**\nAccount Number: `{parts[0]}`\nAccount Name: {parts[2] if len(parts) > 2 else 'N/A'}"

    save_config(GLOBAL_CONFIG)
    await msg.reply_text(f"✅ **Success!** Updated **{method_key.upper()}** payment info!", parse_mode="Markdown")

async def add_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args or len(args) < 2:
        await msg.reply_text("⚠️ **Usage:** `/addpayment crypto USDT | Address: TXYZ...`", parse_mode="Markdown")
        return

    tenant_cfg = get_tenant_config(user.id)
    pay_key = f"pay_{args[0].lower()}"
    payload = " ".join(args[1:])
    parts = [p.strip() for p in payload.split("|")]

    label = parts[0]
    instructions = " | ".join(parts[1:]) if len(parts) > 1 else label
    tenant_cfg["payments"][pay_key] = f"💰 **{label}**\n{instructions}"

    save_config(GLOBAL_CONFIG)
    await msg.reply_text(f"✅ **Success!** Added custom payment option `{pay_key}`!", parse_mode="Markdown")

async def del_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args:
        await msg.reply_text("⚠️ **Usage:** `/delpayment <key>`")
        return

    tenant_cfg = get_tenant_config(user.id)
    pay_key = f"pay_{args[0].lower()}"
    if pay_key in tenant_cfg["payments"]:
        del tenant_cfg["payments"][pay_key]
        save_config(GLOBAL_CONFIG)
        await msg.reply_text(f"✅ Removed payment option `{pay_key}`.", parse_mode="Markdown")
    else:
        await msg.reply_text(f"❌ Payment option `{pay_key}` not found.")

async def payment_option_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("payusr_"):
        parts = data.split("_", 2)
        owner_id = int(parts[1])
        method = parts[2]
        tenant_cfg = get_tenant_config(owner_id)
    else:
        method = data
        tenant_cfg = get_tenant_config(query.from_user.id)

    instructions = tenant_cfg.get("payments", {}).get(method, "Payment details not configured.")
    instructions_text = f"{instructions}\n\n📸 **INSTRUCTIONS:** Send your receipt screenshot directly here."
    await query.edit_message_text(instructions_text, parse_mode="Markdown")

async def handle_photo_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file_id = update.message.photo[-1].file_id

    owner_id, tenant_cfg = get_tenant_by_chat(update.effective_chat.id)
    if not tenant_cfg:
        owner_id = user.id
        tenant_cfg = get_tenant_config(user.id)

    admin_group_id = tenant_cfg.get("admin_proof_group_id")
    if not admin_group_id:
        await update.message.reply_text("⚠️ Payment group is not configured for this vault. Ask the owner to run `/setadmin` in their verification group.")
        return

    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}_{owner_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}_{owner_id}")]
    ]
    await context.bot.send_photo(
        chat_id=admin_group_id,
        photo=photo_file_id,
        caption=f"📥 **NEW RECEIPT SUBMISSION**\n👤 **Buyer:** {user.full_name} (`{user.id}`)\n💬 **Username:** @{user.username if user.username else 'N/A'}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

    template = tenant_cfg["messages"].get("receipt", DEFAULT_TENANT_CONFIG["messages"]["receipt"])
    await update.message.reply_text(template.replace("{name}", user.full_name), parse_mode="Markdown")

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[0]
    buyer_id = int(data[1])
    owner_id = int(data[2]) if len(data) > 2 else query.from_user.id

    tenant_cfg = get_tenant_config(owner_id)
    main_hub_id = tenant_cfg.get("main_hub_id")
    proof_archive_id = tenant_cfg.get("proof_archive_id")

    if action == "approve":
        try:
            invite_link = await context.bot.create_chat_invite_link(chat_id=main_hub_id, member_limit=1)
            await context.bot.send_message(chat_id=buyer_id, text=f"🎉 **Payment Approved! Join Hub:** {invite_link.invite_link}")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\nSTATUS: ✅ **APPROVED BY ADMIN**")

            if proof_archive_id:
                await context.bot.forward_message(chat_id=proof_archive_id, from_chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception as e:
            logger.error(f"Approval error: {e}")
            await query.message.reply_text(f"❌ Approval error: {e}")
    elif action == "reject":
        await context.bot.send_message(chat_id=buyer_id, text="❌ **Verification failed.** Please check your reference number and submit a clear screenshot.")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\nSTATUS: ❌ **REJECTED BY ADMIN**")

# ================= SECURITY THREAT DETECTOR & GROUP MODERATION =================

async def security_threat_detector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat = msg.chat
    if chat.type not in ["group", "supergroup"]:
        return

    user = msg.from_user
    if is_super_admin(user.id):
        return

    text_content = (msg.text or msg.caption or "").lower()
    sec_cfg = DEFAULT_TENANT_CONFIG["security"]

    threat_detected = False
    violation_reason = ""

    for keyword in sec_cfg["phishing_keywords"]:
        if keyword in text_content:
            threat_detected = True
            violation_reason = f"Phishing keyword detected: `{keyword}`"
            break

    if msg.document:
        doc_name = msg.document.file_name.lower()
        for ext in sec_cfg["suspicious_extensions"]:
            if doc_name.endswith(ext):
                threat_detected = True
                violation_reason = f"Suspicious file attachment: `{ext}`"
                break

    if threat_detected:
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Failed to delete malicious message: {e}")

        keyboard = [
            [
                InlineKeyboardButton("🥾 Kick & Ban User", callback_data=f"seckick_ban_{user.id}_{chat.id}"),
                InlineKeyboardButton("🛡️ Keep & Dismiss", callback_data=f"seckick_keep_{user.id}")
            ]
        ]
        alert_text = (
            f"🚨 **SECURITY ALERT: POTENTIAL THREAT DETECTED!** 🚨\n\n"
            f"👤 **User:** {user.full_name} (`{user.id}`)\n"
            f"💬 **Group:** {chat.title} (`{chat.id}`)\n"
            f"⚠️ **Reason:** {violation_reason}\n\n"
            f"👉 Message was automatically deleted. Select action below:"
        )

        for s_admin_id in GLOBAL_CONFIG.get("super_admin_ids", SUPER_ADMIN_IDS):
            try:
                await context.bot.send_message(chat_id=s_admin_id, text=alert_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to notify super admin {s_admin_id}: {e}")

async def handle_security_kick_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[1]
    user_id = int(data[2])
    chat_id = int(data[3]) if len(data) > 3 else None

    if action == "ban" and chat_id:
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await query.edit_message_text(text=f"{query.message.text}\n\nSTATUS: ✅ **USER BANNED & KICKED**", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to ban user: {e}")
            await query.edit_message_text(text=f"{query.message.text}\n\nSTATUS: ❌ **Failed to ban user:** {e}")
    else:
        await query.edit_message_text(text=f"{query.message.text}\n\nSTATUS: 🛡️ **ALERT DISMISSED**", parse_mode="Markdown")

async def group_moderation_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat = msg.chat
    if chat.type not in ["group", "supergroup"]:
        return

    if await is_admin_or_owner(update, context):
        return

    owner_id, tenant_cfg = get_tenant_by_chat(chat.id)
    if not tenant_cfg:
        tenant_cfg = DEFAULT_TENANT_CONFIG

    mod_cfg = tenant_cfg.get("moderation", DEFAULT_TENANT_CONFIG["moderation"])
    if not mod_cfg.get("enabled", True):
        return

    text = (msg.text or msg.caption or "").lower()

    for word in mod_cfg.get("bad_words", []):
        if word in text:
            try:
                await msg.delete()
                warning = await chat.send_message(f"⚠️ {msg.from_user.mention_html()}, message removed for violating moderation rules.", parse_mode="HTML")
                await asyncio.sleep(4)
                await warning.delete()
            except Exception as e:
                logger.error(f"Moderation error: {e}")
            return

async def add_bad_word_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    if not context.args:
        await msg.reply_text("⚠️ **Usage:** `/addbadword <word>`")
        return

    word = context.args[0].lower()
    tenant_cfg = get_tenant_config(user.id)
    bad_words = tenant_cfg.setdefault("moderation", {}).setdefault("bad_words", [])

    if word not in bad_words:
        bad_words.append(word)
        save_config(GLOBAL_CONFIG)
        await msg.reply_text(f"✅ Added `{word}` to moderation blocklist!", parse_mode="Markdown")
    else:
        await msg.reply_text(f"ℹ️ Word `{word}` is already in the blocklist.")

# ================= AUTOMATED CONTENT INDEXING =================

async def auto_index_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.message
    if not post:
        return

    chat_id = post.chat_id
    owner_id, tenant_cfg = get_tenant_by_chat(chat_id)
    if not tenant_cfg:
        return

    main_hub_id = tenant_cfg.get("main_hub_id")
    if not main_hub_id or chat_id in [main_hub_id, tenant_cfg.get("admin_proof_group_id"), tenant_cfg.get("proof_archive_id")]:
        return

    category_name = post.chat.title if post.chat.title else "Vault Content"
    clean_chat_id = str(chat_id).replace("-100", "")
    thread_id = getattr(post, "message_thread_id", None)

    if chat_id not in VAULT_STATE:
        VAULT_STATE[chat_id] = {"category_name": category_name, "active_course": "General Library", "courses": {}}
    else:
        VAULT_STATE[chat_id]["category_name"] = category_name

    extracted_text = post.text or post.caption

    if (post.text and not post.video and not post.document) or (post.forward_origin and post.text and not post.video and not post.document):
        raw_title = post.text.strip()
        if raw_title.startswith("/"):
            return

        norm_key = normalize_title(raw_title)
        VAULT_STATE[chat_id]["active_course"] = norm_key

        if norm_key not in VAULT_STATE[chat_id]["courses"]:
            VAULT_STATE[chat_id]["courses"][norm_key] = {"display_title": raw_title, "file_count": 0, "items": []}
            status_msg = f"📌 **NEW MODULE ADDED TO {category_name.upper()}**\n\n📖 **Title:** `{raw_title}`"
        else:
            current_count = VAULT_STATE[chat_id]["courses"][norm_key]["file_count"]
            status_msg = f"🔄 **RE-OPENED MODULE IN {category_name.upper()}**\n\n📖 **Title:** `{raw_title}`\n📊 **Current Total Files:** {current_count}"

        save_state(VAULT_STATE)
        await context.bot.send_message(chat_id=main_hub_id, text=f"{status_msg}\n────────────────────────────────────────", parse_mode="Markdown")
        return

    if post.video or post.document:
        active_key = VAULT_STATE[chat_id].get("active_course", "General Library")
        if active_key not in VAULT_STATE[chat_id]["courses"]:
            VAULT_STATE[chat_id]["courses"][active_key] = {"display_title": active_key.title(), "file_count": 0, "items": []}

        VAULT_STATE[chat_id]["courses"][active_key]["file_count"] += 1
        file_num = VAULT_STATE[chat_id]["courses"][active_key]["file_count"]
        display_title = VAULT_STATE[chat_id]["courses"][active_key]["display_title"]

        content_type_icon = "🎬" if post.video else "📚"
        item_label = f"Lesson {file_num}" if post.video else f"Ebook Part {file_num}"
        caption_title = extracted_text.split("\n")[0] if extracted_text else item_label
        direct_link = f"https://t.me/c/{clean_chat_id}/{thread_id}/{post.message_id}" if thread_id else f"https://t.me/c/{clean_chat_id}/{post.message_id}"

        item_info = {
            "type": "video" if post.video else "document",
            "num": file_num,
            "title": caption_title,
            "link": direct_link,
            "msg_id": post.message_id
        }
        VAULT_STATE[chat_id]["courses"][active_key].setdefault("items", []).append(item_info)
        save_state(VAULT_STATE)

        lesson_entry = (
            f"📁 **Category:** {category_name}\n"
            f"📖 **Module:** {display_title}\n"
            f"{content_type_icon} **#{file_num}:** [{caption_title}]({direct_link})\n\n"
            f"👉 _Click the link above to jump directly to this material!_"
        )

        await context.bot.send_message(chat_id=main_hub_id, text=lesson_entry, parse_mode="Markdown", disable_web_page_preview=True)

# ================= ADVANCED MODULE GROUPING & RENAMING =================

async def group_module_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    if not context.args:
        await msg.reply_text("⚠️ **Usage:** `/groupmodule Game Dev Master Bundle | Lesson 1, Lesson 2`", parse_mode="Markdown")
        return

    payload = " ".join(context.args)
    if "|" not in payload:
        await msg.reply_text("❌ Please use `|` to separate the title from included items.")
        return

    left_part, right_part = payload.split("|", 1)
    master_title = left_part.strip()
    items_to_group = [i.strip() for i in right_part.split(",")]

    tenant_cfg = get_tenant_config(user.id)
    main_hub_id = tenant_cfg.get("main_hub_id")
    if not main_hub_id:
        await msg.reply_text("⚠️ Main Hub ID not set.")
        return

    bundle_text = f"📦 **MASTER BUNDLE:** `{master_title}`\n────────────────────────────────────────\n"
    for idx, item in enumerate(items_to_group, 1):
        bundle_text += f"• Part {idx}: {item}\n"

    bundle_text += "\n👉 _All selected lessons bundled into one master link!_"
    await context.bot.send_message(chat_id=main_hub_id, text=bundle_text, parse_mode="Markdown")
    await msg.reply_text(f"✅ Bundle `{master_title}` created and posted to Main Hub!")

async def rename_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    payload = " ".join(context.args)
    if "|" not in payload:
        await msg.reply_text("⚠️ **Usage:** `/renameitem Game Dev Intro | Advanced Unity 2026`", parse_mode="Markdown")
        return

    old_title, new_title = [p.strip() for p in payload.split("|", 1)]
    renamed_count = 0

    for chat_id, data in VAULT_STATE.items():
        courses = data.get("courses", {})
        for k, c_info in list(courses.items()):
            if old_title.lower() in c_info.get("display_title", "").lower():
                c_info["display_title"] = new_title
                renamed_count += 1

    save_state(VAULT_STATE)
    await msg.reply_text(f"✅ Renamed {renamed_count} entries to `{new_title}`.", parse_mode="Markdown")

async def del_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    if not VAULT_STATE:
        await msg.reply_text("ℹ️ No indexed courses found.")
        return

    keyboard = []
    for chat_id, data in VAULT_STATE.items():
        cat_name = data.get("category_name", f"Chat {chat_id}")
        for course_key, info in data.get("courses", {}).items():
            title = info.get("display_title", course_key)
            keyboard.append([InlineKeyboardButton(f"🗑️ Delete: [{cat_name}] {title}", callback_data=f"delmod_{chat_id}_{course_key[:20]}")])

    await msg.reply_text("🗑️ Select a module to remove from index records:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_del_index_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)
    chat_id = int(parts[1])
    short_key = parts[2]

    if chat_id in VAULT_STATE:
        target_key = None
        for key in VAULT_STATE[chat_id].get("courses", {}):
            if key.startswith(short_key):
                target_key = key
                break
        if target_key:
            del VAULT_STATE[chat_id]["courses"][target_key]
            save_state(VAULT_STATE)
            await query.edit_message_text("✅ Removed module from index records.")
            return

    await query.edit_message_text("❌ Module not found.")

# ================= CONFIG AUDIT & ADVANCED UTILITIES =================

async def set_msg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args or len(args) < 2:
        await msg.reply_text("⚠️ **Usage:** `/setmsg welcome|help|receipt <Text|reset>`", parse_mode="Markdown")
        return

    msg_type = args[0].lower()
    text_val = " ".join(args[1:])
    tenant_cfg = get_tenant_config(user.id)

    if msg_type in ["welcome", "help", "receipt"]:
        if text_val.lower() in ["reset", "remove", "default", "clear"]:
            tenant_cfg["messages"][msg_type] = DEFAULT_TENANT_CONFIG["messages"][msg_type]
            await msg.reply_text(f"🔄 Reset `{msg_type}` message to default!")
        else:
            tenant_cfg["messages"][msg_type] = text_val
            await msg.reply_text(f"✅ Updated `{msg_type}` message template!")
        save_config(GLOBAL_CONFIG)

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args:
        await msg.reply_text("⚠️ **Usage:** `/promote <Message>`")
        return

    promo_text = " ".join(args)
    PENDING_PROMOTIONS[user.id] = promo_text

    keyboard = []
    for chat_id, data in VAULT_STATE.items():
        cat_name = data.get("category_name", f"Chat {chat_id}")
        keyboard.append([InlineKeyboardButton(f"📤 Post to: {cat_name}", callback_data=f"sendpromo_{chat_id}")])

    keyboard.append([InlineKeyboardButton("🌐 Broadcast ALL Chats", callback_data="sendpromo_ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sendpromo_CANCEL")])

    await msg.reply_text(f"📢 **PROMOTION PREVIEW:**\n{promo_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_promotion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in PENDING_PROMOTIONS:
        await query.edit_message_text("⚠️ Promotion session expired.")
        return

    target = query.data.replace("sendpromo_", "")
    promo_text = PENDING_PROMOTIONS.pop(user_id)

    if target == "CANCEL":
        await query.edit_message_text("❌ Promotion cancelled.")
        return

    target_chats = list(VAULT_STATE.keys()) if target == "ALL" else [int(target)]
    sent_count = 0

    for c_id in target_chats:
        try:
            await context.bot.send_message(chat_id=c_id, text=promo_text, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed promotion post: {e}")

    await query.edit_message_text(f"🚀 Promotion sent to {sent_count} target location(s)!")

async def set_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    args = context.args
    if not args or len(args) < 2:
        await msg.reply_text("⚠️ **Usage:** `/setconfig shop_name Digital Vault Store`", parse_mode="Markdown")
        return

    key = args[0]
    val = " ".join(args[1:])
    tenant_cfg = get_tenant_config(user.id)

    if key == "allow_admin_member_cmds":
        GLOBAL_CONFIG.setdefault("settings", {})[key] = (val.lower() == "true")
    else:
        tenant_cfg[key] = val

    save_config(GLOBAL_CONFIG)
    await msg.reply_text(f"✅ Updated setting `{key}` = `{val}`!", parse_mode="Markdown")

async def view_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not await is_admin_or_owner(update, context):
        return

    tenant_cfg = get_tenant_config(user.id)
    conf_text = (
        f"📋 **YOUR VAULT CONFIGURATION AUDIT:**\n\n"
        f"📛 **Shop Name:** `{tenant_cfg.get('shop_name')}`\n"
        f"📍 **Main Hub ID:** `{tenant_cfg.get('main_hub_id')}`\n"
        f"📍 **Admin Proof Group ID:** `{tenant_cfg.get('admin_proof_group_id')}`\n"
        f"📍 **Proof Archive ID:** `{tenant_cfg.get('proof_archive_id')}`\n\n"
        f"💳 **Payments Configured:** {list(tenant_cfg.get('payments', {}).keys())}\n"
        f"👥 **Co-Owners:** `{tenant_cfg.get('co_owners', [])}`"
    )
    await msg.reply_text(conf_text, parse_mode="Markdown")

# ================= APPLICATION BUILDER & WEBHOOK LIFECYCLE =================

ACTIVE_BOT_TOKEN = GLOBAL_CONFIG.get("bot_token", "9118312201:AAFvZ6-cRZZCZqtbSz9dXTChxKYIKkTt9e8")
bot_app = ApplicationBuilder().token(ACTIVE_BOT_TOKEN).build()

# Core Onboarding & User Commands
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CommandHandler("help", member_help_command))
bot_app.add_handler(CommandHandler("admin", admin_panel))

# File & Jump Link Inspection Commands
bot_app.add_handler(CommandHandler("viewvault", view_vault_command))
bot_app.add_handler(CommandHandler("openlink", open_link_command))

# Bot Profile Setup Commands
bot_app.add_handler(CommandHandler("setbotname", set_bot_name_command))
bot_app.add_handler(CommandHandler("setbotusername", set_bot_username_command))

# Multi-Tenant Admin & Room Binding Commands
bot_app.add_handler(CommandHandler(["sethub", "unsethub", "delhub"], set_hub_command))
bot_app.add_handler(CommandHandler(["setadmin", "unsetadmin", "deladmin"], set_admin_group_command))
bot_app.add_handler(CommandHandler(["setproof", "unsetproof", "delproof"], set_proof_archive_command))
bot_app.add_handler(CommandHandler("addcoowner", add_coowner_command))

# Content & Moderation Management Commands
bot_app.add_handler(CommandHandler("promote", promote_command))
bot_app.add_handler(CommandHandler("groupmodule", group_module_command))
bot_app.add_handler(CommandHandler("renameitem", rename_item_command))
bot_app.add_handler(CommandHandler("delindex", del_index_command))
bot_app.add_handler(CommandHandler("addbadword", add_bad_word_command))

# Payments & Config Commands
bot_app.add_handler(CommandHandler("setmsg", set_msg_command))
bot_app.add_handler(CommandHandler("setpayment", set_payment_command))
bot_app.add_handler(CommandHandler("addpayment", add_payment_command))
bot_app.add_handler(CommandHandler("delpayment", del_payment_command))
bot_app.add_handler(CommandHandler("setconfig", set_config_command))
bot_app.add_handler(CommandHandler("config", view_config_command))

# Callback Query & Message Handlers
bot_app.add_handler(CallbackQueryHandler(handle_mode_switch, pattern="^mode_"))
bot_app.add_handler(CallbackQueryHandler(handle_vault_browser_callback, pattern="^(browsechat_|browsetit_|browse_)"))
bot_app.add_handler(CallbackQueryHandler(handle_del_index_callback, pattern="^delmod_"))
bot_app.add_handler(CallbackQueryHandler(handle_promotion_callback, pattern="^sendpromo_"))
bot_app.add_handler(CallbackQueryHandler(payment_option_selected, pattern="^(pay_|payusr_)"))
bot_app.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^(approve|reject)_"))
bot_app.add_handler(CallbackQueryHandler(handle_security_kick_decision, pattern="^seckick_"))

bot_app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo_receipt))
bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
bot_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_direct_link_paste))

bot_app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND & filters.ChatType.GROUPS, security_threat_detector), group=0)
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, group_moderation_guard), group=1)
bot_app.add_handler(MessageHandler(filters.ChatType.GROUPS | filters.ChatType.CHANNEL, auto_index_posts), group=2)

# Persistent Event Loop Manager for Webhook Processing
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

loop.run_until_complete(bot_app.initialize())
loop.run_until_complete(bot_app.start())

@app.route(f"/{ACTIVE_BOT_TOKEN}", methods=["POST"])
def webhook():
    json_data = request.get_json(force=True)
    update = Update.de_json(data=json_data, bot=bot_app.bot)
    loop.run_until_complete(bot_app.process_update(update))
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def health_check():
    return "Multi-Tenant Bot Server Active", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
