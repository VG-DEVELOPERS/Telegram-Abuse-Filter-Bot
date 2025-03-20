import asyncio
import logging
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import telegram.error
import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = 7563434309

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = mongo_client["telegram_bot"]
auth_users_collection = db["authorized_users"]
groups_collection = db["groups"]

USER_WARNINGS = {}

WARNING_MESSAGES = {
    1: "⚠️ [{user}](tg://openmessage?user_id={user_id}), please keep it respectful!",
    2: "⛔ [{user}](tg://openmessage?user_id={user_id}), second warning! Watch your words.",
    3: "🚦 [{user}](tg://openmessage?user_id={user_id}), you're on thin ice! Final warning.",
    4: "🛑 [{user}](tg://openmessage?user_id={user_id}), stop now, or you will be muted!",
    5: "🚷 [{user}](tg://openmessage?user_id={user_id}), last chance before removal!",
    6: "🔇 [{user}](tg://openmessage?user_id={user_id}), you've been muted for repeated violations!",
    7: "🚫 [{user}](tg://openmessage?user_id={user_id}), you’ve crossed the line. Consider this a final notice!",
    8: "☢️ [{user}](tg://openmessage?user_id={user_id}), next time, you're banned!",
    9: "⚰️ [{user}](tg://openmessage?user_id={user_id}), you’re getting removed now!",
    10: "🔥 [{user}](tg://openmessage?user_id={user_id}), you are banned from this group!"
}

async def is_admin(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except telegram.error.BadRequest:
        return False

async def is_group_owner(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status == ChatMember.OWNER
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

async def handle_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await groups_collection.update_one({"chat_id": chat_id}, {"$set": {"enabled": True}}, upsert=True)
    await update.message.reply_text("✅ This group is now protected by the Anti-Abuse Bot!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user

    auth_entry = await auth_users_collection.find_one({"chat_id": chat_id})
    if auth_entry and user.id in auth_entry.get("authorized_users", []):
        return

    abusive_words = {"badword1", "badword2", "badword3"}  
    message_words = set(re.findall(r'\b\w+\b', update.message.text.lower()))

    if abusive_words & message_words:
        try:
            await update.message.delete()
        except telegram.error.BadRequest:
            pass

        USER_WARNINGS.setdefault(chat_id, {}).setdefault(user.id, 0)
        USER_WARNINGS[chat_id][user.id] += 1
        level = min(USER_WARNINGS[chat_id][user.id], 10)
        warning_text = WARNING_MESSAGES[level].format(user=user.first_name, user_id=user.id)

        await context.bot.send_message(chat_id, warning_text, parse_mode="Markdown")

        if level >= 6:
            try:
                if level == 6:
                    await context.bot.restrict_chat_member(chat_id, user.id, can_send_messages=False)
                elif level >= 9:
                    await context.bot.ban_chat_member(chat_id, user.id)
            except telegram.error.BadRequest:
                pass

async def admin_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    if not await is_group_owner(update, user_id):
        await update.message.reply_text("🚫 Only the group owner can use this command!")
        return

    action = context.args[0] if context.args else None
    if action not in ["on", "off"]:
        await update.message.reply_text("❌ Usage: `/admin on` or `/admin off`", parse_mode="Markdown")
        return

    enabled = action == "on"
    await groups_collection.update_one({"chat_id": chat_id}, {"$set": {"enabled": enabled}}, upsert=True)

    status = "enabled" if enabled else "disabled"
    await update.message.reply_text(f"✅ Anti-Abuse system has been **{status}** for this group.", parse_mode="Markdown")

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    chat_id = update.message.chat_id
    user_id = update.message.reply_to_message.from_user.id

    await auth_users_collection.update_one(
        {"chat_id": chat_id}, {"$addToSet": {"authorized_users": user_id}}, upsert=True
    )
    await update.message.reply_text(f"✅ User [{user_id}](tg://openmessage?user_id={user_id}) authorized.", parse_mode="Markdown")

async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    chat_id = update.message.chat_id
    user_id = update.message.reply_to_message.from_user.id

    await auth_users_collection.update_one(
        {"chat_id": chat_id}, {"$pull": {"authorized_users": user_id}}
    )
    await update.message.reply_text(f"❌ User [{user_id}](tg://openmessage?user_id={user_id}) unauthorized.", parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("unauth", unauth))
    app.add_handler(CommandHandler("admin", admin_toggle))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
