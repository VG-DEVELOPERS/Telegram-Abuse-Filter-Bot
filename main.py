import os
import re
import requests
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import telegram.error
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

client = AsyncIOMotorClient(MONGO_URI)
db = client["AntiAbuseBot"]
authorized_users_col = db["authorized_users"]
groups_col = db["groups"]
admin_mode_col = db["admin_mode"]

SIGHTENGINE_API_USER = "1828919519"
SIGHTENGINE_API_SECRET = "Ci48qMLfv2PpV6zGXkFJruVv26JxYENL"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def is_owner(update: Update, user_id: int):
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status == ChatMember.OWNER
    except telegram.error.BadRequest:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = (
        "🚨 **Anti-Abuse Bot Activated!** 🚨\n\n"
        "🔹 Auto-deletes abusive messages\n"
        "🔹 Detects & removes NSFW stickers/videos\n"
        "🔹 Admins can enable admin-only mode\n\n"
        "📢 **Let's keep our chat clean!** ✨"
    )
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not await groups_col.find_one({"chat_id": chat_id}):
        await groups_col.insert_one({"chat_id": chat_id})
        await update.message.reply_text("✅ This group is now protected by the Anti-Abuse Bot!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user

    if await authorized_users_col.find_one({"chat_id": chat_id, "user_id": user.id}):
        return

    admin_mode = await admin_mode_col.find_one({"chat_id": chat_id})
    if admin_mode and admin_mode.get("enabled", False):
        if not await is_owner(update, user.id):
            return

    abusive_words = {"badword1", "badword2", "badword3"}
    message_words = re.findall(r'\b\w+\b', update.message.text.lower())

    if any(word in abusive_words for word in message_words):
        try:
            await update.message.delete()
        except telegram.error.BadRequest:
            pass

        warning_text = f"⚠️ Warning [User](tg://openmessage?user_id={user.id})! Watch your language!"
        await update.message.chat.send_message(warning_text, parse_mode="Markdown")

async def detect_nsfw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.sticker:
        file_id = update.message.sticker.file_id
    elif update.message.video:
        file_id = update.message.video.file_id

    if not file_id:
        return

    file = await context.bot.get_file(file_id)
    file_url = file.file_path

    response = requests.get(
        "https://api.sightengine.com/1.0/check.json",
        params={
            "url": file_url,
            "models": "nudity",
            "api_user": SIGHTENGINE_API_USER,
            "api_secret": SIGHTENGINE_API_SECRET,
        },
    ).json()

    if response["nudity"]["raw"] > 0.7:
        await update.message.delete()
        await update.message.chat.send_message(
            f"❌ NSFW content removed! [User](tg://openmessage?user_id={update.message.from_user.id})",
            parse_mode="Markdown",
        )

async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user to authorize them.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user = update.message.reply_to_message.from_user

    if not await is_owner(update, admin_id):
        await update.message.reply_text("🚫 Only group owner can use this command!")
        return

    await authorized_users_col.insert_one({"chat_id": chat_id, "user_id": user.id})
    await update.message.reply_text(f"✅ {user.first_name} is now authorized.")

async def unauthorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user to unauthorize them.")
        return

    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id
    user = update.message.reply_to_message.from_user

    if not await is_owner(update, admin_id):
        await update.message.reply_text("🚫 Only group owner can use this command!")
        return

    await authorized_users_col.delete_one({"chat_id": chat_id, "user_id": user.id})
    await update.message.reply_text(f"❌ {user.first_name} is no longer authorized.")

async def admin_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    admin_id = update.message.from_user.id

    if not await is_owner(update, admin_id):
        await update.message.reply_text("🚫 Only group owner can use this command!")
        return

    if len(context.args) == 0:
        await update.message.reply_text("Usage: `/admin on` or `/admin off`", parse_mode="Markdown")
        return

    mode = context.args[0].lower()
    if mode == "on":
        await admin_mode_col.update_one({"chat_id": chat_id}, {"$set": {"enabled": True}}, upsert=True)
        await update.message.reply_text("✅ Admin-only mode is now enabled!")
    elif mode == "off":
        await admin_mode_col.update_one({"chat_id": chat_id}, {"$set": {"enabled": False}}, upsert=True)
        await update.message.reply_text("❌ Admin-only mode is now disabled!")
    else:
        await update.message.reply_text("Usage: `/admin on` or `/admin off`", parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "help":
        await query.edit_message_text(
            "🆘 **Help Guide**\n\n"
            "🔹 Auto-deletes abusive messages.\n"
            "🔹 Detects & removes NSFW stickers/videos.\n"
            "🔹 Only group owner can enable admin-only mode.\n\n"
            "✔️ `/auth` - Authorize a user.\n"
            "✔️ `/unauth` - Remove authorization.\n"
            "✔️ `/admin on` - Enable admin-only mode.\n"
            "✔️ `/admin off` - Disable admin-only mode.",
            parse_mode="Markdown",
        )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", authorize))
    app.add_handler(CommandHandler("unauth", unauthorize))
    app.add_handler(CommandHandler("admin", admin_control))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Sticker.ALL | filters.Video.ALL, detect_nsfw))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.run_polling()

if __name__ == "__main__":
    main()
        
