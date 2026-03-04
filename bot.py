#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          TELEGRAM-БОТ АДМИНИСТРАТОРА КВЕСТ-КОМНАТ           ║
║                                                              ║
║  • Приём и отмена бронирований                               ║
║  • Напоминания за 24ч и 2ч до игры                          ║
║  • FAQ с быстрыми ответами                                   ║
║  • Уведомления администратору                                ║
║  • Команды /today и /week для расписания                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
from datetime import date, datetime, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import database as db

# ─── Логирование ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Состояния диалога ────────────────────────────────────────
(
    MAIN_MENU,
    BOOKING_QUEST,
    BOOKING_DATE,
    BOOKING_TIME,
    BOOKING_NAME,
    BOOKING_PHONE,
    BOOKING_CONFIRM,
    MY_BOOKINGS,
    FAQ_MENU,
) = range(9)
from dotenv import load_dotenv
load_dotenv()

# ════════════════════════════════════════════════════════════════
#   КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════════════

def kb_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["📅 Забронировать квест"],
            ["📋 Мои бронирования", "❓ Частые вопросы"],
            ["📞 Связаться с нами"],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие...",
    )


def kb_quests() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(q["name"], callback_data=f"quest:{qid}")]
        for qid, q in config.QUESTS.items()
    ]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(buttons)


def kb_dates(quest_id: str) -> InlineKeyboardMarkup:
    today = date.today()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons, row = [], []

    for i in range(1, 15):          # следующие 14 дней
        d = today + timedelta(days=i)
        wd = weekdays[d.weekday()]
        label = f"{d.day:02d}.{d.month:02d} {wd}"
        row.append(InlineKeyboardButton(label, callback_data=f"date:{d.isoformat()}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back:quest")])
    return InlineKeyboardMarkup(buttons)


def kb_times(quest_id: str, booking_date: str) -> InlineKeyboardMarkup:
    booked = db.get_booked_slots(quest_id, booking_date)
    slots  = config.QUESTS[quest_id]["time_slots"]
    buttons, row = [], []

    for slot in slots:
        if slot in booked:
            btn = InlineKeyboardButton(f"❌ {slot}", callback_data="slot:busy")
        else:
            btn = InlineKeyboardButton(f"✅ {slot}", callback_data=f"time:{slot}")
        row.append(btn)
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back:date")])
    return InlineKeyboardMarkup(buttons)


def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить", callback_data="confirm:yes"),
        InlineKeyboardButton("✏️ Изменить",    callback_data="confirm:edit"),
    ]])


def kb_my_bookings(bookings: list) -> InlineKeyboardMarkup:
    buttons = []
    for bk_id, quest_id, bdate, btime, status in bookings:
        qname = config.QUESTS.get(quest_id, {}).get("name", quest_id)
        d     = datetime.strptime(bdate, "%Y-%m-%d").strftime("%d.%m")
        emoji = "✅" if status == "confirmed" else "❌"
        label = f"{emoji} {qname[:22]} | {d} {btime}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"view:{bk_id}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(buttons)


def kb_booking_detail(booking_id: int, status: str) -> InlineKeyboardMarkup:
    buttons = []
    if status == "confirmed":
        buttons.append([
            InlineKeyboardButton("❌ Отменить бронирование", callback_data=f"cancel:{booking_id}")
        ])
    buttons.append([InlineKeyboardButton("🔙 К списку", callback_data="back:my_bookings")])
    return InlineKeyboardMarkup(buttons)


def kb_faq() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(item["q"], callback_data=f"faq:{i}")]
        for i, item in enumerate(config.FAQ_ITEMS)
    ]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(buttons)


# ════════════════════════════════════════════════════════════════
#   ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════

