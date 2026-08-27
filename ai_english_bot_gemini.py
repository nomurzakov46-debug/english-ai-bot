import os
import asyncio
import logging
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiosqlite
from google import genai

# ============= ЛОГИРОВАНИЕ =============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============= ТОКЕНЫ =============
# Лучше вынести в переменные окружения Render (Environment -> Add Environment Variable),
# но можно оставить и так, просто впиши свои значения.
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY)

DB_NAME = "academy_english.db"

# ============= УРОВНИ =============
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# ============= БАЗА ДАННЫХ =============
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                level TEXT DEFAULT 'A1',
                words_learned INTEGER DEFAULT 0,
                joined_date TEXT,
                total_seconds_spent INTEGER DEFAULT 0,
                last_active_time INTEGER DEFAULT 0,
                daily_words_count INTEGER DEFAULT 0,
                last_learned_date TEXT DEFAULT ''
            )
        """)
        await db.commit()
    logger.info("База данных готова.")

async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT last_learned_date FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        now_date = datetime.now().strftime("%Y-%m-%d")

        if not res:
            await db.execute(
                "INSERT INTO users (user_id, joined_date, last_active_time, last_learned_date) VALUES (?, ?, ?, ?)",
                (user_id, now_date, int(time.time()), now_date)
            )
            await db.commit()
        elif res[0] != now_date:
            await db.execute(
                "UPDATE users SET daily_words_count = 0, last_learned_date = ? WHERE user_id = ?",
                (now_date, user_id)
            )
            await db.commit()

async def get_user_level(user_id: int) -> str:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT level FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
    return res[0] if res else "A1"

async def set_user_level(user_id: int, level: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET level = ? WHERE user_id = ?", (level, user_id))
        await db.commit()

async def track_time(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT last_active_time FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        now = int(time.time())
        if res and res[0] > 0:
            diff = now - res[0]
            if 0 < diff < 600:
                await db.execute(
                    "UPDATE users SET total_seconds_spent = total_seconds_spent + ?, last_active_time = ? WHERE user_id = ?",
                    (diff, now, user_id)
                )
            else:
                await db.execute("UPDATE users SET last_active_time = ? WHERE user_id = ?", (now, user_id))
        else:
            await db.execute("UPDATE users SET last_active_time = ? WHERE user_id = ?", (now, user_id))
        await db.commit()

# ============= СОСТОЯНИЯ =============
class BotStates(StatesGroup):
    chatting = State()
    grammar = State()

# ============= КЛАВИАТУРЫ =============
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Учить слова (50 в день)"), KeyboardButton(text="💬 Разговорный чат")],
        [KeyboardButton(text="📖 Грамматика"), KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="🎯 Мой уровень"), KeyboardButton(text="📝 Тест на уровень")],
        [KeyboardButton(text="❌ Выйти в меню")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите нужную опцию на панели..."
)

def level_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for lvl in LEVELS:
        row.append(InlineKeyboardButton(text=lvl, callback_data=f"setlevel_{lvl}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ============= ПРОМПТ ДЛЯ ИИ =============
def system_instruction(level: str) -> str:
    return f"""
Ты — лаконичный, дружелюбный ИИ-преподаватель английского языка.
Ученик сейчас на уровне {level} (по шкале CEFR: A1-C2). Всегда подстраивай сложность языка под этот уровень.

