import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import asyncio
import os
from dotenv import load_dotenv
import re
from aiogram.enums import ParseMode

from main import (
    schedule_get,
    convert_schedule_to_markdown,
    get_current_week_range,
    get_leader_group,
    get_leader_stream,
    create_leader_group_markdown,
    convert_leader_stream_to_markdown,
    escape_for_markdown_v2,
    get_future_exams,
    convert_exams_to_markdown,
    get_auth_token,
    init_db,
    add_account,
    get_active_account,
    has_accounts,
    get_all_accounts,
    set_active_account,
    delete_account,
    delete_all_accounts
)

logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Токен бота не найден. Убедитесь, что он указан в файле .env")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

JSON_FOLDER = "project/JsonOut"
MD_FOLDER = "project/MdOut"
os.makedirs(JSON_FOLDER, exist_ok=True)
os.makedirs(MD_FOLDER, exist_ok=True)

from aiogram.fsm.state import State, StatesGroup

# --- Состояния ---
class Form(StatesGroup):
    username = State()
    password = State()

class AccountManagement(StatesGroup):
    choosing_account = State()
    deleting_account = State()

# --- Клавиатуры ---
login_markup = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Войти 🚀")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

main_markup = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Получить расписание 📆")],
        [KeyboardButton(text="Главная")],
        [KeyboardButton(text="Управление аккаунтами ⚙️")],
        [KeyboardButton(text="Выйти 🚪")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

main_submenu_markup = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Студенты группы 👥"), KeyboardButton(text="Топ 3 в потоке 🏆")],
        [KeyboardButton(text="Будущие экзамены 📚")],
        [KeyboardButton(text="Назад")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# --- Функции для автоудаления файлов ---
async def delete_file_later(file_path: str, delay_seconds: int = 1_209_600):
    """Удаляет файл через delay_seconds секунд (по умолчанию 2 недели)."""
    await asyncio.sleep(delay_seconds)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Файл {file_path} удален автоматически")
    except Exception as e:
        print(f"Ошибка при удалении файла {file_path}: {e}")

def save_json_to_file(json_data: dict, file_path: str):
    import json
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
        print(f"JSON-файл {file_path} создан.")
        asyncio.create_task(delete_file_later(file_path))  # автоудаление через 2 недели
    except Exception as e:
        print(f"Ошибка при сохранении JSON: {e}")

def save_md_file(markdown_text: str, file_path: str):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
        print(f"MD-файл {file_path} создан.")
        asyncio.create_task(delete_file_later(file_path))  # автоудаление через 2 недели
    except Exception as e:
        print(f"Ошибка при сохранении MD: {e}")

# --- Хендлеры ---
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    if has_accounts(user_id):
        await message.answer("Привет! Что ещё могу для вас сделать?", reply_markup=main_markup)
    else:
        await message.answer(
            "Привет! Я твой бот-помощник для расписания. Чтобы получить расписание, "
            "тебе нужно войти в журнал. Нажми кнопку ниже, чтобы начать.",
            reply_markup=login_markup
        )

@dp.message(lambda message: message.text == "Войти 🚀")
async def process_login_button(message: types.Message, state: MemoryStorage):
    await message.answer("Пожалуйста, введите ваш <b>логин</b> от журнала:", parse_mode=ParseMode.HTML)
    await state.set_state(Form.username)

@dp.message(Form.username)
async def process_username(message: types.Message, state: MemoryStorage):
    await state.update_data(username=message.text)
    await message.answer("Отлично! Теперь введите ваш <b>пароль</b>:", parse_mode=ParseMode.HTML)
    await state.set_state(Form.password)

@dp.message(Form.password)
async def process_password(message: types.Message, state: MemoryStorage):
    user_data = await state.get_data()
    username = user_data['username']
    password = message.text
    user_id = message.from_user.id

    await message.answer("Проверяю логин и пароль...", reply_markup=ReplyKeyboardRemove())

    try:
        token = await get_auth_token(username, password)
        add_account(user_id, username, token)
        await message.answer("🎉 Ваши учетные данные успешно сохранены!", parse_mode=ParseMode.HTML)
        await message.answer("Что ещё могу для вас сделать?", reply_markup=main_markup)
        await state.clear()
    except Exception as e:
        error_message = str(e)
        logging.error(f"Ошибка при авторизации: {error_message}")
        if "Неверный логин или пароль" in error_message:
            await message.answer("😔 Неверный логин или пароль. Введите логин:", parse_mode=ParseMode.HTML)
            await state.set_state(Form.username)
        else:
            await message.answer(f"Произошла ошибка: {error_message}", reply_markup=main_markup)
            await state.clear()

# --- Главные меню и подменю ---
@dp.message(lambda message: message.text == "Главная", StateFilter(None))
async def show_main_submenu(message: types.Message):
    user_id = message.from_user.id
    if has_accounts(user_id):
        await message.answer("Выберите действие:", reply_markup=main_submenu_markup)
    else:
        await message.answer("Сначала войдите в аккаунт.", reply_markup=login_markup)

@dp.message(lambda message: message.text == "Назад", StateFilter(None))
async def show_main_menu_from_submenu(message: types.Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_markup)

# --- Получение расписания и файлов ---
async def get_user_schedule(message: types.Message, token: str):
    start_of_week, end_of_week, _ = get_current_week_range()
    user_id = message.from_user.id
    try:
        schedule_json_data = await schedule_get(start_of_week, end_of_week, token)

        json_file_path = os.path.join(JSON_FOLDER, f"schedule_{user_id}.json")
        save_json_to_file(schedule_json_data, json_file_path)

        markdown_text = convert_schedule_to_markdown(schedule_json_data)
        md_file_path = os.path.join(MD_FOLDER, f"schedule_{user_id}.md")
        save_md_file(markdown_text, md_file_path)

        await message.answer(markdown_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_markup)
    except Exception as e:
        await message.answer(f"Ошибка при получении расписания: {e}", reply_markup=main_markup)

@dp.message(lambda message: message.text == "Получить расписание 📆", StateFilter(None))
async def get_schedule_button(message: types.Message):
    user_id = message.from_user.id
    credentials = get_active_account(user_id)
    if credentials:
        _, token = credentials
        await message.answer("Получаю ваше расписание...")
        await get_user_schedule(message, token)
    else:
        await message.answer("Сначала войдите в аккаунт.", reply_markup=login_markup)

# --- Остальные хендлеры (группа, топ-3, экзамены) ---
@dp.message(lambda message: message.text == "Студенты группы 👥", StateFilter(None))
async def get_group_leaders_button(message: types.Message):
    user_id = message.from_user.id
    credentials = get_active_account(user_id)
    if credentials:
        _, token = credentials
        await message.answer("Получаю список студентов группы...")
        try:
            json_data = await get_leader_group(token)
            markdown_text = create_leader_group_markdown(json_data)

            json_file_path = os.path.join(JSON_FOLDER, f"group_leaders_{user_id}.json")
            save_json_to_file(json_data, json_file_path)
            md_file_path = os.path.join(MD_FOLDER, f"group_leaders_{user_id}.md")
            save_md_file(markdown_text, md_file_path)

            await message.answer(markdown_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_submenu_markup)
        except Exception as e:
            await message.answer(f"Ошибка при получении студентов группы: {e}", reply_markup=main_submenu_markup)

@dp.message(lambda message: message.text == "Топ 3 в потоке 🏆", StateFilter(None))
async def get_stream_leaders_button(message: types.Message):
    user_id = message.from_user.id
    credentials = get_active_account(user_id)
    if credentials:
        _, token = credentials
        await message.answer("Получаю топ-3 студентов потока...")
        try:
            json_data = await get_leader_stream(token)
            markdown_text = convert_leader_stream_to_markdown(json_data)

            json_file_path = os.path.join(JSON_FOLDER, f"stream_leaders_{user_id}.json")
            save_json_to_file(json_data, json_file_path)
            md_file_path = os.path.join(MD_FOLDER, f"stream_leaders_{user_id}.md")
            save_md_file(markdown_text, md_file_path)

            await message.answer(markdown_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_submenu_markup)
        except Exception as e:
            await message.answer(f"Ошибка при получении топ-3: {e}", reply_markup=main_submenu_markup)

@dp.message(lambda message: message.text == "Будущие экзамены 📚", StateFilter(None))
async def get_exams_button(message: types.Message):
    user_id = message.from_user.id
    credentials = get_active_account(user_id)
    if credentials:
        _, token = credentials
        await message.answer("Получаю список будущих экзаменов...")
        try:
            json_data = await get_future_exams(token)
            markdown_text = convert_exams_to_markdown(json_data)

            json_file_path = os.path.join(JSON_FOLDER, f"exams_{user_id}.json")
            save_json_to_file(json_data, json_file_path)
            md_file_path = os.path.join(MD_FOLDER, f"exams_{user_id}.md")
            save_md_file(markdown_text, md_file_path)

            await message.answer(markdown_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_submenu_markup)
        except Exception as e:
            await message.answer(f"Ошибка при получении экзаменов: {e}", reply_markup=main_submenu_markup)

# --- Выход ---
@dp.message(lambda message: message.text == "Выйти 🚪", StateFilter(None))
async def logout_button(message: types.Message):
    user_id = message.from_user.id
    delete_all_accounts(user_id)
    await message.answer("Вы вышли из всех аккаунтов.", reply_markup=login_markup)

# --- Запуск бота ---
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