def fmt_booking_summary(ud: dict) -> str:
    """Форматирует сводку бронирования из user_data."""
    quest  = config.QUESTS[ud["quest_id"]]
    bdate  = datetime.strptime(ud["booking_date"], "%Y-%m-%d")
    wdays  = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
    return (
        f"🎮 <b>Квест:</b> {quest['name']}\n"
        f"📅 <b>Дата:</b> {bdate.strftime('%d.%m.%Y')} ({wdays[bdate.weekday()]})\n"
        f"⏰ <b>Время:</b> {ud['booking_time']}\n"
        f"⏱ <b>Длительность:</b> {quest['duration']} мин\n"
        f"💰 <b>Стоимость:</b> {quest['price']:,} ₽\n"
        f"👤 <b>Имя:</b> {ud['client_name']}\n"
        f"📱 <b>Телефон:</b> {ud['client_phone']}"
    )


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    try:
        await context.bot.send_message(
            config.ADMIN_CHAT_ID, text, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("Admin notification failed: %s", e)


# ════════════════════════════════════════════════════════════════
#   ТОЧКА ВХОДА / ГЛАВНОЕ МЕНЮ
# ════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        "Добро пожаловать в <b>Quest Rooms</b> — сеть квест-комнат!\n\n"
        "Я ваш виртуальный администратор. Помогу:\n"
        "📅 Забронировать квест\n"
        "📋 Управлять бронированиями\n"
        "❓ Ответить на любые вопросы\n\n"
        "Выберите действие 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(),
    )
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == "📅 Забронировать квест":
        await update.message.reply_text(
            "🎮 Выберите квест-комнату:",
            reply_markup=kb_quests(),
        )
        return BOOKING_QUEST

    if text == "📋 Мои бронирования":
        return await show_my_bookings_msg(update, context)

    if text == "❓ Частые вопросы":
        await update.message.reply_text(
            "❓ <b>Часто задаваемые вопросы</b>\n\nВыберите интересующий вопрос:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_faq(),
        )
        return FAQ_MENU

    if text == "📞 Связаться с нами":
        await update.message.reply_text(
            f"📞 <b>Контакты</b>\n\n{config.CONTACT_INFO}\n\n"
            "Ответим в течение нескольких минут!",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main_menu(),
        )
        return MAIN_MENU

    await update.message.reply_text(
        "Воспользуйтесь меню ниже 👇", reply_markup=kb_main_menu()
    )
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 1: выбор квеста
# ════════════════════════════════════════════════════════════════

async def cb_quest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    if q.data == "back:main":
        await q.message.delete()
        await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())
        return MAIN_MENU

    quest_id = q.data.split(":", 1)[1]
    context.user_data["quest_id"] = quest_id
    quest = config.QUESTS[quest_id]

    await q.message.edit_text(
        f"{quest['name']}\n\n{quest['description']}\n\n"
        "📆 Выберите <b>дату</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_dates(quest_id),
    )
    return BOOKING_DATE


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 2: выбор даты
# ════════════════════════════════════════════════════════════════

async def cb_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    if q.data == "back:quest":
        await q.message.edit_text("🎮 Выберите квест-комнату:", reply_markup=kb_quests())
        return BOOKING_QUEST

    booking_date = q.data.split(":", 1)[1]
    context.user_data["booking_date"] = booking_date
    quest_id = context.user_data["quest_id"]

    d  = datetime.strptime(booking_date, "%Y-%m-%d")
    wd = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"][d.weekday()]

    await q.message.edit_text(
        f"📅 Дата: <b>{d.strftime('%d.%m.%Y')}</b> ({wd})\n\n"
        "⏰ Выберите <b>время</b>:\n"
        "✅ — свободно   ❌ — занято",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_times(quest_id, booking_date),
    )
    return BOOKING_TIME


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 3: выбор времени
# ════════════════════════════════════════════════════════════════

async def cb_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query

    if q.data == "slot:busy":
        await q.answer("Это время уже занято — выберите другое.", show_alert=True)
        return BOOKING_TIME

    if q.data == "back:date":
        await q.answer()
        qid   = context.user_data["quest_id"]
        quest = config.QUESTS[qid]
        await q.message.edit_text(
            f"{quest['name']}\n\n{quest['description']}\n\n📆 Выберите <b>дату</b>:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_dates(qid),
        )
        return BOOKING_DATE

    await q.answer()
    booking_time = q.data.split(":", 1)[1]
    context.user_data["booking_time"] = booking_time

    await q.message.edit_text(
        f"⏰ Время: <b>{booking_time}</b>\n\n"
        "👤 Введите ваше <b>имя и фамилию</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=None,
    )
    return BOOKING_NAME


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 4: имя
# ════════════════════════════════════════════════════════════════

async def msg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()

    if len(name) < 2 or any(ch.isdigit() for ch in name):
        await update.message.reply_text(
            "❗ Пожалуйста, введите настоящее имя (и фамилию).\n"
            "Например: <b>Иван Петров</b>",
            parse_mode=ParseMode.HTML,
        )
        return BOOKING_NAME

    context.user_data["client_name"] = name
    await update.message.reply_text(
        f"Отлично, <b>{name}</b>! 👋\n\n"
        "📱 Введите ваш <b>номер телефона</b>:\n"
        "<i>Например: +7 999 123-45-67</i>",
        parse_mode=ParseMode.HTML,
    )
    return BOOKING_PHONE


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 5: телефон
# ════════════════════════════════════════════════════════════════

