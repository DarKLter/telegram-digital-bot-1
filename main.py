import os
import json
import logging
import asyncio
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

async def member_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.full_name
    template = BOT_CONFIG["messages"].get("help", DEFAULT_CONFIG["messages"]["help"])
    text = template.replace("{name}", user_name)
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can use this command.")
        return

    admin_help_text = (
        "🛠️ **ADMIN & OWNER CONTROL PANEL**\n\n"
        "🤖 **Bot Profile Management:**\n"
        "• `/setbotname <Name>` - Change bot display name live\n"
        "• `/setbotusername` - View current handle & change guide\n\n"
        "🔑 **Owner Commands:**\n"
        "• `/settoken <TOKEN>` - Update Bot HTTP API Token\n"
        "• `/addowner <USER_ID>` - Add a new Bot Owner\n"
        "• `/removeowner <USER_ID>` - Remove a Bot Owner\n"
        "• `/setconfig <KEY> <VAL>` - Edit dynamic config value\n\n"
        "📢 **Broadcast Promotion:** `/promote <Message>`\n"
        "🗑️ **Remove Indexed Course:** `/delindex`\n"
        "📦 **Group Modules:** `/groupmodule <Category> <Title> | <Items>`\n"
        "✏️ **Rename Course Item:** `/renameitem <Category> <Old> | <New>`\n"
        "💳 **Manage Payment Options:** `/addpayment`, `/delpayment`, `/setpayment`\n"
        "🛡️ **Add Bad Word:** `/addbadword <word>`\n"
        "💬 **Edit Messages:** `/setmsg welcome|help|receipt <Text>`\n"
        "📍 **Room Setup:** `/sethub`, `/setadmin`, `/setproof`\n"
        "🔍 **System Audit:** `/config`"
    )
    await update.message.reply_text(admin_help_text, parse_mode="Markdown")

# ================= CONFIGURATION =================

