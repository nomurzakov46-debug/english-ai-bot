import os
import asyncio
import logging
from dotenv import load_dotenv
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
load_dotenv(dotenv_path="api.env")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY)

DB_NAME = "academy_english.db"

# ============= УРОВНИ И ТЕСТЫ =============
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Вопросы для теста на уровень (начиная с A1, повышая сложность)
LEVEL_TEST_QUESTIONS = [
    # A1 вопросы
    {
        "level": "A1",
        "question": "Выбери правильный ответ:\n\n'She ___ a teacher.'",
        "options": ["am", "is", "are", "be"],
        "correct": 1,  # is
        "explanation": "С 'She' (она) используется 'is'"
    },
    {
        "level": "A1",
        "question": "Выбери правильный ответ:\n\n'I ___ to school every day.'",
        "options": ["go", "goes", "going", "went"],
        "correct": 0,  # go
        "explanation": "С 'I' используется 'go' (Present Simple)"
    },
    {
        "level": "A1",
        "question": "Что означает слово 'book'?",
        "options": ["книга", "кресло", "таблица", "окно"],
        "correct": 0,
        "explanation": "'Book' = книга"
    },
    {
        "level": "A1",
        "question": "Выбери правильный вопрос:",
        "options": ["Do you like coffee?", "You like coffee?", "Do like you coffee?", "You do like coffee?"],
        "correct": 0,
        "explanation": "Вопрос в Present Simple: Do + you + глагол"
    },
    # A2 вопросы
    {
        "level": "A2",
        "question": "Выбери правильный ответ:\n\n'They ___ been here for 2 hours.'",
        "options": ["have", "has", "had", "are"],
        "correct": 0,  # have
        "explanation": "Present Perfect: have/has + been. С 'they' → have"
    },
    {
        "level": "A2",
        "question": "Выбери правильный ответ:\n\n'I ___ to Paris last year.'",
        "options": ["go", "went", "have gone", "am going"],
        "correct": 1,  # went
        "explanation": "'Last year' указывает на Past Simple → went"
    },
    {
        "level": "A2",
        "question": "Что означает 'difficult'?",
        "options": ["трудный, сложный", "интересный", "важный", "разные"],
        "correct": 0,
        "explanation": "'Difficult' = сложный, трудный"
    },
    # B1 вопросы
    {
        "level": "B1",
        "question": "Выбери правильный ответ:\n\n'If I _____ rich, I would travel the world.'",
        "options": ["was", "were", "am", "had been"],
        "correct": 1,  # were
        "explanation": "Conditional (2nd): If + Past Simple (were для 'I')"
    },
    {
        "level": "B1",
        "question": "Выбери правильный ответ:\n\n'She has been working here _____ five years.'",
        "options": ["since", "for", "during", "while"],
        "correct": 1,  # for
        "explanation": "'For' используется с периодами времени (five years)"
    },
    {
        "level": "B1",
        "question": "Выбери правильный ответ:\n\n'The book _____ by Shakespeare.'",
        "options": ["was written", "were written", "is written", "was write"],
        "correct": 0,  # was written
        "explanation": "Passive Voice Past: was + written"
    },
    # B2 вопросы
    {
        "level": "B2",
        "question": "Выбери правильный ответ:\n\n'By the time you arrive, I _____ dinner.'",
        "options": ["will finish", "will have finished", "finish", "have finished"],
        "correct": 1,  # will have finished
        "explanation": "Future Perfect: will have + finished"
    },
    {
        "level": "B2",
        "question": "Выбери правильный ответ:\n\n'She spoke as if she _____ the situation before.'",
        "options": ["had encountered", "has encountered", "encountered", "was encountering"],
        "correct": 0,  # had encountered
        "explanation": "Past Perfect для действия ДО другого действия в прошлом"
    },
]

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
                last_learned_date TEXT DEFAULT '',
                test_score INTEGER DEFAULT 0
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
    testing = State()
    test_answering = State()