async def msg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw   = update.message.text.strip()
    digits = "".join(filter(str.isdigit, raw))

    if len(digits) < 10:
        await update.message.reply_text(
            "❗ Номер телефона должен содержать минимум 10 цифр.\n"
            "Попробуйте ещё раз: <i>+7 999 123-45-67</i>",
            parse_mode=ParseMode.HTML,
        )
        return BOOKING_PHONE

    context.user_data["client_phone"] = raw

    await update.message.reply_text(
        "📋 <b>Проверьте данные бронирования:</b>\n\n"
        + fmt_booking_summary(context.user_data)
        + "\n\nВсё верно?",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_confirm(),
    )
    return BOOKING_CONFIRM


# ════════════════════════════════════════════════════════════════
#   БРОНИРОВАНИЕ — шаг 6: подтверждение
# ════════════════════════════════════════════════════════════════

async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ud = context.user_data

    if q.data == "confirm:edit":
        # Начинаем заново с выбора квеста
        await q.message.edit_text("🎮 Выберите квест-комнату:", reply_markup=kb_quests())
        return BOOKING_QUEST

    # ── Подтверждение ──────────────────────────────────────────
    if q.data == "confirm:yes":
        # Финальная проверка доступности слота (могли забрать за время диалога)
        if not db.slot_is_available(ud["quest_id"], ud["booking_date"], ud["booking_time"]):
            await q.message.edit_text(
                "😔 К сожалению, это время только что заняли.\n"
                "Пожалуйста, выберите другое.",
                reply_markup=None,
            )
            await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())
            return MAIN_MENU

        user  = q.from_user
        bk_id = db.create_booking(
            user_id      = user.id,
            username     = user.username or "",
            quest_id     = ud["quest_id"],
            booking_date = ud["booking_date"],
            booking_time = ud["booking_time"],
            name         = ud["client_name"],
            phone        = ud["client_phone"],
        )

        quest = config.QUESTS[ud["quest_id"]]
        bdate = datetime.strptime(ud["booking_date"], "%Y-%m-%d")

        await q.message.edit_text(
            f"🎉 <b>Бронирование подтверждено!</b>\n\n"
            + fmt_booking_summary(ud)
            + f"\n\n🔑 Номер брони: <code>#{bk_id}</code>\n"
            f"📍 {config.ADDRESS}\n\n"
            "🔔 Напомним за 24 часа и за 2 часа до игры!\n"
            "⏰ Просим прийти за 10–15 минут.\n\n"
            "До встречи! 🚀",
            parse_mode=ParseMode.HTML,
            reply_markup=None,
        )
        await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())

        # Уведомляем администратора
        uname_str = f"@{user.username}" if user.username else f"ID {user.id}"
        await notify_admin(
            context,
            f"🆕 <b>Новое бронирование #{bk_id}</b>\n\n"
            f"{fmt_booking_summary(ud)}\n"
            f"💬 Telegram: {uname_str}",
        )

        context.user_data.clear()
        return MAIN_MENU

    return BOOKING_CONFIRM


# ════════════════════════════════════════════════════════════════
#   МОИ БРОНИРОВАНИЯ
# ════════════════════════════════════════════════════════════════

async def show_my_bookings_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bookings = db.get_user_bookings(update.effective_user.id)
    if not bookings:
        await update.message.reply_text(
            "📋 У вас нет предстоящих бронирований.\n\n"
            "Нажмите «📅 Забронировать квест»!",
            reply_markup=kb_main_menu(),
        )
        return MAIN_MENU

    await update.message.reply_text(
        "📋 <b>Ваши бронирования:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_my_bookings(bookings),
    )
    return MY_BOOKINGS