1. Когда ученик просит слова, выведи СТРОГО список из 10 одиночных слов (не фразы и не идиомы), подходящих для уровня {level}. Для каждого слова дай транскрипцию, перевод на русский и короткий живой пример.
2. Если ученик делает грамматическую ошибку, вежливо покажи правильный вариант жирным шрифтом, объясни правило одной строкой на русском и задай короткий встречный вопрос на английском.
3. Не используй слова и конструкции сильно выше уровня {level}.
4. Отвечай по делу, без длинных вступлений.
"""

async def ask_gemini(prompt: str, level: str) -> str:
    try:
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'system_instruction': system_instruction(level),
                'temperature': 0.3
            }
        )
        return response.text if response.text else "⚠️ Нейросеть вернула пустой ответ. Повтори запрос."
    except Exception as e:
        logger.error(f"Ошибка Gemini API: {e}")
        return "⚠️ Ошибка связи с ИИ. Проверь, что GEMINI_API_KEY указан и активен."

# ============= КОМАНДЫ =============
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я твой ИИ-репетитор английского языка.\n\n"
        "Сначала выбери свой уровень:",
        reply_markup=level_keyboard()
    )

@dp.message(F.text == "❌ Выйти в меню")
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Возврат в главное меню.", reply_markup=main_menu)

# ============= ВЫБОР УРОВНЯ =============
@dp.message(F.text == "🎯 Мой уровень")
async def show_level_menu(message: Message):
    level = await get_user_level(message.from_user.id)
    await message.answer(
        f"Твой текущий уровень: <b>{level}</b>\n\nВыбери новый уровень, если хочешь его сменить:",
        reply_markup=level_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("setlevel_"))
async def process_set_level(callback: CallbackQuery, state: FSMContext):
    level = callback.data.split("_", 1)[1]
    await ensure_user(callback.from_user.id)
    await set_user_level(callback.from_user.id, level)
    await state.clear()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ Уровень установлен: <b>{level}</b>\n\n"
        "Теперь выбери, чем хочешь заняться:",
        reply_markup=main_menu,
        parse_mode="HTML"
    )
    await callback.answer()

# ============= МОДУЛЬ СЛОВ =============
@dp.message(F.text == "📚 Учить слова (50 в день)")
async def mode_vocab(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id)
    await track_time(message.from_user.id)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT level, daily_words_count FROM users WHERE user_id = ?",
            (message.from_user.id,)
        ) as cursor:
            res = await cursor.fetchone()
    user_level, daily_count = res if res else ("A1", 0)

    if daily_count >= 50:
        await message.answer(
            "🎉 Ты уже выполнил дневную норму в 50 слов!\n"
            "Новая порция откроется завтра. Отдыхай! 🙌"
        )
        return

    current_step = (daily_count // 10) + 1
    msg = await message.answer(
        f"🔄 Генерирую слова для уровня <b>{user_level}</b> (блок {current_step} из 5)...",
        parse_mode="HTML"
    )

    prompt = f"Дай список из ровно 10 полезных ОДИНОЧНЫХ слов для уровня {user_level}. Для каждого: транскрипция, перевод, короткий пример."
    ai_response = await ask_gemini(prompt, user_level)

    try:
        await msg.delete()
    except Exception:
        pass

    kb_confirm = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Я выучил эти 10 слов ({current_step}/5)", callback_data="confirm_step")]
    ])
    await message.answer(ai_response, reply_markup=kb_confirm)

@dp.callback_query(F.data == "confirm_step")
async def process_confirm_step(callback: CallbackQuery):
    await ensure_user(callback.from_user.id)
    await track_time(callback.from_user.id)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET words_learned = words_learned + 10, daily_words_count = daily_words_count + 10 WHERE user_id = ?",
            (callback.from_user.id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT daily_words_count, level FROM users WHERE user_id = ?",
            (callback.from_user.id,)
        ) as cursor:
            res = await cursor.fetchone()
    daily_count, user_level = res if res else (0, "A1")

    await callback.message.delete()

    if daily_count >= 50:
        await callback.message.answer(
            "🏆 Дневная норма в 50 слов выполнена! Новые слова — завтра. 🚀"
        )
    else:
        current_step = (daily_count // 10) + 1
        await callback.message.answer(
            f"✅ Блок {current_step - 1} из 5 выучен.\n"
            f"Прогресс: <b>{daily_count}/50 слов</b> (уровень {user_level}).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📚 Получить блок {current_step} из 5", callback_data="next_block")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "next_block")
async def process_next_block(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    fake_message = callback.message
    fake_message.from_user = callback.from_user
    await mode_vocab(fake_message, state)
    await callback.answer()

# ============= РАЗГОВОРНЫЙ ЧАТ =============
@dp.message(F.text == "💬 Разговорный чат")
async def mode_chat(message: Message, state: FSMContext):
    await ensure_user(message.from_user.id)
    level = await get_user_level(message.from_user.id)
    await state.set_state(BotStates.chatting)
    await message.answer(
        f"💬 Режим разговора включен (уровень {level}).\n"
        "Пиши мне на английском, я буду отвечать и мягко исправлять ошибки.\n\n"
        "Нажми «❌ Выйти в меню», чтобы закончить.",
        reply_markup=main_menu
    )

@dp.message(BotStates.chatting)
async def handle_chat(message: Message):
    await track_time(message.from_user.id)
    level = await get_user_level(message.from_user.id)
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_gemini(message.text, level)
    await message.answer(reply, parse_mode="HTML")

# ============= ГРАММАТИКА =============
@dp.message(F.text == "📖 Грамматика")
async def mode_grammar(message: Message, state: FSMContext):
    await ensure_user(message.from_user.id)
    level = await get_user_level(message.from_user.id)
    await state.set_state(BotStates.grammar)
    await message.answer(
        f"📖 Режим грамматики (уровень {level}).\n"
        "Напиши тему (например: Present Simple) или пришли предложение — я проверю и объясню.",
        reply_markup=main_menu
    )

@dp.message(BotStates.grammar)
async def handle_grammar(message: Message):
    level = await get_user_level(message.from_user.id)
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Объясни грамматическую тему или проверь предложение ученика уровня {level}: {message.text}"
    reply = await ask_gemini(prompt, level)
    await message.answer(reply, parse_mode="HTML")

# ============= АНАЛИТИКА =============
@dp.message(F.text == "📊 Аналитика")
async def show_analytics(message: Message):
    await ensure_user(message.from_user.id)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT level, words_learned, total_seconds_spent, daily_words_count FROM users WHERE user_id = ?",
            (message.from_user.id,)
        ) as cursor:
            res = await cursor.fetchone()

    if not res:
        await message.answer("Данных пока нет, начни обучение! 🚀")
        return

    level, words_learned, seconds_spent, daily_count = res
    minutes = seconds_spent // 60

    await message.answer(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"🎯 Уровень: {level}\n"
        f"📚 Всего слов выучено: {words_learned}\n"
        f"📅 Сегодня: {daily_count}/50 слов\n"
        f"⏱ Время в обучении: {minutes} мин.",
        parse_mode="HTML"
    )

# ============= ТЕСТ НА УРОВЕНЬ =============
@dp.message(F.text == "📝 Тест на уровень")
async def start_level_test(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📝 Короткий тест поможет определить твой примерный уровень.\n"
        "Напиши пару предложений о себе на английском (кто ты, чем занимаешься, что любишь) — я оценю уровень и предложу его установить."
    )
    await state.set_state(BotStates.chatting)
    await message.answer("Готов? Пиши ✍️")

# ============= ЗАПУСК =============
async def main():
    await init_db()

    from aiohttp import web
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Status: Active", content_type="text/plain"))

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
