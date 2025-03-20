import asyncio
import logging
import os
import random
import re
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import telegram.error
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID = 7563434309  
ALLOWED_USERS = {OWNER_ID, 123456789, 987654321}  

GROUPS_FILE = "groups.txt"
ABUSE_FILE = "abuse.txt"

USER_WARNINGS = {}
AUTHORIZED_USERS = {}

WARNING_MESSAGES = {
    1: "⚠️ {user}, please keep it respectful!",
    2: "⛔ {user}, second warning! Watch your words.",
    3: "🚦 {user}, you're on thin ice! Final warning.",
    4: "🛑 {user}, stop now, or you will be muted!",
    5: "🚷 {user}, last chance before removal!",
    6: "🔨 {user}, you've been muted for repeated violations!",
    7: "🚫 {user}, you’ve crossed the line. Consider this a final notice!",
    8: "☢️ {user}, next time, you're banned!",
    9: "⚰️ {user}, you're getting removed now!",
    10: "🔥 {user}, you are banned from this group!"
}

def load_abusive_words():
    if os.path.exists(ABUSE_FILE):
        try:
            with open(ABUSE_FILE, "r", encoding="utf-8") as f:
                return set(word.strip().lower() for word in f.readlines() if word.strip())
        except Exception as e:
            logger.error(f"Failed to load abusive words: {e}")
            return set()
    return set()

ABUSIVE_WORDS = load_abusive_words()

def load_groups():
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                return {int(line.strip()) for line in f.readlines() if line.strip().isdigit()}
        except Exception as e:
            logger.error(f"Failed to load group IDs: {e}")
            return set()
    return set()

def save_groups(groups):
    try:
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            for group_id in groups:
                f.write(str(group_id) + "\n")
    except Exception as e:
        logger.error(f"Failed to save group IDs: {e}")

GROUP_IDS = load_groups()

async def is_admin(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except telegram.error.BadRequest:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("📢 Support", url="https://t.me/Gaming_World_Update")],
        [InlineKeyboardButton("🔄 Updates", url="https://t.me/Gaming_World_Update")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    start_message = (
        "🚨 **Anti-Abuse Bot Active!** 🚨\n\n"
        "This bot automatically detects and deletes abusive messages from the chat. "
        "If you use offensive language, you will receive warnings, and repeated violations may lead to a mute or ban. "
        "Stay respectful and enjoy a positive chat experience! 😊\n\n"
        "⚠️ **How It Works:**\n"
        "🔹 First warning is a gentle reminder.\n"
        "🔹 Repeated offenses lead to stricter warnings.\n"
        "🔹 Continuous abuse will result in a mute or ban.\n\n"
        "🤖 **Admin Features:**\n"
        "✔️ Auto-deletes abusive messages.\n"
        "✔️ Issues warnings based on severity.\n"
        "✔️ Supports multiple groups.\n"
        "✔️ Works 24/7 without admin intervention.\n"
        "✔️ **Admins can use `/auth` to allow a user to bypass message deletion.**\n\n"
        "📢 **Let's keep our chat clean and friendly!** ✨"
    )
    await update.message.reply_text(start_message, parse_mode="Markdown", reply_markup=reply_markup)

async def help_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    help_text = (
        "📖 **Help Guide** 📖\n\n"
        "🔹 **How the bot works:**\n"
        "🔹 Automatically removes abusive messages.\n"
        "🔹 Issues warnings for inappropriate words.\n"
        "🔹 Users who continue abusing will be muted or banned.\n\n"
        "⚙️ **Admin Commands:**\n"
        "✅ `/auth` - Allow a user to send messages without deletion (Admin Only).\n"
        "✅ This bot protects the chat 24/7 without manual intervention.\n\n"
        "📢 **Join our support group for more details!**"
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(help_text, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user

    if chat_id in AUTHORIZED_USERS and user.id in AUTHORIZED_USERS[chat_id]:
        return

    message_words = re.findall(r'\b\w+\b', update.message.text.lower())

    if any(word in ABUSIVE_WORDS for word in message_words):
        try:
            await update.message.delete()
        except telegram.error.BadRequest:
            logger.warning(f"Failed to delete message in chat {chat_id}")

        user_warnings = USER_WARNINGS.get(chat_id, {})
        user_warnings[user.id] = user_warnings.get(user.id, 0) + 1
        USER_WARNINGS[chat_id] = user_warnings

        level = min(user_warnings[user.id], 10)
        warning_text = WARNING_MESSAGES[level].format(user=user.first_name)

        await update.message.reply_text(warning_text)

        if level >= 6:
            try:
                if level == 6:
                    await context.bot.restrict_chat_member(chat_id, user.id, can_send_messages=False)
                    await update.message.reply_text(f"🔇 {user.first_name} has been muted for repeated violations!")
                elif level >= 9:
                    await context.bot.ban_chat_member(chat_id, user.id)
                    await update.message.reply_text(f"🚷 {user.first_name} has been banned for breaking the rules!")
            except telegram.error.BadRequest:
                logger.warning(f"Failed to mute/ban {user.id} in chat {chat_id}")
                
async def back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("📢 Support", url="https://t.me/Gaming_World_Update")],
        [InlineKeyboardButton("🔄 Updates", url="https://t.me/Gaming_World_Update")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    start_message = (
        "🚨 **Anti-Abuse Bot Active!** 🚨\n\n"
        "This bot automatically detects and deletes abusive messages from the chat. "
        "If you use offensive language, you will receive warnings, and repeated violations may lead to a mute or ban. "
        "Stay respectful and enjoy a positive chat experience! 😊\n\n"
        "⚠️ **How It Works:**\n"
        "🔹 First warning is a gentle reminder.\n"
        "🔹 Repeated offenses lead to stricter warnings.\n"
        "🔹 Continuous abuse will result in a mute or ban.\n\n"
        "🤖 **Admin Features:**\n"
        "✔️ Auto-deletes abusive messages.\n"
        "✔️ Issues warnings based on severity.\n"
        "✔️ Supports multiple groups.\n"
        "✔️ Works 24/7 without admin intervention.\n"
        "✔️ **Admins can use `/auth` to allow a user to bypass message deletion.**\n\n"
        "📢 **Let's keep our chat clean and friendly!** ✨"
    )

    await query.message.edit_text(start_message, parse_mode="Markdown", reply_markup=reply_markup)
async def handle_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in GROUP_IDS:
        GROUP_IDS.add(chat_id)
        save_groups(GROUP_IDS)
        await update.message.reply_text("✅ This group is now protected by the Anti-Abuse Bot!")
        
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(help_button, pattern="help"))
    app.add_handler(CallbackQueryHandler(back_button, pattern="back"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