# ============= КЛАВИАТУРЫ =============
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Учить слова (50 в день)"), KeyboardButton(text="💬 Разговор")],
        [KeyboardButton(text="📖 Грамматика"), KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="🎯 Мой уровень"), KeyboardButton(text="📝 Пройти тест")],
        [KeyboardButton(text="❌ Выход")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери опцию ↓"
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

def get_progress_bar(current: int, total: int) -> str:
    """Красивый прогресс-бар"""
    filled = int((current / total) * 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty

# ============= ПРОМПТ ДЛЯ ИИ =============
def system_instruction(level: str) -> str:
    return f"""
Ты — дружелюбный, профессиональный ИИ-преподаватель английского.
Ученик на уровне {level} (CEFR). Подстраивай язык под этот уровень.

Правила:
1. СЛОВА: 10 одиночных слов. Для каждого: транскрипция, перевод, пример.
2. ОШИБКИ: Мягко показывай правильный вариант **жирным**, объясняй правило 1 строкой, задай вопрос на английском.
3. ЯЗЫК: Не используй сложные конструкции выше уровня {level}.
4. СТИЛЬ: Ответы по делу, без воды.
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
        return response.text if response.text else "⚠️ ИИ вернул пустой ответ. Повтори."
    except Exception as e:
        logger.error(f"Ошибка Gemini: {e}")
        return "⚠️ Ошибка связи. Проверь GEMINI_API_KEY или попробуй позже."

# ============= КОМАНДЫ =============
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id)
    
    first_name = message.from_user.first_name or "Друже"
    await message.answer(
        f"👋 <b>Привет, {first_name}!</b>\n\n"
        f"🎓 Я твой персональный <b>ИИ-репетитор английского</b>.\n\n"
        f"<b>Что я умею:</b>\n"
        f"📚 Учить слова (50 в день)\n"
        f"💬 Вести разговоры\n"
        f"📖 Объяснять грамматику\n"
        f"📊 Отслеживать прогресс\n\n"
        f"<b>Сначала выбери свой уровень:</b>",
        reply_markup=level_keyboard(),
        parse_mode="HTML"
    )

@dp.message(F.text == "❌ Выход")
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>До свидания!</b>\n\nВернуться: /start",
        reply_markup=main_menu,
        parse_mode="HTML"
    )

# ============= ВЫБОР УРОВНЯ =============
@dp.message(F.text == "🎯 Мой уровень")
async def show_level_menu(message: Message):
    level = await get_user_level(message.from_user.id)
    await message.answer(
        f"<b>🎯 Твой текущий уровень:</b> <u>{level}</u>\n\n"
        f"<b>Выбери новый уровень:</b>",
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
        f"✅ <b>Уровень установлен!</b>\n\n"
        f"📌 Твой уровень: <u><b>{level}</b></u>\n\n"
        f"Теперь ты готов начать обучение! 🚀",
        reply_markup=main_menu,
        parse_mode="HTML"
    )
    await callback.answer()

# ============= УМНЫЙ ТЕСТ НА УРОВЕНЬ =============
@dp.message(F.text == "📝 Пройти тест")
async def start_level_test(message: Message, state: FSMContext):
    await ensure_user(message.from_user.id)
    await state.set_state(BotStates.testing)
    
    context_data = {
        "test_index": 0,
        "correct_answers": 0,
        "current_level": "A1"
    }
    await state.update_data(**context_data)

    await message.answer(
        "📝 <b>ТЕСТ НА ОПРЕДЕЛЕНИЕ УРОВНЯ</b>\n\n"
        "🎯 Я буду задавать вопросы, начиная с A1.\n"
        "📈 Сложность будет расти постепенно.\n"
        "✅ Ответь правильно → сложнее\n"
        "❌ Ошибка → помогу и предложу уровень\n\n"
        "<b>Готов? Начнём! 👇</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать тест", callback_data="start_test")]
        ])
    )

@dp.callback_query(F.data == "start_test")
async def begin_test(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    test_index = data.get("test_index", 0)
    
    if test_index >= len(LEVEL_TEST_QUESTIONS):
        await callback.message.delete()
        await finalize_test(callback.message, state)
        return

    question_data = LEVEL_TEST_QUESTIONS[test_index]
    level = question_data["level"]
    question = question_data["question"]
    options = question_data["options"]

    # Красивый вывод теста
    test_num = test_index + 1
    progress = get_progress_bar(test_index, len(LEVEL_TEST_QUESTIONS))
    
    kb_rows = [
        [InlineKeyboardButton(text=f"{i+1}️⃣ {opt}", callback_data=f"test_answer_{i}")]
        for i, opt in enumerate(options)
    ]
    kb_rows.append([InlineKeyboardButton(text="😕 Я не знаю / Сдаюсь", callback_data="test_give_up")])
    
    msg_text = (
        f"<b>Вопрос {test_num}/{len(LEVEL_TEST_QUESTIONS)}</b> "
        f"<code>{progress}</code>\n\n"
        f"<b>Уровень: {level}</b>\n\n"
        f"{question}\n\n"
        f"<b>Выбери ответ:</b>"
    )
    
    await callback.message.delete()
    await callback.message.answer(msg_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("test_answer_"))
async def process_test_answer(callback: CallbackQuery, state: FSMContext):
    user_answer = int(callback.data.split("_")[-1])
    data = await state.get_data()
    test_index = data.get("test_index", 0)
    correct_answers = data.get("correct_answers", 0)

    question_data = LEVEL_TEST_QUESTIONS[test_index]
    correct_option = question_data["correct"]
    explanation = question_data["explanation"]

    if user_answer == correct_option:
        correct_answers += 1
        response = "✅ <b>Верно!</b>"
        emoji = "🎉"
    else:
        correct_answer_text = question_data["options"][correct_option]
        response = f"❌ <b>Не совсем.</b>\n\n💡 Правильный ответ: <u>{correct_answer_text}</u>\n📚 {explanation}"
        emoji = "💪"

    await callback.message.delete()
    await callback.message.answer(f"{emoji} {response}", parse_mode="HTML")

    # Переход к следующему вопросу
    await state.update_data(test_index=test_index + 1, correct_answers=correct_answers)
    
    await asyncio.sleep(1)
    
    if test_index + 1 >= len(LEVEL_TEST_QUESTIONS):
        await finalize_test(callback.message, state)
    else:
        next_msg = await callback.message.answer("⏳ Следующий вопрос...")
        await asyncio.sleep(0.5)
        
        next_question = LEVEL_TEST_QUESTIONS[test_index + 1]
        next_level = next_question["level"]
        next_text = next_question["question"]
        next_options = next_question["options"]
        
        kb_rows = [
            [InlineKeyboardButton(text=f"{i+1}️⃣ {opt}", callback_data=f"test_answer_{i}")]
            for i, opt in enumerate(next_options)
        ]
        kb_rows.append([InlineKeyboardButton(text="😕 Я не знаю", callback_data="test_give_up")])
        
        test_num = test_index + 2
        progress = get_progress_bar(test_index + 1, len(LEVEL_TEST_QUESTIONS))
        
        msg_text = (
            f"<b>Вопрос {test_num}/{len(LEVEL_TEST_QUESTIONS)}</b> "
            f"<code>{progress}</code>\n\n"
            f"<b>Уровень: {next_level}</b>\n\n"
            f"{next_text}\n\n"
            f"<b>Выбери ответ:</b>"
        )
        
        await next_msg.delete()
        await callback.message.answer(msg_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")

@dp.callback_query(F.data == "test_give_up")
async def give_up_test(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    test_index = data.get("test_index", 0)
    correct_answers = data.get("correct_answers", 0)
    
    question_data = LEVEL_TEST_QUESTIONS[test_index]
    current_level = question_data["level"]
    
    await callback.message.delete()
    await callback.message.answer(f"😊 Ничего страшного! Твой уровень: <b>{current_level}</b>", parse_mode="HTML")
    
    await ensure_user(callback.from_user.id)
    await set_user_level(callback.from_user.id, current_level)
    await state.clear()
    
    await callback.message.answer(
        f"✅ Уровень установлен на <b>{current_level}</b>.\n\n"
        "Теперь ты готов учиться! 🚀",
        reply_markup=main_menu,
        parse_mode="HTML"
    )
    await callback.answer()

async def finalize_test(message: Message, state: FSMContext):
    data = await state.get_data()
    correct_answers = data.get("correct_answers", 0)
    total = len(LEVEL_TEST_QUESTIONS)
    percentage = (correct_answers / total) * 100

    # Определяем уровень по результатам
    if percentage >= 80:
        determined_level = "C2"
    elif percentage >= 70:
        determined_level = "C1"
    elif percentage >= 60:
        determined_level = "B2"
    elif percentage >= 50:
        determined_level = "B1"
    elif percentage >= 40:
        determined_level = "A2"
    else:
        determined_level = "A1"

    progress_bar = get_progress_bar(correct_answers, total)

    result_msg = (
        f"🏆 <b>РЕЗУЛЬТАТЫ ТЕСТА</b>\n\n"
        f"✅ Правильно: {correct_answers}/{total}\n"
        f"📊 Результат: {percentage:.0f}%\n"
        f"<code>{progress_bar}</code>\n\n"
        f"🎯 <b>Определённый уровень: {determined_level}</b>\n\n"
        f"Это хороший результат! Давай учиться! 🚀"
    )

    await message.answer(result_msg, parse_mode="HTML")

    await ensure_user(message.from_user.id)
    await set_user_level(message.from_user.id, determined_level)
    await state.clear()

    await message.answer(
        f"Уровень установлен на <b>{determined_level}</b>",
        reply_markup=main_menu,
        parse_mode="HTML"
    )

# ============= МОДУЛЬ СЛОВ =============

# 1. Выносим всю логику генерации слов в отдельную функцию, независимую от типов Message/CallbackQuery
async def generate_and_send_vocab_block(user_id: int, target_chat_id: int, state: FSMContext, bot_or_message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT level, daily_words_count FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            res = await cursor.fetchone()
    user_level, daily_count = res if res else ("A1", 0)

    if daily_count >= 50:
        await bot_or_message.answer(
            f"🎉 <b>Отличная работа!</b>\n\n"
            f"Ты уже выучил <u>50 слов</u> сегодня.\n"
            f"Новая порция откроется завтра! 😴",
            parse_mode="HTML"
        )
        return

    current_step = (daily_count // 10) + 1
    msg = await bot_or_message.answer(
        f"🔄 <b>Генерирую слова...</b>\n\n"
        f"📚 Уровень: <u>{user_level}</u>\n"
        f"📍 Блок: {current_step}/5",
        parse_mode="HTML"
    )

    prompt = f"Дай список из ровно 10 ОДИНОЧНЫХ слов для уровня {user_level}. Для каждого: транскрипция, перевод, пример."
    ai_response = await ask_gemini(prompt, user_level)

    try:
        await msg.delete()
    except Exception:
        pass

    kb_confirm = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Выучил! ({current_step}/5)", callback_data="confirm_step")]
    ])
    await bot_or_message.answer(
        f"<b>📚 Блок {current_step} из 5</b>\n\n{ai_response}",
        reply_markup=kb_confirm,
        parse_mode="HTML"
    )


# 2. Хендлер на кнопку из главного меню
@dp.message(F.text == "📚 Учить слова (50 в день)")
async def mode_vocab(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user.id)
    await track_time(message.from_user.id)
    
    # Просто вызываем нашу общую функцию
    await generate_and_send_vocab_block(message.from_user.id, message.chat.id, state, message)


# 3. Хендлер подтверждения шага
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
            f"🏆 <b>ДНЕВНАЯ НОРМА ВЫПОЛНЕНА!</b>\n\n"
            f"50 слов → 📚 Отличный результат!\n\n"
            f"Завтра: новые слова 🚀",
            parse_mode="HTML"
        )
    else:
        current_step = (daily_count // 10) + 1
        progress_bar = get_progress_bar(daily_count, 50)
        
        await callback.message.answer(
            f"✅ <b>Блок выучен!</b>\n\n"
            f"<code>{progress_bar}</code>\n"
            f"{daily_count}/50 слов (уровень {user_level})",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📚 Блок {current_step}/5", callback_data="next_block")]
            ])
        )
    await callback.answer()


# 4. Хендлер переходов на следующий блок (ЗДЕСЬ БОЛЬШЕ НЕТ КОПИРОВАНИЯ ОБЪЕКТОВ)
@dp.callback_query(F.data == "next_block")
async def process_next_block(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    
    # Прямо передаем ID пользователя из колбэка и сам объект callback для отправки сообщений
    await generate_and_send_vocab_block(callback.from_user.id, callback.message.chat.id, state, callback)
    await callback.answer()


# ============= РАЗГОВОРНЫЙ ЧАТ =============
@dp.message(F.text == "💬 Разговор")
async def mode_chat(message: Message, state: FSMContext):
    await ensure_user(message.from_user.id)
    level = await get_user_level(message.from_user.id)
    await state.set_state(BotStates.chatting)
    await message.answer(
        f"💬 <b>РЕЖИМ РАЗГОВОРА ВКЛЮЧЕН</b>\n\n"
        f"🎯 Уровень: <u>{level}</u>\n\n"
        f"Пиши мне на английском, я буду отвечать и мягко исправлять твои ошибки. 💪",
        reply_markup=main_menu,
        parse_mode="HTML"
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
        f"📖 <b>РЕЖИМ ГРАММАТИКИ</b>\n\n"
        f"🎯 Уровень: <u>{level}</u>\n\n"
        f"<b>Напиши:</b>\n"
        f"• Тему (Present Simple)\n"
        f"• Или фразу для проверки",
        reply_markup=main_menu,
        parse_mode="HTML"
    )

@dp.message(BotStates.grammar)
async def handle_grammar(message: Message):
    level = await get_user_level(message.from_user.id)
    await bot.send_chat_action(message.chat.id, "typing")
    prompt = f"Объясни грамматику или проверь предложение ученика уровня {level}: {message.text}"
    reply = await ask_gemini(prompt, level)
    await message.answer(reply, parse_mode="HTML")

# ============= АНАЛИТИКА =============
@dp.message(F.text == "📊 Аналитика")
async def show_analytics(message: Message):
    await ensure_user(message.from_user.id)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT level, words_learned, total_seconds_spent, daily_words_count, joined_date FROM users WHERE user_id = ?",
            (message.from_user.id,)
        ) as cursor:
            res = await cursor.fetchone()

    if not res:
        await message.answer("📊 Данных пока нет. Начни обучение! 🚀")
        return

    level, words_learned, seconds_spent, daily_count, joined_date = res
    minutes = seconds_spent // 60
    hours = minutes // 60
    time_str = f"{hours}ч {minutes%60}мин" if hours > 0 else f"{minutes}мин"
    
    progress_bar = get_progress_bar(daily_count, 50)

    msg = (
        f"<b>📊 ТВОЯ СТАТИСТИКА</b>\n\n"
        f"<b>Уровень:</b> <u>{level}</u>\n"
        f"<b>Всего слов:</b> {words_learned} 📚\n"
        f"<b>Время учёбы:</b> {time_str} ⏱\n\n"
        f"<b>📅 Сегодня:</b>\n"
        f"<code>{progress_bar}</code>\n"
        f"{daily_count}/50 слов\n\n"
        f"<b>Дата регистрации:</b> {joined_date}"
    )

    await message.answer(msg, parse_mode="HTML")

# ============= ЗАПУСК =============
async def main():
    await init_db()

    from aiohttp import web
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Status: Active ✅", content_type="text/plain"))

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
