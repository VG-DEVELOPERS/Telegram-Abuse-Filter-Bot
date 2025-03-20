import asyncio
import logging
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
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
    6: "🔇 {user}, you've been muted for repeated violations!",
    7: "🚫 {user}, you’ve crossed the line. Consider this a final notice!",
    8: "☢️ {user}, next time, you're banned!",
    9: "⚰️ {user}, you’re getting removed now!",
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

async def is_admin(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except telegram.error.BadRequest:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    start_message = (
        "🚨 **Anti-Abuse Bot Active!** 🚨\n\n"
        "This bot automatically detects and deletes abusive messages. "
        "If you use offensive language, you will receive warnings, and repeated violations may lead to a mute or ban.\n\n"
        "📢 **Let's keep our chat clean and friendly!** ✨"
    )
    await update.message.reply_text(start_message, parse_mode="Markdown", reply_markup=reply_markup)

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
        mention = f"[{user.first_name}](tg://openmessage?user_id={user.id})"
        warning_text = WARNING_MESSAGES[level].format(user=mention)

        await context.bot.send_message(chat_id, text=warning_text, parse_mode="Markdown")

        if level >= 6:
            try:
                if level == 6:
                    await context.bot.restrict_chat_member(chat_id, user.id, can_send_messages=False)
                    await context.bot.send_message(chat_id, f"🔇 {mention} has been muted for repeated violations!", parse_mode="Markdown")
                elif level >= 9:
                    await context.bot.ban_chat_member(chat_id, user.id)
                    await context.bot.send_message(chat_id, f"🚷 {mention} has been banned for breaking the rules!", parse_mode="Markdown")
            except telegram.error.BadRequest:
                logger.warning(f"Failed to mute/ban {user.id} in chat {chat_id}")

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to a user's message to authorize them.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user = update.message.reply_to_message.from_user

    if not await is_admin(update, admin_id):
        await update.message.reply_text("🚫 Only group admins can use this command!")
        return

    if chat_id not in AUTHORIZED_USERS:
        AUTHORIZED_USERS[chat_id] = set()
    
    AUTHORIZED_USERS[chat_id].add(user.id)
    mention = f"[{user.first_name}](tg://openmessage?user_id={user.id})"
    await update.message.reply_text(f"✅ {mention} is now authorized. Their messages won't be deleted.", parse_mode="Markdown")

async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to a user's message to remove their authorization.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user = update.message.reply_to_message.from_user

    if not await is_admin(update, admin_id):
        await update.message.reply_text("🚫 Only group admins can use this command!")
        return

    if chat_id in AUTHORIZED_USERS and user.id in AUTHORIZED_USERS[chat_id]:
        AUTHORIZED_USERS[chat_id].remove(user.id)
        mention = f"[{user.first_name}](tg://openmessage?user_id={user.id})"
        await update.message.reply_text(f"❌ {mention} is no longer authorized. Their messages will now be monitored.", parse_mode="Markdown")
    else:
        await update.message.reply_text("ℹ️ This user was not authorized.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data == "help":
        help_message = (
            "🆘 **Help Guide**\n\n"
            "🔹 This bot automatically deletes abusive messages.\n"
            "🔹 Users receive warnings for violations.\n"
            "🔹 Severe cases result in mutes or bans.\n\n"
            "👮 **Admin Commands:**\n"
            "✔️ `/auth` - Allow a user to bypass auto-deletion.\n"
            "❌ `/unauth` - Remove a user from authorized list.\n\n"
            "🔄 Click 'Back' to return."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(help_message, parse_mode="Markdown", reply_markup=reply_markup)

    elif query.data == "back":
        await start(update, context)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("unauth", unauth))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
