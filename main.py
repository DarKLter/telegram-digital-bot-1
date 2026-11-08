import os
import json
import logging
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
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# Add your Telegram User ID here to grant global owner access
OWNER_IDS = [123456789]  # Replace with your actual numerical Telegram User ID

CONFIG_FILE = "bot_config.json"
STATE_FILE = "vault_state.json"

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Default configuration structure with customizable message templates
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

# Global Memory State
BOT_CONFIG = load_config()
VAULT_STATE = load_state()
PENDING_PROMOTIONS = {}

def normalize_title(title: str) -> str:
    return title.strip().lower()

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the command sender is a bot owner or channel/group admin."""
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

# ================= 1. MEMBER COMMANDS =================
async def member_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Public Help Command for Members."""
    user_name = update.effective_user.full_name
    template = BOT_CONFIG["messages"].get("help", DEFAULT_CONFIG["messages"]["help"])
    text = template.replace("{name}", user_name)
    await update.message.reply_text(text, parse_mode="Markdown")

# ================= 2. ADMIN CONTROL PANEL COMMANDS (SECURED FOR ADMINS/OWNERS ONLY) =================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Desk Command (/admin) - Secured for channel owners and administrators."""
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can use this command.")
        return

    admin_help_text = (
        "🛠️ **ADMIN CONTROL PANEL & COMMAND GUIDE**\n\n"
        "Welcome to the Management Desk. Authorized commands & usage examples:\n\n"
        "📢 **Targeted Promotional Broadcast:**\n"
        "• `/promote <Message>`\n"
        "  _Example:_ `/promote 🚀 Check out our Google Drive Courses: https://drive.google.com/...`\n\n"
        "💬 **Editable System Messages:**\n"
        "• `/setmsg welcome <Text>` - _Example:_ `/setmsg welcome Hello {name}! Welcome to Vault.`\n"
        "• `/setmsg help <Text>` - _Example:_ `/setmsg help Hi {name}! To buy: 1. Pay 2. Send receipt.`\n"
        "• `/setmsg receipt <Text>` - _Example:_ `/setmsg receipt Thanks {name}! Verifying now...`\n"
        "  _(Tip: Include `{name}` in message text to insert member's name!)_\n\n"
        "📍 **Room Setup Commands (Run inside target Channel/Group):**\n"
        "• `/sethub` - Register current chat as Main Directory Hub\n"
        "• `/setadmin` - Register current group as Admin Verification Group\n"
        "• `/setproof` - Register current chat as Public Proof Archive\n\n"
        "💳 **Payment Management Commands:**\n"
        "• `/setpayment gcash <Number> | <Name>` - _Example:_ `/setpayment gcash 09171234567 | Juan Cruz`\n"
        "• `/setpayment maya <Number> | <Name>` - _Example:_ `/setpayment maya 09189876543 | Maria Santos`\n"
        "• `/setpayment bank <Account No> | <Bank Name> | <Name>` - _Example:_ `/setpayment bank 12345 | MariBank | Juan`\n\n"
        "🔍 **System Audit Commands:**\n"
        "• `/config` - View active IDs, payment options, and custom messages"
    )
    await update.message.reply_text(admin_help_text, parse_mode="Markdown")

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to initiate targeted promotional messages."""
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can broadcast promotions.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ **Usage Example:**\n`/promote Check out our Google Drive Ebook Collection: https://drive.google.com/...`",
            parse_mode="Markdown"
        )
        return

    promo_text = " ".join(args)
    user_id = update.effective_user.id
    PENDING_PROMOTIONS[user_id] = promo_text

    keyboard = []
    # Build list of detected vault channels/groups + main hub
    available_chats = {}
    if BOT_CONFIG.get("main_hub_id"):
        available_chats[BOT_CONFIG["main_hub_id"]] = "Main Hub Directory"

    for chat_id, data in VAULT_STATE.items():
        available_chats[chat_id] = data.get("category_name", f"Chat {chat_id}")

    if not available_chats:
        await update.message.reply_text("⚠️ No active channels or groups detected yet.")
        return

    for c_id, c_name in available_chats.items():
        keyboard.append([InlineKeyboardButton(f"📤 Send to: {c_name}", callback_data=f"sendpromo_{c_id}")])

    keyboard.append([InlineKeyboardButton("🌐 Broadcast to ALL Groups & Channels", callback_data="sendpromo_ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sendpromo_CANCEL")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📢 **Targeted Promotion Manager**\n\n"
        "Select the target group or channel where you want to post this promotion:\n\n"
        f"📝 **Message Preview:**\n{promo_text}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_promotion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles channel selection for broadcasting promotions."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in PENDING_PROMOTIONS:
        await query.edit_message_text("⚠️ Promotion session expired. Please type `/promote` again.")
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
            logger.error(f"Failed to send promo to chat {c_id}: {e}")

    del PENDING_PROMOTIONS[user_id]
    await query.edit_message_text(f"🚀 **Promotion successfully posted to {sent_count} target location(s)!**", parse_mode="Markdown")

async def set_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or channel owners can change system messages.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage Examples:**\n"
            "• `/setmsg welcome Hello {name}, welcome to our store!`\n"
            "• `/setmsg help Hi {name}, follow these instructions to purchase...`\n"
            "• `/setmsg receipt Thanks {name}, receipt received!`\n"
            "\nValid message types: `welcome`, `help`, `receipt`",
            parse_mode="Markdown"
        )
        return

    msg_type = args[0].lower()
    custom_text = " ".join(args[1:])

    if msg_type in ["welcome", "help", "receipt"]:
        BOT_CONFIG["messages"][msg_type] = custom_text
        save_config(BOT_CONFIG)
        await update.message.reply_text(f"✅ Successfully updated **{msg_type.upper()}** message template!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Unknown message type! Choose between: `welcome`, `help`, or `receipt`.")

async def set_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can change payment settings.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage Examples:**\n"
            "• `/setpayment gcash 09170001111 | John Doe`\n"
            "• `/setpayment maya 09180002222 | Jane Doe`\n"
            "• `/setpayment bank 123456789 | MariBank | John Doe`",
            parse_mode="Markdown"
        )
        return

    method_key = args[0].lower()
    payload = " ".join(args[1:])
    parts = [p.strip() for p in payload.split("|")]

    if method_key == "gcash":
        number = parts[0]
        name = parts[1] if len(parts) > 1 else "N/A"
        BOT_CONFIG["payments"]["pay_gcash"] = f"📱 **GCash Payment**\nNumber: `{number}`\nAccount Name: {name}"
    elif method_key == "maya":
        number = parts[0]
        name = parts[1] if len(parts) > 1 else "N/A"
        BOT_CONFIG["payments"]["pay_maya"] = f"📱 **Maya Payment**\nNumber: `{number}`\nAccount Name: {name}"
    elif method_key in ["bank", "maribank"]:
        acc_num = parts[0]
        bank_name = parts[1] if len(parts) > 1 else "MariBank"
        name = parts[2] if len(parts) > 2 else "N/A"
        BOT_CONFIG["payments"]["pay_bank"] = f"🏦 **{bank_name} Payment**\nAccount Number: `{acc_num}`\nBank: {bank_name}\nAccount Name: {name}"
    else:
        await update.message.reply_text("❌ Unknown payment type! Use: `gcash`, `maya`, or `bank`.")
        return

    save_config(BOT_CONFIG)
    await update.message.reply_text(f"✅ Successfully updated **{method_key.upper()}** payment details!", parse_mode="Markdown")

async def set_hub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can configure system rooms.")
        return
    BOT_CONFIG["main_hub_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current chat registered as **MAIN HUB DIRECTORY**!", parse_mode="Markdown")

async def set_admin_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can configure system rooms.")
        return
    BOT_CONFIG["admin_proof_group_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current group registered as **ADMIN VERIFICATION GROUP**!", parse_mode="Markdown")

async def set_proof_archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Only administrators or owners can configure system rooms.")
        return
    BOT_CONFIG["proof_archive_id"] = update.effective_chat.id
    save_config(BOT_CONFIG)
    await update.message.reply_text("✅ Current chat registered as **PROOF ARCHIVE**!", parse_mode="Markdown")

async def view_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        await update.message.reply_text("⛔ **Access Denied:** Admin only.")
        return
    conf_text = (
        "📋 **Active Configuration Audit:**\n\n"
        f"📍 **Main Hub ID:** `{BOT_CONFIG.get('main_hub_id')}`\n"
        f"📍 **Admin Proof Group ID:** `{BOT_CONFIG.get('admin_proof_group_id')}`\n"
        f"📍 **Proof Archive ID:** `{BOT_CONFIG.get('proof_archive_id')}`\n\n"
        "💳 **Active Payment Profiles:**\n"
        f"{BOT_CONFIG['payments'].get('pay_gcash')}\n\n"
        f"{BOT_CONFIG['payments'].get('pay_maya')}\n\n"
        f"{BOT_CONFIG['payments'].get('pay_bank')}\n\n"
        "💬 **Active Message Templates:**\n"
        f"• **Welcome:** {BOT_CONFIG['messages'].get('welcome')}\n"
        f"• **Help:** {BOT_CONFIG['messages'].get('help')}\n"
        f"• **Receipt Ack:** {BOT_CONFIG['messages'].get('receipt')}"
    )
    await update.message.reply_text(conf_text, parse_mode="Markdown")

# ================= 3. AUTOMATED CONTENT INDEXER (SUPPORTS MULTI-TOPIC / GENERAL CHAT FORUMS) =================
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

    # Multi-Topic / General Chat Forum handling
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

    # 1. Title Post (Direct Upload OR Forwarded Text Title)
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

    # 2. Media Upload / Forwarded File (Video or Ebook/PDF)
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

        if post.video:
            content_type_icon = "🎬"
            item_label = f"Lesson {file_num}"
        else:
            content_type_icon = "📚"
            item_label = f"Ebook/Doc Part {file_num}"

        caption_title = extracted_text.split("\n")[0] if extracted_text else item_label

        # Multi-Topic link building logic
        if thread_id:
            direct_link = f"https://t.me/c/{clean_chat_id}/{thread_id}/{post.message_id}"
        else:
            direct_link = f"https://t.me/c/{clean_chat_id}/{post.message_id}"

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

# ================= 4. CUSTOMER PAYMENTS & PROOF MANAGEMENT =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.full_name
    template = BOT_CONFIG["messages"].get("welcome", DEFAULT_CONFIG["messages"]["welcome"])
    welcome_text = template.replace("{name}", user_name)

    keyboard = [
        [InlineKeyboardButton("📱 Pay via GCash", callback_data="pay_gcash")],
        [InlineKeyboardButton("📱 Pay via Maya", callback_data="pay_maya")],
        [InlineKeyboardButton("🏦 Pay via MariBank / Card", callback_data="pay_bank")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def payment_option_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method = query.data
    instructions = BOT_CONFIG["payments"].get(method, "Payment details not configured.")

    instructions_text = (
        f"{instructions}\n\n"
        "────────────────────────────────────────\n"
        "📸 **INSTRUCTIONS:**\n"
        "1. Complete your transfer using the details above.\n"
        "2. Send a **screenshot/photo of your receipt** directly as a response to this chat."
    )

    await query.edit_message_text(instructions_text, parse_mode="Markdown")

async def handle_photo_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file_id = update.message.photo[-1].file_id

    admin_group_id = BOT_CONFIG.get("admin_proof_group_id")
    if not admin_group_id:
        await update.message.reply_text("⚠️ Payment verification group is not configured yet. Please contact admin.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_photo(
        chat_id=admin_group_id,
        photo=photo_file_id,
        caption=(
            f"📥 **NEW PAYMENT PROOF RECEIVED**\n\n"
            f"👤 **Name:** {user.full_name}\n"
            f"💬 **Username:** @{user.username if user.username else 'N/A'}\n"
            f"🆔 **User ID:** `{user.id}`"
        ),
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

    template = BOT_CONFIG["messages"].get("receipt", DEFAULT_CONFIG["messages"]["receipt"])
    ack_text = template.replace("{name}", user.full_name)
    await update.message.reply_text(ack_text, parse_mode="Markdown")

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
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=main_hub_id, member_limit=1
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 **Payment Approved!**\n\n"
                    f"Welcome aboard! Click the link below to join the Main Hub Directory:\n"
                    f"{invite_link.invite_link}\n\n"
                    f"⚠️ _Note: This link can only be used once._"
                ),
            )
            
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\nSTATUS: ✅ **APPROVED BY ADMIN**",
                parse_mode="Markdown",
            )
            
            if proof_archive_id:
                await context.bot.forward_message(
                    chat_id=proof_archive_id,
                    from_chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                )
        except Exception as e:
            logger.error(f"Error approving user {user_id}: {e}")
            await query.message.reply_text(f"⚠️ Error approving user: {e}")

    elif action == "reject":
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ **Payment Verification Failed**\n\n"
                "We could not verify your receipt screenshot. Please ensure the reference number is visible and send a valid payment screenshot again."
            ),
        )
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\nSTATUS: ❌ **REJECTED BY ADMIN**",
            parse_mode="Markdown",
        )

# ================= 5. MAIN HANDLER REGISTRATION =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Member Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", member_help_command))

    # Secured Admin Command Handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("promote", promote_command))
    app.add_handler(CommandHandler("setmsg", set_message_command))
    app.add_handler(CommandHandler("setpayment", set_payment_command))
    app.add_handler(CommandHandler("sethub", set_hub_command))
    app.add_handler(CommandHandler("setadmin", set_admin_group_command))
    app.add_handler(CommandHandler("setproof", set_proof_archive_command))
    app.add_handler(CommandHandler("config", view_config_command))

    # Callback & Photo Handlers
    app.add_handler(CallbackQueryHandler(handle_promotion_callback, pattern="^sendpromo_"))
    app.add_handler(CallbackQueryHandler(payment_option_selected, pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo_receipt))
    
    # Universal Content Auto-Indexer (Supports Channels, Supergroups, & Forum Topics)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS | filters.ChatType.CHANNEL, auto_index_posts))

    logger.info("Bot running with targeted promotions & multi-topic support...")
    app.run_polling()

if __name__ == "__main__":
    main()