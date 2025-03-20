import os
import logging
import re
import motor.motor_asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import telegram.error
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = "mongodb+srv://botmaker9675208:botmaker9675208@cluster0.sc9mq8b.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["AntiAbuseBot"]
users_collection = db["users"]
groups_collection = db["groups"]
authorized_users_collection = db["authorized_users"]

ABUSE_FILE = "abuse.txt"

USER_WARNINGS = {}

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

async def is_owner(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status == ChatMember.OWNER
    except telegram.error.BadRequest:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    existing_user = await users_collection.find_one({"user_id": user_id})
    if not existing_user:
        await users_collection.insert_one({"user_id": user_id, "user_name": user_name})

    keyboard = [[InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    start_message = (
        "🚨 **Anti-Abuse Bot Active!** 🚨\n\n"
        "This bot automatically detects and deletes abusive messages from the chat. "
        "If you use offensive language, you will receive warnings, and repeated violations may lead to a mute or ban.\n\n"
        "📢 **Let's keep our chat clean and friendly!** ✨"
    )
    await update.message.reply_text(start_message, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    existing_group = await groups_collection.find_one({"group_id": chat_id})

    if not existing_group:
        await groups_collection.insert_one({"group_id": chat_id})

    await update.message.reply_text("✅ This group is now protected by the Anti-Abuse Bot!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user

    authorized = await authorized_users_collection.find_one({"group_id": chat_id, "user_id": user.id})
    if authorized:
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

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to a user's message to authorize them.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user_id = update.message.reply_to_message.from_user.id
    user_name = update.message.reply_to_message.from_user.first_name

    if not await is_admin(update, admin_id):
        await update.message.reply_text("🚫 Only group admins can use this command!")
        return

    await authorized_users_collection.update_one(
        {"group_id": chat_id, "user_id": user_id},
        {"$set": {"user_name": user_name}},
        upsert=True
    )
    await update.message.reply_text(f"✅ [{user_name}](tg://openmessage?user_id={user_id}) is now authorized.", parse_mode="Markdown")

async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to a user's message to unauthorize them.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user_id = update.message.reply_to_message.from_user.id

    if not await is_admin(update, admin_id):
        await update.message.reply_text("🚫 Only group admins can use this command!")
        return

    await authorized_users_collection.delete_one({"group_id": chat_id, "user_id": user_id})
    await update.message.reply_text(f"❌ User has been unauthorized.")

async def authadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    sender_id = update.message.from_user.id

    if not await is_owner(update, sender_id):
        await update.message.reply_text("🚫 Only the **group owner** can use this command!", parse_mode="Markdown")
        return

    admins = await context.bot.get_chat_administrators(chat_id)
    for admin in admins:
        if admin.user.id != sender_id:
            await authorized_users_collection.update_one(
                {"group_id": chat_id, "user_id": admin.user.id},
                {"$set": {"user_name": admin.user.first_name}},
                upsert=True
            )

    await update.message.reply_text("✅ All admins have been authorized.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("unauth", unauth))
    app.add_handler(CommandHandler("authadmin", authadmin))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
        