async def cb_my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q  = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ── Назад в главное меню ───────────────────────────────────
    if q.data == "back:main":
        await q.message.delete()
        await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())
        return MAIN_MENU

    # ── Назад к списку броней ──────────────────────────────────
    if q.data == "back:my_bookings":
        bookings = db.get_user_bookings(uid)
        if not bookings:
            await q.message.edit_text(
                "📋 Нет предстоящих бронирований.", reply_markup=None
            )
            await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())
            return MAIN_MENU
        await q.message.edit_text(
            "📋 <b>Ваши бронирования:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_my_bookings(bookings),
        )
        return MY_BOOKINGS

    # ── Просмотр конкретной брони ──────────────────────────────
    if q.data.startswith("view:"):
        bk_id = int(q.data.split(":")[1])
        bk    = db.get_booking_by_id(bk_id, uid)
        if not bk:
            await q.message.edit_text("Бронирование не найдено.", reply_markup=None)
            return MAIN_MENU

        _, _uid, _uname, qid, bdate, btime, cname, cphone, status, created, *_ = bk
        quest = config.QUESTS.get(qid, {})
        d     = datetime.strptime(bdate, "%Y-%m-%d")
        emoji = "✅ Активно" if status == "confirmed" else "❌ Отменено"

        await q.message.edit_text(
            f"🔑 <b>Бронирование #{bk_id}</b>\n\n"
            f"🎮 {quest.get('name', qid)}\n"
            f"📅 {d.strftime('%d.%m.%Y')} в {btime}\n"
            f"⏱ {quest.get('duration', '—')} минут\n"
            f"💰 {quest.get('price', 0):,} ₽\n"
            f"👤 {cname}   📱 {cphone}\n"
            f"📊 Статус: {emoji}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_booking_detail(bk_id, status),
        )
        return MY_BOOKINGS

    # ── Отмена брони ───────────────────────────────────────────
    if q.data.startswith("cancel:"):
        bk_id = int(q.data.split(":")[1])
        bk    = db.get_booking_by_id(bk_id, uid)

        if not bk:
            await q.message.edit_text("Бронирование не найдено.", reply_markup=None)
            return MAIN_MENU

        _, _uid, _uname, qid, bdate, btime, cname, cphone, status, *_ = bk

        # Проверяем 24-часовое ограничение
        try:
            bk_dt  = datetime.strptime(f"{bdate} {btime}", "%Y-%m-%d %H:%M")
            too_late = (bk_dt - datetime.now()) < timedelta(hours=24)
        except ValueError:
            too_late = False

        if too_late:
            await q.message.edit_text(
                "⚠️ <b>Бесплатная отмена возможна только за 24 часа</b> до начала.\n\n"
                "Для отмены в другое время свяжитесь с нами:\n"
                f"{config.CONTACT_INFO}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="back:my_bookings")
                ]]),
            )
            return MY_BOOKINGS

        ok = db.cancel_booking(bk_id, uid)
        if ok:
            await q.message.edit_text(
                f"✅ Бронирование <b>#{bk_id}</b> успешно отменено.\n\n"
                "Будем рады видеть вас снова! 🙏",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Новое бронирование", callback_data="new_booking"),
                    InlineKeyboardButton("🔙 Меню",               callback_data="back:main"),
                ]]),
            )
            await notify_admin(
                context,
                f"❌ <b>Отмена бронирования #{bk_id}</b>\n"
                f"🎮 {config.QUESTS.get(qid, {}).get('name', qid)}\n"
                f"📅 {bdate} {btime}\n"
                f"👤 {cname}   📱 {cphone}",
            )
        else:
            await q.message.edit_text(
                "Не удалось отменить. Обратитесь к администратору.",
                reply_markup=None,
            )
        return MY_BOOKINGS

    # ── Кнопка «Новое бронирование» ───────────────────────────
    if q.data == "new_booking":
        await q.message.edit_text("🎮 Выберите квест-комнату:", reply_markup=kb_quests())
        return BOOKING_QUEST

    return MY_BOOKINGS


# ════════════════════════════════════════════════════════════════
#   FAQ
# ════════════════════════════════════════════════════════════════

async def cb_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    if q.data == "back:main":
        await q.message.delete()
        await q.message.reply_text("Главное меню 👇", reply_markup=kb_main_menu())
        return MAIN_MENU

    if q.data == "back:faq":
        await q.message.edit_text(
            "❓ <b>Часто задаваемые вопросы</b>\n\nВыберите интересующий вопрос:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_faq(),
        )
        return FAQ_MENU

    if q.data.startswith("faq:"):
        idx  = int(q.data.split(":")[1])
        item = config.FAQ_ITEMS[idx]
        await q.message.edit_text(
            f"❓ <b>{item['q']}</b>\n\n{item['a']}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Все вопросы", callback_data="back:faq"),
                InlineKeyboardButton("🏠 Главная",     callback_data="back:main"),
            ]]),
        )
        return FAQ_MENU

    return FAQ_MENU


# ════════════════════════════════════════════════════════════════
#   АДМИНИСТРАТИВНЫЕ КОМАНДЫ
# ════════════════════════════════════════════════════════════════

