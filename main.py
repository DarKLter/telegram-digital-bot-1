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

# ================= CONFIGURATION =================

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "9118312201:AAFvZ6-cRZZCZqtbSz9dXTChxKYIKkTt9e8")

# Bot Owner User ID(s)
OWNER_IDS = [5331007152]

CONFIG_FILE = "bot_config.json"
STATE_FILE = "vault_state.json"

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask App Initialization for Gunicorn / Render.com
app = Flask(__name__)

# Default configuration structure
DEFAULT_CONFIG = {
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

def normalize_title(title: str) -> str:
    return title.strip().lower()

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id in OWNER_IDS:
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

# ================= HANDLERS & LOGIC =================

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
        "🛠️ **ADMIN CONTROL PANEL & COMMAND GUIDE**\n\n"
        "📢 **Broadcast Promotion:** `/promote <Message>`\n"
        "🗑️ **Remove Indexed Course:** `/delindex`\n"
        "🛡️ **Add Bad Word:** `/addbadword <word>`\n"
        "💬 **Edit Messages:** `/setmsg welcome|help|receipt <Text>`\n"
        "📍 **Room Setup:** `/sethub`, `/setadmin`, `/setproof`\n"
        "💳 **Payment Config:** `/setpayment gcash|maya|bank <Details>`\n"
        "🔍 **System Audit:** `/config`"
    )
    await update.message.reply_text(admin_help_text, parse_mode="Markdown")