CONFIG_FILE = "bot_config.json"
STATE_FILE = "vault_state.json"

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Default configuration structure
DEFAULT_CONFIG = {
    "bot_token": os.getenv("TELEGRAM_TOKEN", "9118312201:AAFvZ6-cRZZCZqtbSz9dXTChxKYIKkTt9e8"),
    "owner_ids": [5331007152],
    "main_hub_id": 0,
    "admin_proof_group_id": 0,
    "proof_archive_id": 0,
    "payments": {
        "pay_gcash": "📱 **GCash Payment**\nNumber: `09171234567`\nAccount Name: Admin",
        "pay_maya": "📱 **Maya Payment**\nNumber: `09171234567`\nAccount Name: Admin",
        "pay_bank": "🏦 **MariBank / Bank Transfer**\nAccount Number: `1234-5678-9012`\nBank: MariBank\nAccount Name: Admin",
    },
    "messages": {
        "welcome": "👋 **Welcome to Digital Vault Academy, {name}!**\n\nGet access to our complete library of Game Development, Video Editing, and Ebooks.\n\nPlease select your preferred payment method below:",
        "help": "📖 **MEMBER HELP & INSTRUCTIONS**\n\nWelcome {name}! Here is how to purchase access:\n\n1️⃣ **Start Checkout:** Type `/start` and select your payment method (GCash, Maya, MariBank).\n2️⃣ **Make Transfer:** Pay the exact amount using the payment details shown.\n3️⃣ **Send Receipt:** Take a screenshot of your successful transaction and send the photo directly to this chat.\n4️⃣ **Instant Access:** Once an admin approves your receipt, the bot will automatically send you a private single-use invite link to the course hub!",
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

# ================= PERSISTENT STORAGE HELPERS =================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if "messages" not in config:
                    config["messages"] = DEFAULT_CONFIG["messages"]
                if "moderation" not in config:
                    config["moderation"] = DEFAULT_CONFIG["moderation"]
                if "security" not in config:
                    config["security"] = DEFAULT_CONFIG["security"]
                if "owner_ids" not in config:
                    config["owner_ids"] = DEFAULT_CONFIG["owner_ids"]
                if "bot_token" not in config:
                    config["bot_token"] = DEFAULT_CONFIG["bot_token"]
                return config
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
    return DEFAULT_CONFIG

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

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving state file: {e}")

BOT_CONFIG = load_config()
VAULT_STATE = load_state()
PENDING_PROMOTIONS = {}

# Flask App Initialization for Gunicorn / Render.com
app = Flask(__name__)

def normalize_title(title: str) -> str:
    return title.strip().lower()

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id in BOT_CONFIG.get("owner_ids", [5331007152]):
        return True

    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup", "channel"]:
        try:
            member = await context.bot.get_chat_member(chat.id, user_id)
            if member.status in ["administrator", "creator"]:
                return True
        except Exception as e:
            logger.error(f"Error checking chat permissions: {e}")
            
    return False

# ================= ADVANCE BOT PROFILE MANAGEMENT COMMANDS =================

async def set_bot_name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or bot owners can change the bot name.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/setbotname <NEW_BOT_NAME>`\n_Example:_ `/setbotname Digital Vault Pro`", parse_mode="Markdown")
        return

    new_name = " ".join(context.args).strip()
    try:
        await context.bot.set_my_name(name=new_name)
        await update.message.reply_text(
            f"✅ **SUCCESS!** Bot display name updated to:\n\n"
            f"📛 **New Bot Name:** `{new_name}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to set bot name: {e}")
        await update.message.reply_text(f"❌ **Error changing bot name:** {e}")

async def set_bot_username_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or bot owners can manage username settings.")
        return

    bot_info = await context.bot.get_me()
    guide_text = (
        f"🤖 **CURRENT BOT PROFILE DETAILS**\n\n"
        f"📛 **Display Name:** `{bot_info.first_name}`\n"
        f"👤 **Current Username:** @{bot_info.username}\n"
        f"🆔 **Bot User ID:** `{bot_info.id}`\n\n"
        "────────────────────────────────────────\n"
        "ℹ️ **HOW TO CHANGE BOT USERNAME (@handle):**\n"
        "1. Open Telegram and search for `@BotFather`.\n"
        "2. Send `/setusername` to `@BotFather`.\n"
        "3. Select this bot from your list.\n"
        "4. Type your new desired username ending in `bot` (e.g., `NewVaultName_bot`).\n\n"
        "💡 _To change the display name instantly from this chat, use `/setbotname <Name>`!_"
    )
    await update.message.reply_text(guide_text, parse_mode="Markdown")

# ================= DYNAMIC CONFIG & MANAGEMENT COMMANDS =================

async def set_token_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only owners can change the bot API token.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/settoken <NEW_BOT_TOKEN>`", parse_mode="Markdown")
        return

    new_token = context.args[0].strip()
    BOT_CONFIG["bot_token"] = new_token
    save_config(BOT_CONFIG)
    
    await update.message.reply_text(
        f"✅ **SUCCESS!** Bot API Token updated successfully!\n\n"
        f"🔑 **New Token:** `{new_token[:10]}...`\n"
        f"⚠️ _Note: Please restart the bot server on Render to apply the new token active connection._",
        parse_mode="Markdown"
    )

async def add_owner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only owners can add new bot owners.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/addowner <USER_ID>`", parse_mode="Markdown")
        return

    try:
        new_owner_id = int(context.args[0])
        owners = BOT_CONFIG.setdefault("owner_ids", [])
        if new_owner_id not in owners:
            owners.append(new_owner_id)
            save_config(BOT_CONFIG)
            await update.message.reply_text(f"✅ **SUCCESS!** Added User ID `{new_owner_id}` to Owner List!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ User ID `{new_owner_id}` is already an owner.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID. Must be numerical.")

async def remove_owner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only owners can remove bot owners.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/removeowner <USER_ID>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
        owners = BOT_CONFIG.get("owner_ids", [])
        if target_id in owners:
            owners.remove(target_id)
            save_config(BOT_CONFIG)
            await update.message.reply_text(f"✅ **SUCCESS!** Removed User ID `{target_id}` from Owner List!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ User ID `{target_id}` is not in owner list.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID. Must be numerical.")

async def set_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Owner only.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/setconfig <KEY> <VALUE>`\n_Example:_ `/setconfig main_hub_id -1001234567`", parse_mode="Markdown")
        return

    key = context.args[0]
    val = " ".join(context.args[1:])

    if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
        val = int(val)

    BOT_CONFIG[key] = val
    save_config(BOT_CONFIG)
    await update.message.reply_text(f"✅ **SUCCESS!** Updated config `{key}` = `{val}`!", parse_mode="Markdown")

# ================= SECURITY & HACK THREAT DETECTOR =================

async def security_threat_detector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat = msg.chat
    if chat.type not in ["group", "supergroup"]:
        return

    user = msg.from_user
    if user.id in BOT_CONFIG.get("owner_ids", []):
        return

    text_content = (msg.text or msg.caption or "").lower()
    sec_cfg = BOT_CONFIG.get("security", DEFAULT_CONFIG["security"])
    
    threat_detected = False
    violation_reason = ""

    for keyword in sec_cfg["phishing_keywords"]:
        if keyword in text_content:
            threat_detected = True
            violation_reason = f"Credential / Phishing keyword detected: `{keyword}`"
            break

    if msg.document:
        doc_name = msg.document.file_name.lower()
        for ext in sec_cfg["suspicious_extensions"]:
            if doc_name.endswith(ext):
                threat_detected = True
                violation_reason = f"Suspicious malicious file attachment detected: `{ext}`"
                break

    if threat_detected:
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Failed to delete malicious message: {e}")

        owner_ids = BOT_CONFIG.get("owner_ids", [5331007152])
        keyboard = [
            [
                InlineKeyboardButton("🥾 Kick & Ban User", callback_data=f"seckick_ban_{user.id}_{chat.id}"),
                InlineKeyboardButton("🛡️ Keep & Dismiss", callback_data=f"seckick_keep_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        alert_text = (
            f"🚨 **SECURITY ALERT: POTENTIAL HACK/THEFT DETECTED!** 🚨\n\n"
            f"👤 **User:** {user.full_name} (`{user.id}`)\n"
            f"💬 **Group:** {chat.title} (`{chat.id}`)\n"
            f"⚠️ **Reason:** {violation_reason}\n\n"
            f"👉 **Action Taken:** Message was automatically deleted.\n"
            f"Would you like to ban this user from the chat?"
        )

        for owner_id in owner_ids:
            try:
                await context.bot.send_message(chat_id=owner_id, text=alert_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to notify owner {owner_id}: {e}")

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
            await query.edit_message_text(
                text=f"{query.message.text}\n\nSTATUS: ✅ **USER BANNED & KICKED BY OWNER**",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to ban user {user_id}: {e}")
            await query.edit_message_text(text=f"{query.message.text}\n\nSTATUS: ❌ **Failed to ban user:** {e}")
    else:
        await query.edit_message_text(
            text=f"{query.message.text}\n\nSTATUS: 🛡️ **ALERT DISMISSED (User Kept)**",
            parse_mode="Markdown"
        )

# ================= GROUP MODERATION GUARD =================

async def group_moderation_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat = msg.chat
    if chat.type not in ["group", "supergroup"]:
        return

    if await is_admin_or_owner(update, context):
        return

    text = (msg.text or msg.caption or "").lower()
    mod_cfg = BOT_CONFIG.get("moderation", DEFAULT_CONFIG["moderation"])

    if not mod_cfg.get("enabled", True):
        return

    for word in mod_cfg.get("bad_words", []):
        if word in text:
            try:
                await msg.delete()
                warning = await chat.send_message(
                    f"⚠️ {msg.from_user.mention_html()}, your message was removed for violating group moderation rules.",
                    parse_mode="HTML"
                )
                await asyncio.sleep(5)
                await warning.delete()
            except Exception as e:
                logger.error(f"Moderation deletion error: {e}")
            return

    if mod_cfg.get("block_links", True) and ("http://" in text or "https://www.google.com" in text or "t.me/" not in text):
        allowed = False
        for domain in mod_cfg.get("whitelisted_domains", []):
            if domain in text:
                allowed = True
                break
        if not allowed and ("http://" in text or "https://" in text):
            try:
                await msg.delete()
                warning = await chat.send_message(
                    f"⚠️ {msg.from_user.mention_html()}, external links are restricted in this group.",
                    parse_mode="HTML"
                )
                await asyncio.sleep(5)
                await warning.delete()
            except Exception as e:
                logger.error(f"Link moderation error: {e}")
            return

async def add_bad_word_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/addbadword <word>`")
        return
    word = context.args[0].lower()
    bad_words = BOT_CONFIG["moderation"].setdefault("bad_words", [])
    if word not in bad_words:
        bad_words.append(word)
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ **Success!** Added `{word}` to the moderation blocklist!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ Word `{word}` is already in the blocklist.")

# ================= AUTOMATED CONTENT INDEXER =================

async def auto_index_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.message
    if not post:
        return

    chat_id = post.chat_id
    main_hub_id = BOT_CONFIG.get("main_hub_id")

    if not main_hub_id or chat_id in [main_hub_id, BOT_CONFIG.get("admin_proof_group_id"), BOT_CONFIG.get("proof_archive_id")]:
        return

    category_name = post.chat.title if post.chat.title else "Vault Content"
    clean_chat_id = str(chat_id).replace("-100", "")
    thread_id = getattr(post, "message_thread_id", None)

    if chat_id not in VAULT_STATE:
        VAULT_STATE[chat_id] = {
            "category_name": category_name,
            "active_course": "General Library",
            "courses": {}
        }
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
            VAULT_STATE[chat_id]["courses"][norm_key] = {
                "display_title": raw_title,
                "file_count": 0
            }
            status_msg = f"📌 **NEW MODULE ADDED TO {category_name.upper()}**\n\n📖 **Title:** `{raw_title}`"
        else:
            current_count = VAULT_STATE[chat_id]["courses"][norm_key]["file_count"]
            status_msg = f"🔄 **RE-OPENED MODULE IN {category_name.upper()}**\n\n📖 **Title:** `{raw_title}`\n📊 **Current Total Files:** {current_count}"

        save_state(VAULT_STATE)

        await context.bot.send_message(
            chat_id=main_hub_id,
            text=f"{status_msg}\n────────────────────────────────────────",
            parse_mode="Markdown"
        )
        return

    if post.video or post.document:
        active_key = VAULT_STATE[chat_id].get("active_course", "General Library")

        if active_key not in VAULT_STATE[chat_id]["courses"]:
            VAULT_STATE[chat_id]["courses"][active_key] = {
                "display_title": active_key.title(),
                "file_count": 0
            }

        VAULT_STATE[chat_id]["courses"][active_key]["file_count"] += 1
        file_num = VAULT_STATE[chat_id]["courses"][active_key]["file_count"]
        display_title = VAULT_STATE[chat_id]["courses"][active_key]["display_title"]

        save_state(VAULT_STATE)

        content_type_icon = "🎬" if post.video else "📚"
        item_label = f"Lesson {file_num}" if post.video else f"Ebook Part {file_num}"
        caption_title = extracted_text.split("\n")[0] if extracted_text else item_label

        direct_link = f"https://t.me/c/{clean_chat_id}/{thread_id}/{post.message_id}" if thread_id else f"https://t.me/c/{clean_chat_id}/{post.message_id}"
        forward_tag = " _(Forwarded Content)_" if post.forward_origin else ""

        lesson_entry = (
            f"📁 **Category:** {category_name}\n"
            f"📖 **Module:** {display_title}\n"
            f"{content_type_icon} **#{file_num}:** [{caption_title}]({direct_link}){forward_tag}\n\n"
            f"👉 _Click the link above to jump directly to this material!_"
        )

        await context.bot.send_message(
            chat_id=main_hub_id,
            text=lesson_entry,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

async def del_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    if not VAULT_STATE:
        await update.message.reply_text("ℹ️ No indexed courses found in state records.")
        return

    keyboard = []
    for chat_id, data in VAULT_STATE.items():
        cat_name = data.get("category_name", f"Chat {chat_id}")
        for course_key, info in data.get("courses", {}).items():
            title = info.get("display_title", course_key)
            keyboard.append([InlineKeyboardButton(f"🗑️ Delete: [{cat_name}] {title}", callback_data=f"delmod_{chat_id}_{course_key}")])

    await update.message.reply_text(
        "🗑️ **INDEXED MODULE REMOVAL DESK**\n\nSelect a course module below to remove from active index records:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_del_index_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)
    chat_id = int(parts[1])
    course_key = parts[2]

    if chat_id in VAULT_STATE and course_key in VAULT_STATE[chat_id]["courses"]:
        removed_title = VAULT_STATE[chat_id]["courses"][course_key].get("display_title")
        del VAULT_STATE[chat_id]["courses"][course_key]
        save_state(VAULT_STATE)
        await query.edit_message_text(f"✅ **Success!** Removed module `{removed_title}` from index records.", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Module not found or already deleted.")

# ================= PROMOTION & MANAGEMENT COMMANDS =================

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ **Usage:** `/promote <Message>`", parse_mode="Markdown")
        return

    promo_text = " ".join(args)
    user_id = update.effective_user.id
    PENDING_PROMOTIONS[user_id] = promo_text

    keyboard = []
    available_chats = {}
    if BOT_CONFIG.get("main_hub_id"):
        available_chats[BOT_CONFIG["main_hub_id"]] = "Main Hub Directory"

    for chat_id, data in VAULT_STATE.items():
        available_chats[chat_id] = data.get("category_name", f"Chat {chat_id}")

    for c_id, c_name in available_chats.items():
        keyboard.append([InlineKeyboardButton(f"📤 Send to: {c_name}", callback_data=f"sendpromo_{c_id}")])

    keyboard.append([InlineKeyboardButton("🌐 Broadcast to ALL Groups & Channels", callback_data="sendpromo_ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sendpromo_CANCEL")])

    await update.message.reply_text(
        "📢 **Targeted Promotion Manager**\n\nSelect target location:\n\n" f"📝 **Preview:**\n{promo_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_promotion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in PENDING_PROMOTIONS:
        await query.edit_message_text("⚠️ Promotion session expired.")
        return

    target = query.data.replace("sendpromo_", "")
    promo_text = PENDING_PROMOTIONS[user_id]

    if target == "CANCEL":
        del PENDING_PROMOTIONS[user_id]
        await query.edit_message_text("❌ Promotion cancelled.")
        return

    sent_count = 0
    target_chats = []
    if target == "ALL":
        if BOT_CONFIG.get("main_hub_id"):
            target_chats.append(BOT_CONFIG["main_hub_id"])
        target_chats.extend(list(VAULT_STATE.keys()))
    else:
        target_chats.append(int(target))

    for c_id in set(target_chats):
        try:
            await context.bot.send_message(chat_id=c_id, text=promo_text, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to post promotion to {c_id}: {e}")

    del PENDING_PROMOTIONS[user_id]
    await query.edit_message_text(f"🚀 **Promotion successfully posted to {sent_count} location(s)!**", parse_mode="Markdown")

async def set_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/setmsg welcome|help|receipt <Text>`", parse_mode="Markdown")
        return

    msg_type = args[0].lower()
    custom_text = " ".join(args[1:])

    if msg_type in ["welcome", "help", "receipt"]:
        BOT_CONFIG["messages"][msg_type] = custom_text
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ Successfully updated **{msg_type.upper()}** message template!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Unknown type! Choose: `welcome`, `help`, `receipt`.")

async def set_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/setpayment gcash <Number> | <Name>`", parse_mode="Markdown")
        return

    method_key = args[0].lower()
    payload = " ".join(args[1:])
    parts = [p.strip() for p in payload.split("|")]

    if method_key == "gcash":
        BOT_CONFIG["payments"]["pay_gcash"] = f"📱 **GCash Payment**\nNumber: `{parts[0]}`\nAccount Name: {parts[1] if len(parts) > 1 else 'N/A'}"
    elif method_key == "maya":
        BOT_CONFIG["payments"]["pay_maya"] = f"📱 **Maya Payment**\nNumber: `{parts[0]}`\nAccount Name: {parts[1] if len(parts) > 1 else 'N/A'}"
    elif method_key in ["bank", "maribank"]:
        BOT_CONFIG["payments"]["pay_bank"] = f"🏦 **{parts[1] if len(parts) > 1 else 'Bank'} Payment**\nAccount Number: `{parts[0]}`\nAccount Name: {parts[2] if len(parts) > 2 else 'N/A'}"
    else:
        await update.message.reply_text("❌ Unknown payment type.")
        return

    save_config(BOT_CONFIG)
    await update.message.reply_text(f"✅ Successfully updated **{method_key.upper()}** payment details!", parse_mode="Markdown")

async def set_hub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    BOT_CONFIG["main_hub_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current chat registered as **MAIN HUB DIRECTORY**!", parse_mode="Markdown")

async def set_admin_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    BOT_CONFIG["admin_proof_group_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current group registered as **ADMIN VERIFICATION GROUP**!", parse_mode="Markdown")

async def set_proof_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    BOT_CONFIG["proof_archive_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current chat registered as **PROOF ARCHIVE**!", parse_mode="Markdown")

async def view_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    conf_text = (
        f"📋 **Configuration Audit:**\n\n"
        f"🔑 **Owner IDs:** `{BOT_CONFIG.get('owner_ids')}`\n"
        f"📍 **Main Hub ID:** `{BOT_CONFIG.get('main_hub_id')}`\n"
        f"📍 **Admin Proof Group ID:** `{BOT_CONFIG.get('admin_proof_group_id')}`\n"
        f"📍 **Proof Archive ID:** `{BOT_CONFIG.get('proof_archive_id')}`\n\n"
        f"💳 **Payments Active:** {list(BOT_CONFIG.get('payments', {}).keys())}"
    )
    await update.message.reply_text(conf_text, parse_mode="Markdown")

# ================= DYNAMIC PAYMENTS, GROUPING, RENAMING COMMANDS =================

async def add_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage:** `/addpayment <key> <Button Label> | <Instructions>`\n"
            "_Example:_ `/addpayment crypto USDT (TRC20) | Address: TXYZ... | Name: Vault`",
            parse_mode="Markdown"
        )
        return

    pay_key = f"pay_{args[0].lower()}"
    payload = " ".join(args[1:])
    parts = [p.strip() for p in payload.split("|")]
    
    label = parts[0]
    instructions = " | ".join(parts[1:]) if len(parts) > 1 else label

    payments = BOT_CONFIG.setdefault("payments", {})
    payments[pay_key] = f"💰 **{label}**\n{instructions}"
    save_config(BOT_CONFIG)

    await update.message.reply_text(f"✅ **Success!** Added payment method `{pay_key}` (`{label}`). It now appears in `/start`!", parse_mode="Markdown")

async def del_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ **Usage:** `/delpayment <key>` (e.g., `/delpayment crypto`)")
        return

    pay_key = f"pay_{args[0].lower()}"
    payments = BOT_CONFIG.get("payments", {})
    if pay_key in payments:
        del payments[pay_key]
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ **Success!** Removed payment option `{pay_key}`.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Payment key `{pay_key}` not found.")

async def group_module_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ **Usage:** `/groupmodule <Category> <Master Title> | <Item1, Item2>`\n"
            "_Example:_ `/groupmodule Game Development Master Bundle | Lesson 1, Lesson 2`",
            parse_mode="Markdown"
        )
        return

    payload = " ".join(context.args)
    if "|" not in payload:
        await update.message.reply_text("❌ Please use `|` to separate the master title from items.")
        return

    left_part, right_part = payload.split("|", 1)
    tokens = left_part.strip().rsplit(" ", 1)
    category_name = tokens[0]
    master_title = tokens[1] if len(tokens) > 1 else "Master Bundle"
    items_to_group = [i.strip() for i in right_part.split(",")]

    main_hub_id = BOT_CONFIG.get("main_hub_id")
    if not main_hub_id:
        await update.message.reply_text("⚠️ Main Hub ID not configured.")
        return

    bundle_text = (
        f"📦 **MASTER BUNDLE GROUP**\n"
        f"📁 **Category:** {category_name}\n"
        f"🌟 **Title:** `{master_title}`\n\n"
        f"🔗 **Included Modules / Lessons:**\n"
    )
    for idx, item in enumerate(items_to_group, 1):
        bundle_text += f"• Part {idx}: {item}\n"

    bundle_text += "\n👉 _All selected items bundled successfully into one master link!_"

    await context.bot.send_message(chat_id=main_hub_id, text=bundle_text, parse_mode="Markdown")
    await update.message.reply_text(f"✅ **Success!** Master bundle `{master_title}` created and posted to Main Hub.")

async def rename_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    payload = " ".join(context.args)
    if "|" not in payload:
        await update.message.reply_text(
            "⚠️ **Usage:** `/renameitem <Category> <Old Title> | <New Title>`\n"
            "_Example:_ `/renameitem Game Dev Intro to Unity | Advanced Unity 2026`",
            parse_mode="Markdown"
        )
        return

    left_part, new_title = [p.strip() for p in payload.split("|", 1)]
    tokens = left_part.rsplit(" ", 1)
    category_name = tokens[0]
    old_title = tokens[1] if len(tokens) > 1 else ""

    renamed_count = 0
    for chat_id, data in VAULT_STATE.items():
        cat_title = data.get("category_name", "")
        if category_name.lower() in cat_title.lower():
            courses = data.get("courses", {})
            for k, c_info in list(courses.items()):
                if old_title.lower() in c_info.get("display_title", "").lower():
                    c_info["display_title"] = new_title
                    renamed_count += 1

    save_state(VAULT_STATE)
    await update.message.reply_text(f"✅ **Success!** Renamed {renamed_count} indexed entries to `{new_title}`.", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.full_name
    template = BOT_CONFIG["messages"].get("welcome", DEFAULT_CONFIG["messages"]["welcome"])
    welcome_text = template.replace("{name}", user_name)

    keyboard = []
    payments = BOT_CONFIG.get("payments", DEFAULT_CONFIG["payments"])
    for key, val in payments.items():
        title_line = val.split("\n")[0].replace("*", "").replace("📱", "").replace("🏦", "").replace("💰", "").strip()
        keyboard.append([InlineKeyboardButton(title_line, callback_data=key)])

    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def payment_option_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method = query.data
    instructions = BOT_CONFIG["payments"].get(method, "Payment details not configured.")
    instructions_text = f"{instructions}\n\n📸 **INSTRUCTIONS:** Send your receipt screenshot here."
    await query.edit_message_text(instructions_text, parse_mode="Markdown")

async def handle_photo_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file_id = update.message.photo[-1].file_id
    admin_group_id = BOT_CONFIG.get("admin_proof_group_id")

    if not admin_group_id:
        await update.message.reply_text("⚠️ Payment group unconfigured.")
        return

    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")]
    ]
    await context.bot.send_photo(
        chat_id=admin_group_id,
        photo=photo_file_id,
        caption=f"📥 **NEW RECEIPT:** {user.full_name} (`{user.id}`)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

    template = BOT_CONFIG["messages"].get("receipt", DEFAULT_CONFIG["messages"]["receipt"])
    await update.message.reply_text(template.replace("{name}", user.full_name), parse_mode="Markdown")

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[0]
    user_id = int(data[1])

    main_hub_id = BOT_CONFIG.get("main_hub_id")
    proof_archive_id = BOT_CONFIG.get("proof_archive_id")

    if action == "approve":
        try:
            invite_link = await context.bot.create_chat_invite_link(chat_id=main_hub_id, member_limit=1)
            await context.bot.send_message(chat_id=user_id, text=f"🎉 **Approved! Join:** {invite_link.invite_link}")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\nSTATUS: ✅ **APPROVED**")

            if proof_archive_id:
                await context.bot.forward_message(chat_id=proof_archive_id, from_chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception as e:
            logger.error(f"Approval error: {e}")
    elif action == "reject":
        await context.bot.send_message(chat_id=user_id, text="❌ **Verification failed.** Send a clear receipt.")
        await query.edit_message_caption(caption=f"{query.message.caption}\n\nSTATUS: ❌ **REJECTED**")

# ================= APPLICATION BUILDER & ASYNC LIFECYCLE MANAGEMENT =================

ACTIVE_BOT_TOKEN = BOT_CONFIG.get("bot_token", "9118312201:AAFvZ6-cRZZCZqtbSz9dXTChxKYIKkTt9e8")
bot_app = ApplicationBuilder().token(ACTIVE_BOT_TOKEN).build()

# Core User Commands
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text(BOT_CONFIG["messages"]["help"].replace("{name}", u.effective_user.full_name), parse_mode="Markdown")))
bot_app.add_handler(CommandHandler("admin", lambda u, c: u.message.reply_text("🛠️ **Admin Desk Active**\nUse `/promote`, `/setmsg`, `/setpayment`, `/sethub`, `/setadmin`, `/setproof`, `/config`, `/addpayment`, `/delpayment`, `/groupmodule`, `/renameitem`, `/delindex`, `/addbadword`, `/settoken`, `/addowner`, `/removeowner`, `/setconfig`, `/setbotname`, `/setbotusername`", parse_mode="Markdown")))

# Advance Bot Profile Management Commands
bot_app.add_handler(CommandHandler("setbotname", set_bot_name_command))
bot_app.add_handler(CommandHandler("setbotusername", set_bot_username_command))

# Dynamic Owner Configuration Commands
bot_app.add_handler(CommandHandler("settoken", set_token_command))
bot_app.add_handler(CommandHandler("addowner", add_owner_command))
bot_app.add_handler(CommandHandler("removeowner", remove_owner_command))
bot_app.add_handler(CommandHandler("setconfig", set_config_command))

# Admin Control Panel Commands
bot_app.add_handler(CommandHandler("promote", promote_command))
bot_app.add_handler(CommandHandler("delindex", del_index_command))
bot_app.add_handler(CommandHandler("addbadword", add_bad_word_command))
bot_app.add_handler(CommandHandler("addpayment", add_payment_command))
bot_app.add_handler(CommandHandler("delpayment", del_payment_command))
bot_app.add_handler(CommandHandler("groupmodule", group_module_command))
bot_app.add_handler(CommandHandler("renameitem", rename_item_command))
bot_app.add_handler(CommandHandler("setmsg", set_message_command))
bot_app.add_handler(CommandHandler("setpayment", set_payment_command))
bot_app.add_handler(CommandHandler("sethub", set_hub_command))
bot_app.add_handler(CommandHandler("setadmin", set_admin_group_command))
bot_app.add_handler(CommandHandler("setproof", set_proof_archive_command))
bot_app.add_handler(CommandHandler("config", view_config_command))

# Callbacks & Message Filters
bot_app.add_handler(CallbackQueryHandler(handle_security_kick_decision, pattern="^seckick_"))
bot_app.add_handler(CallbackQueryHandler(handle_del_index_callback, pattern="^delmod_"))
bot_app.add_handler(CallbackQueryHandler(handle_promotion_callback, pattern="^sendpromo_"))
bot_app.add_handler(CallbackQueryHandler(payment_option_selected, pattern="^pay_"))
bot_app.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^(approve|reject)_"))
bot_app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo_receipt))
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
    return "Bot Server Online", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