def _is_admin(update: Update) -> bool:
    return update.effective_user.id == config.ADMIN_CHAT_ID


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    bookings = db.get_today_bookings()
    if not bookings:
        await update.message.reply_text(
            f"📅 На <b>{datetime.now().strftime('%d.%m.%Y')}</b> бронирований нет.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📅 <b>Расписание на {datetime.now().strftime('%d.%m.%Y')}:</b>\n"]
    prev_quest = None
    for bk_id, qid, btime, cname, cphone, uname in bookings:
        qname = config.QUESTS.get(qid, {}).get("name", qid)
        if qid != prev_quest:
            lines.append(f"\n{qname}")
            prev_quest = qid
        tag = f"@{uname}" if uname else ""
        lines.append(f"  ⏰ {btime} — {cname}  📱 {cphone}  {tag}  [#{bk_id}]")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    bookings = db.get_week_bookings()
    if not bookings:
        await update.message.reply_text("📅 На ближайшие 7 дней бронирований нет.")
        return

    wdays = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    lines = ["📆 <b>Расписание на 7 дней:</b>"]
    cur_date = None

    for bk_id, qid, bdate, btime, cname, cphone in bookings:
        d = datetime.strptime(bdate, "%Y-%m-%d")
        if bdate != cur_date:
            cur_date = bdate
            lines.append(f"\n<b>{d.strftime('%d.%m.%Y')} ({wdays[d.weekday()]})</b>")
        qname = config.QUESTS.get(qid, {}).get("name", qid)
        lines.append(f"  ⏰ {btime} — {qname[:20]}  👤 {cname}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ════════════════════════════════════════════════════════════════
#   ДЖОБ: НАПОМИНАНИЯ
# ════════════════════════════════════════════════════════════════

async def job_send_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запускается каждые 30 минут. Отправляет напоминания клиентам."""
    items = db.get_bookings_needing_reminder()
    for rtype, row in items:
        bk_id, uid, qid, bdate, btime, cname, *_ = row
        quest = config.QUESTS.get(qid, {})
        d     = datetime.strptime(bdate, "%Y-%m-%d")

        if rtype == "24h":
            text = (
                f"🔔 <b>Напоминание о вашем квесте!</b>\n\n"
                f"Завтра в <b>{btime}</b> вас ждёт:\n"
                f"🎮 {quest.get('name', qid)}\n"
                f"📅 {d.strftime('%d.%m.%Y')}\n\n"
                f"📍 {config.ADDRESS}\n"
                "⏰ Приходите за 10–15 минут до начала!\n\n"
                "До встречи! 🚀"
            )
        else:
            text = (
                f"⏰ <b>Ваш квест — через 2 часа!</b>\n\n"
                f"🎮 {quest.get('name', qid)}\n"
                f"📅 {d.strftime('%d.%m.%Y')} в <b>{btime}</b>\n\n"
                f"📍 {config.ADDRESS}\n"
                "Ждём вас! Не забудьте захватить хорошее настроение 🎉"
            )

        try:
            await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
            db.mark_reminded(bk_id, rtype)
            logger.info("Reminder %s sent to user %s (booking #%s)", rtype, uid, bk_id)
        except Exception as e:
            logger.error("Reminder failed for user %s: %s", uid, e)


# ════════════════════════════════════════════════════════════════
#   ЗАПУСК
# ════════════════════════════════════════════════════════════════

def main() -> None:
    db.init_db()
    logger.info("Database initialized.")

    app = Application.builder().token(config.BOT_TOKEN).build()

    # ── Основной диалог ────────────────────────────────────────
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            BOOKING_QUEST: [
                CallbackQueryHandler(cb_quest, pattern=r"^(quest:|back:main)"),
            ],
            BOOKING_DATE: [
                CallbackQueryHandler(cb_date, pattern=r"^(date:|back:quest)"),
            ],
            BOOKING_TIME: [
                CallbackQueryHandler(cb_time, pattern=r"^(time:|slot:|back:date)"),
            ],
            BOOKING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_name),
            ],
            BOOKING_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_phone),
            ],
            BOOKING_CONFIRM: [
                CallbackQueryHandler(cb_confirm, pattern=r"^confirm:"),
            ],
            MY_BOOKINGS: [
                CallbackQueryHandler(
                    cb_my_bookings,
                    pattern=r"^(view:|cancel:|back:my_bookings|back:main|new_booking)",
                ),
            ],
            FAQ_MENU: [
                CallbackQueryHandler(cb_faq, pattern=r"^(faq:|back:faq|back:main)"),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
        ],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)

    # ── Команды администратора ─────────────────────────────────
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week",  cmd_week))

    # ── Джоб: напоминания каждые 30 минут ─────────────────────
    app.job_queue.run_repeating(job_send_reminders, interval=1800, first=30)

    logger.info("Bot is running... Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