async def security_threat_detector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    if not msg:
        return

    chat = msg.chat
    user = msg.from_user
    if not user or await is_admin_or_owner(update, context):
        return

    sec_config = BOT_CONFIG.get("security", DEFAULT_CONFIG["security"])
    text_content = (msg.text or msg.caption or "").lower()

    threat_found = False
    threat_reason = ""

    for keyword in sec_config.get("phishing_keywords", []):
        if keyword in text_content:
            threat_found = True
            threat_reason = f"Phishing Keyword (`{keyword}`)"
            break

    if not threat_found and msg.document:
        file_name = msg.document.file_name.lower() if msg.document.file_name else ""
        for ext in sec_config.get("suspicious_extensions", []):
            if file_name.endswith(ext):
                threat_found = True
                threat_reason = f"Suspicious File (`{file_name}`)"
                break

    if threat_found:
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Failed to delete threat message: {e}")

        keyboard = [
            [
                InlineKeyboardButton("🥾 Kick & Ban User", callback_data=f"seckick_KICK_{chat.id}_{user.id}"),
                InlineKeyboardButton("🛡️ Keep & Dismiss", callback_data=f"seckick_DISMISS_{chat.id}_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        alert_text = (
            f"🚨 **SECURITY ALERT: SUSPICIOUS ACTIVITY DETECTED**\n\n"
            f"👤 **Offender:** {user.full_name} (`{user.id}`)\n"
            f"💬 **Username:** @{user.username if user.username else 'N/A'}\n"
            f"📍 **Location:** {chat.title} (`{chat.id}`)\n"
            f"⚠️ **Threat:** {threat_reason}"
        )

        for owner_id in OWNER_IDS:
            try:
                await context.bot.send_message(chat_id=owner_id, text=alert_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send security alert: {e}")

async def handle_security_kick_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[1]
    chat_id = int(parts[2])
    user_id = int(parts[3])

    if action == "KICK":
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await query.edit_message_text(f"🥾 **User ID {user_id} banned from chat.**", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to kick user: {e}")
    elif action == "DISMISS":
        await query.edit_message_text("🛡️ Security alert dismissed.")

async def add_bad_word_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/addbadword <word>`")
        return

    word = " ".join(context.args).lower()
    mod_config = BOT_CONFIG.setdefault("moderation", DEFAULT_CONFIG["moderation"])
    if word not in mod_config["bad_words"]:
        mod_config["bad_words"].append(word)
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ Added `{word}` to blocklist!", parse_mode="Markdown")

async def group_moderation_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat = msg.chat
    if chat.type not in ["group", "supergroup"] or await is_admin_or_owner(update, context):
        return

    mod_config = BOT_CONFIG.get("moderation", DEFAULT_CONFIG["moderation"])
    if not mod_config.get("enabled", True):
        return

    text_lower = msg.text.lower()
    violation_reason = None

    for word in mod_config.get("bad_words", []):
        if word in text_lower:
            violation_reason = f"Prohibited word (`{word}`)"
            break

    if not violation_reason and mod_config.get("block_links", True):
        if "http://" in text_lower or "https://" in text_lower or "t.me/" in text_lower:
            whitelisted = mod_config.get("whitelisted_domains", [])
            if not any(domain in text_lower for domain in whitelisted):
                violation_reason = "Unauthorized link"

    if violation_reason:
        try:
            await msg.delete()
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🛡️ **Moderation:** Message from {msg.from_user.mention_markdown()} removed. ({violation_reason})",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Moderation failure: {e}")

async def del_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    if not VAULT_STATE:
        await update.message.reply_text("⚠️ No indexed courses found.")
        return

    keyboard = []
    for chat_id, data in VAULT_STATE.items():
        cat_name = data.get("category_name", f"Chat {chat_id}")
        courses = data.get("courses", {})
        for norm_key, c_info in courses.items():
            disp_title = c_info.get("display_title", norm_key)
            keyboard.append([InlineKeyboardButton(f"🗑️ Delete [{cat_name}] {disp_title}", callback_data=f"delmod_{chat_id}_{norm_key[:20]}")])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="delmod_CANCEL")])
    await update.message.reply_text("🗑️ **Index Removal Panel:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_del_index_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "delmod_CANCEL":
        await query.edit_message_text("❌ Operation cancelled.")
        return

    parts = query.data.split("_", 2)
    target_chat_id = int(parts[1])
    target_norm_key = parts[2]

    if target_chat_id in VAULT_STATE and "courses" in VAULT_STATE[target_chat_id]:
        for key in list(VAULT_STATE[target_chat_id]["courses"].keys()):
            if key.startswith(target_norm_key):
                del VAULT_STATE[target_chat_id]["courses"][key]
                break
        save_state(VAULT_STATE)
        await query.edit_message_text("✅ Module removed from index!")

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ **Usage:** `/promote <Message>`")
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

    keyboard.append([InlineKeyboardButton("🌐 Broadcast to ALL", callback_data="sendpromo_ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sendpromo_CANCEL")])

    await update.message.reply_text(f"📢 **Promotional Broadcast Preview:**\n{promo_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        await query.edit_message_text("❌ Broadcast cancelled.")
        return

    target_chats = []
    if target == "ALL":
        if BOT_CONFIG.get("main_hub_id"):
            target_chats.append(BOT_CONFIG["main_hub_id"])
        target_chats.extend(list(VAULT_STATE.keys()))
    else:
        target_chats.append(int(target))

    sent_count = 0
    for c_id in set(target_chats):
        try:
            await context.bot.send_message(chat_id=c_id, text=promo_text, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send promo to {c_id}: {e}")

    del PENDING_PROMOTIONS[user_id]
    await query.edit_message_text(f"🚀 Broadcast delivered to {sent_count} location(s)!")

async def set_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/setmsg welcome|help|receipt <Text>`")
        return

    msg_type = args[0].lower()
    custom_text = " ".join(args[1:])

    if msg_type in ["welcome", "help", "receipt"]:
        BOT_CONFIG["messages"][msg_type] = custom_text
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ Updated **{msg_type.upper()}** template!")

async def set_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/setpayment gcash|maya|bank <Number> | <Name>`")
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

    save_config(BOT_CONFIG)
    await update.message.reply_text(f"✅ Updated **{method_key.upper()}** payment info!")

async def set_hub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    BOT_CONFIG["main_hub_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Registered as **MAIN HUB DIRECTORY**!")

async def set_admin_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    BOT_CONFIG["admin_proof_group_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Registered as **ADMIN VERIFICATION GROUP**!")

async def set_proof_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    BOT_CONFIG["proof_archive_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Registered as **PROOF ARCHIVE**!")

async def view_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    conf_text = (
        f"📋 **Configuration Audit:**\n"
        f"Hub ID: `{BOT_CONFIG.get('main_hub_id')}`\n"
        f"Admin Proof Group ID: `{BOT_CONFIG.get('admin_proof_group_id')}`\n"
        f"Proof Archive ID: `{BOT_CONFIG.get('proof_archive_id')}`"
    )
    await update.message.reply_text(conf_text, parse_mode="Markdown")

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
            VAULT_STATE[chat_id]["courses"][norm_key] = {"display_title": raw_title, "file_count": 0}
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
            VAULT_STATE[chat_id]["courses"][active_key] = {"display_title": active_key.title(), "file_count": 0}

        VAULT_STATE[chat_id]["courses"][active_key]["file_count"] += 1
        file_num = VAULT_STATE[chat_id]["courses"][active_key]["file_count"]
        display_title = VAULT_STATE[chat_id]["courses"][active_key]["display_title"]

        save_state(VAULT_STATE)

        content_type_icon = "🎬" if post.video else "📚"
        item_label = f"Lesson {file_num}" if post.video else f"Ebook/Doc Part {file_num}"
        caption_title = extracted_text.split("\n")[0] if extracted_text else item_label

        direct_link = f"https://t.me/c/{clean_chat_id}/{thread_id}/{post.message_id}" if thread_id else f"https://t.me/c/{clean_chat_id}/{post.message_id}"
        forward_tag = " _(Forwarded Content)_" if post.forward_origin else ""

        lesson_entry = (
            f"📁 **Category:** {category_name}\n"
            f"📖 **Module:** {display_title}\n"
            f"{content_type_icon} **#{file_num}:** [{caption_title}]({direct_link}){forward_tag}\n\n"
            f"👉 _Click the link above to jump directly to this material!_"
        )

        await context.bot.send_message(chat_id=main_hub_id, text=lesson_entry, parse_mode="Markdown", disable_web_page_preview=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.full_name
    template = BOT_CONFIG["messages"].get("welcome", DEFAULT_CONFIG["messages"]["welcome"])
    welcome_text = template.replace("{name}", user_name)

    keyboard = [
        [InlineKeyboardButton("📱 Pay via GCash", callback_data="pay_gcash")],
        [InlineKeyboardButton("📱 Pay via Maya", callback_data="pay_maya")],
        [InlineKeyboardButton("🏦 Pay via MariBank / Card", callback_data="pay_bank")],
    ]
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

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CommandHandler("help", member_help_command))
bot_app.add_handler(CommandHandler("admin", admin_panel))
bot_app.add_handler(CommandHandler("promote", promote_command))
bot_app.add_handler(CommandHandler("delindex", del_index_command))
bot_app.add_handler(CommandHandler("addbadword", add_bad_word_command))
bot_app.add_handler(CommandHandler("setmsg", set_message_command))
bot_app.add_handler(CommandHandler("setpayment", set_payment_command))
bot_app.add_handler(CommandHandler("sethub", set_hub_command))
bot_app.add_handler(CommandHandler("setadmin", set_admin_group_command))
bot_app.add_handler(CommandHandler("setproof", set_proof_archive_command))
bot_app.add_handler(CommandHandler("config", view_config_command))

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

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
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
