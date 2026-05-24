import logging
import sys
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode, ChatAction

import database as db
import gemini_client as gemini
from config import (
    TELEGRAM_BOT_TOKEN, RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW,
    MIN_AGE, MAX_AGE, HISTORY_CONTEXT_COUNT,
)
from metrics import (
    start_metrics_server, REQUESTS_TOTAL, USERS_REGISTERED,
    RATE_LIMIT_HITS, ACTIVE_USERS_GAUGE, GeminiTimer,
)

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

GENDER, AGE, CHATTING = range(3)


WELCOME_NEW = (
    "Привіт! Я допоможу тобі вибрати фільм або серіал.\n\n"
    "Спочатку кілька запитань для більш точних рекомендацій.\n\n"
    "Вкажи свою стать:"
)

WELCOME_BACK = (
    "З поверненням! Твій профіль збережено.\n\n"
    "Розкажи, що хочеш подивитися?"
)

ASK_AGE = "Чудово!\n\nТепер введи свій вік (число):"

PROFILE_DONE = (
    "Профіль збережено!\n\n"
    "Тепер розкажи, що хочеш подивитися?\n"
    "Наприклад: «хочу трилер з несподіваною кінцівкою»"
)

HELP_TEXT = (
    "*Бот рекомендацій фільмів та серіалів*\n\n"
    "Просто напиши, що хочеш подивитися — я підберу варіанти.\n\n"
    "*Приклади запитів:*\n"
    "• «Хочу щось страшне, але не дуже»\n"
    "• «Порадь серіал як Breaking Bad»\n"
    "• «Що подивитися в п'ятницю ввечері з подругою?»\n\n"
    "*Команди:*\n"
    "/start — почати заново\n"
    "/history — мої останні запити\n"
    "/help — ця довідка\n\n"
    f"⏱ Ліміт: {RATE_LIMIT_MESSAGES} запитів на годину"
)



def gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👨 Чоловік", callback_data="gender_male"),
        InlineKeyboardButton("👩 Жінка", callback_data="gender_female"),
    ]])


def escape_md(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    existing = await db.get_user(user.id)

    if existing:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Продовжити", callback_data="keep_profile"),
            InlineKeyboardButton("Заново", callback_data="reset_profile"),
        ]])
        gender_ua = "чоловік" if existing["gender"] == "male" else "жінка"
        await update.message.reply_text(
            f"Привіт! У мене вже є твій профіль:\n"
            f"• Стать: {gender_ua}\n"
            f"• Вік: {existing['age']} років\n\n"
            f"Продовжити або заповнити заново?",
            reply_markup=keyboard,
        )
        return GENDER

    await update.message.reply_text(WELCOME_NEW, reply_markup=gender_keyboard())
    return GENDER


async def start_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if query.data == "keep_profile":
        await query.edit_message_text(WELCOME_BACK)
        return CHATTING
    else:
        await db.delete_user(user.id)
        await query.edit_message_text(
            "🔄 Профіль скинуто!\n\n👤 Вкажи свою стать:",
            reply_markup=gender_keyboard(),
        )
        return GENDER



async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data not in ("gender_male", "gender_female"):
        return GENDER

    gender = "male" if query.data == "gender_male" else "female"
    context.user_data["gender"] = gender
    label = "👨 Чоловік" if gender == "male" else "👩 Жінка"
    await query.edit_message_text(f"Стать: {label}\n\n{ASK_AGE}")
    return AGE



async def age_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "Введи вік *цифрами*. Наприклад: `25`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AGE

    age = int(text)
    if age < MIN_AGE or age > MAX_AGE:
        await update.message.reply_text(
            f"Введи реальний вік від {MIN_AGE} до {MAX_AGE} років."
        )
        return AGE

    gender = context.user_data.get("gender")
    if not gender:
        await update.message.reply_text(
            "Щось пішло не так. Напиши /start щоб почати заново."
        )
        return ConversationHandler.END

    user = update.effective_user
    await db.save_user(user.id, user.username, gender, age)

    USERS_REGISTERED.inc()
    logger.info(f"Новий користувач: id={user.id}, gender={gender}, age={age}")

    await update.message.reply_text(PROFILE_DONE)
    return CHATTING



async def handle_recommendation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_query = update.message.text.strip()

    if not user_query:
        return CHATTING

    if await db.is_rate_limited(user.id):
        RATE_LIMIT_HITS.inc()
        REQUESTS_TOTAL.labels(status="rate_limited").inc()
        window_min = RATE_LIMIT_WINDOW // 60
        await update.message.reply_text(
            f"⏱ Ти вичерпав ліміт ({RATE_LIMIT_MESSAGES} запитів на {window_min} хв).\n"
            f"Зачекай трохи і спробуй знову!"
        )
        return CHATTING

    user_record = await db.get_user(user.id)
    if not user_record:
        await update.message.reply_text(
            "Профіль не знайдено. Напиши /start щоб почати заново."
        )
        return ConversationHandler.END

    await update.effective_chat.send_action(ChatAction.TYPING)

    history = await db.get_recent_history(user.id, limit=HISTORY_CONTEXT_COUNT)

    try:
        async with GeminiTimer():
            response_text = await gemini.get_recommendation(
                user_query=user_query,
                gender=user_record["gender"],
                age=user_record["age"],
                history=history,
            )
        REQUESTS_TOTAL.labels(status="success").inc()

    except Exception as e:
        logger.error(f"Помилка Gemini для user={user.id}: {e}")
        REQUESTS_TOTAL.labels(status="error").inc()
        await update.message.reply_text(
            "Сталася помилка при зверненні до AI. Спробуй за хвилину."
        )
        return CHATTING

    await db.save_message(user.id, user_query, response_text)

    asyncio.create_task(_update_active_users())

    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)
    return CHATTING


async def _update_active_users():
    try:
        count = await db.count_active_users_last_hour()
        ACTIVE_USERS_GAUGE.set(count)
    except Exception as e:
        logger.warning(f"Не вдалося оновити gauge активних користувачів: {e}")



async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    history = await db.get_recent_history(user.id, limit=5)

    if not history:
        await update.message.reply_text("Історія порожня. Запитай щось!")
        return

    text = "Твої останні запити:\n\n"
    for i, row in enumerate(history, 1):
        date_str = row["created_at"].strftime("%d.%m %H:%M")
        text += f"*{i}\\. \\[{escape_md(date_str)}\\]*\n🗣 _{escape_md(row['user_query'])}_\n\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)



async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)



async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши /start щоб почати роботу з ботом.")



async def on_startup(app: Application):
    await db.init_db()
    await start_metrics_server(port=8000)
    logger.info("Бот і сервер метрик запущено ✓")


async def on_shutdown(app: Application):
    await db.close_pool()
    logger.info("Бот зупинено")



def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GENDER: [
                CallbackQueryHandler(start_profile_callback, pattern="^(keep_profile|reset_profile)$"),
                CallbackQueryHandler(gender_callback, pattern="^gender_"),
            ],
            AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, age_input),
            ],
            CHATTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recommendation),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CommandHandler("history", history_command),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("Запуск polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()