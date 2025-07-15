import json
import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

DATA_FILE = "data.json"

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"admins": [], "events": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(user_id: int) -> bool:
    return user_id in load_data().get("admins", [])

def main_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="/add"))
    kb.add(KeyboardButton(text="/list"))
    kb.add(KeyboardButton(text="/help"))
    return kb.as_markup(resize_keyboard=True)

def format_date_ddmmyyyy(date_str_iso: str) -> str:
    try:
        dt = datetime.strptime(date_str_iso, "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return date_str_iso

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"Привет, <b>{message.from_user.first_name}</b>!\nЯ — бот для управления расписанием.",
        reply_markup=main_keyboard()
    )
    await cmd_help(message)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>Команды:</b>\n"
        "/add — добавить событие (многострочный ввод)\n"
        "/list — показать расписание с кнопками удаления (для админов)\n"
        "/help — показать это сообщение"
    )
    await message.answer(text)

@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У тебя нет прав для добавления событий.")
    await message.answer(
        "📥 Введите событие в формате:\n"
        "Название\n"
        "Дата (ДД.ММ.ГГГГ)\n"
        "Время (ЧЧ:ММ)\n"
        "Место\n"
        "Комментарий (опционально)"
    )

@dp.message()
async def handle_multiline_event(message: Message):
    if not is_admin(message.from_user.id):
        return

    lines = message.text.strip().split("\n")
    if len(lines) < 4:
        return

    title, date_str_input, time_str, location = lines[:4]
    comment = "\n".join(lines[4:]) if len(lines) > 4 else ""

    # Парсим дату из ДД.ММ.ГГГГ и конвертим в ISO для хранения
    try:
        dt = datetime.strptime(date_str_input.strip(), "%d.%m.%Y")
        date_str = dt.strftime("%Y-%m-%d")
    except ValueError:
        return await message.answer("❌ Неверный формат даты. Используй ДД.ММ.ГГГГ")

    # Проверка времени
    try:
        datetime.strptime(time_str.strip(), "%H:%M")
    except ValueError:
        return await message.answer("❌ Неверный формат времени. Используй ЧЧ:ММ")

    data = load_data()
    data["events"].append({
        "title": title.strip(),
        "date": date_str,
        "time": time_str.strip(),
        "location": location.strip(),
        "comment": comment.strip()
    })
    save_data(data)
    await message.answer("✅ Событие добавлено!")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    data = load_data()
    events = data.get("events", [])

    if not events:
        await message.answer("📭 Список событий пуст.")
        return

    builder = InlineKeyboardBuilder()
    text_lines = []
    for i, e in enumerate(events):
        date_str = format_date_ddmmyyyy(e['date'])
        comment_text = e['comment'] if e['comment'] else "-"
        text_lines.append(
            f"<b>{i+1}.</b> {e['title']}\n"
            f"🗓 {date_str} {e['time']}\n"
            f"📍 {e['location']}\n"
            f"📝 {comment_text}\n"
        )
        if is_admin(message.from_user.id):
            builder.button(text=f"Удалить {i+1}", callback_data=f"confirm_remove_{i}")

    await message.answer(
        "<b>Список событий:</b>\n\n" + "\n".join(text_lines),
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_remove_"))
async def process_confirm_remove(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У тебя нет прав на удаление.", show_alert=True)
        return

    index = int(callback.data.split("_")[-1])
    data = load_data()
    events = data.get("events", [])

    if 0 <= index < len(events):
        removed = events.pop(index)
        save_data(data)
        await callback.message.edit_text(
            f"🗑 Событие удалено:\n\n<b>{removed['title']}</b>\nДата: {format_date_ddmmyyyy(removed['date'])} {removed['time']}"
        )
    else:
        await callback.answer("❌ Событие не найдено.", show_alert=True)

async def send_today_schedule():
    data = load_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    events = [e for e in data["events"] if e["date"] == today_str]

    if not events:
        text = "Сегодня нет событий."
    else:
        text = "<b>Сегодняшние события:</b>\n\n" + "\n\n".join(
            f"<b>{e['title']}</b>\n🕒 {e['time']}\n📍 {e['location']}\n📝 {e['comment'] or '-'}"
            for e in events
        )

    await bot.send_message(chat_id=GROUP_ID, text=text)

async def send_weekly_schedule():
    data = load_data()
    today = datetime.now()
    week_end = today + timedelta(days=7)
    weekly_events = [
        e for e in data.get("events", [])
        if today <= datetime.strptime(e["date"], "%Y-%m-%d") < week_end
    ]

    if not weekly_events:
        text = "На эту неделю активностей нет 😴"
    else:
        text = "<b>События на неделю:</b>\n\n" + "\n\n".join(
            f"<b>{e['title']}</b> — {format_date_ddmmyyyy(e['date'])} {e['time']}\n📍 {e['location']}\n📝 {e['comment'] or '-'}"
            for e in sorted(weekly_events, key=lambda x: (x["date"], x["time"]))
        )

    await bot.send_message(chat_id=GROUP_ID, text=text)


async def main():
    logging.basicConfig(level=logging.INFO)
    # Однократная отправка этой ночью (по времени сервера)
    scheduler.add_job(send_weekly_schedule, "date",
                      run_date=datetime.now().replace(hour=1, minute=50, second=0, microsecond=0))
    scheduler.add_job(send_today_schedule, "date",
                      run_date=datetime.now().replace(hour=1, minute=51, second=0, microsecond=0))

    # Повторяющиеся задачи
    scheduler.add_job(send_weekly_schedule, "cron", day_of_week="mon", hour=8, minute=0)
    scheduler.add_job(send_today_schedule, "cron", hour=7, minute=30)

    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
