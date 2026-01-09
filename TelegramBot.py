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

# импортируем всю логику работы с API и форматированием
from main import (
    schedule_get,
    convert_schedule_to_markdown,
    get_current_week_range,
    get_leader_group,
    get_leader_stream,
    create_leader_group_markdown,
    convert_leader_stream_to_markdown,
    escape_for_markdown_v2,
    save_json_to_file,
    get_future_exams,
    convert_exams_to_markdown,
    get_auth_token
)

# импортируем работу с БД аккаунтов
from main import (
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

# подгружаем переменные окружения (.env)
load_dotenv()

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    # без токена бот просто не запустится
    raise ValueError("Токен бота не найден. Проверьте файл .env")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# папки, куда сохраняем json и markdown (для отладки и истории)
JSON_FOLDER = "project/JsonOut"
MD_FOLDER = "project/MdOut"

os.makedirs(JSON_FOLDER, exist_ok=True)
os.makedirs(MD_FOLDER, exist_ok=True)

from aiogram.fsm.state import State, StatesGroup

# состояния для логина
class Form(StatesGroup):
    username = State()
    password = State()

# состояния для управления аккаунтами
class AccountManagement(StatesGroup):
    choosing_account = State()
    deleting_account = State()

# клавиатура для первого входа
login_markup = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Войти 🚀")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# основное меню
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

# подменю «Главная»
main_submenu_markup = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Студенты группы 👥"), KeyboardButton(text="Топ 3 в потоке 🏆")],
        [KeyboardButton(text="Будущие экзамены 📚")],
        [KeyboardButton(text="Назад")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    # если аккаунты уже есть — сразу в меню
    user_id = message.from_user.id
    if has_accounts(user_id):
        await message.answer("Привет! Что будем делать?", reply_markup=main_markup)
    else:
        # иначе просим войти
        await message.answer(
            "Привет! Я бот для просмотра расписания.\n"
            "Чтобы начать, нужно войти в журнал.",
            reply_markup=login_markup
        )

@dp.message(lambda message: message.text == "Войти 🚀")
async def process_login_button(message: types.Message, state: MemoryStorage):
    # начинаем процесс логина
    await message.answer(
        "Введите <b>логин</b> от журнала:",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Form.username)

@dp.message(Form.username)
async def process_username(message: types.Message, state: MemoryStorage):
    # сохраняем логин и просим пароль
    await state.update_data(username=message.text)
    await message.answer(
        "Теперь введите <b>пароль</b>:",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Form.password)

@dp.message(Form.password)
async def process_password(message: types.Message, state: MemoryStorage):
    # пробуем авторизоваться
    user_data = await state.get_data()
    username = user_data['username']
    password = message.text
    user_id = message.from_user.id

    await message.answer(
        "Проверяю данные, подождите немного...",
        reply_markup=ReplyKeyboardRemove()
    )

    try:
        token = await get_auth_token(username, password)
        add_account(user_id, username, token)

        await message.answer(
            "🎉 Аккаунт успешно добавлен!",
            parse_mode=ParseMode.HTML
        )
        await message.answer(
            "Что дальше?",
            reply_markup=main_markup
        )
        await state.clear()

    except Exception as e:
        error_message = str(e)
        logging.error(f"Ошибка авторизации: {error_message}")

        if "Неверный логин или пароль" in error_message:
            # если просто ошибся — даём попробовать ещё раз
            await message.answer(
                "😔 Неверный логин или пароль.\n"
                "Введите <b>логин</b> ещё раз:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(Form.username)
        else:
            await message.answer(
                "Произошла ошибка. Попробуйте позже или напишите в поддержку: @Liebe_Rin\n\n"
                f"Ошибка: {error_message}",
                reply_markup=main_markup
            )
            await state.clear()

@dp.message(lambda message: message.text == "Главная", StateFilter(None))
async def show_main_submenu(message: types.Message):
    # подменю с лидерами и экзаменами
    if has_accounts(message.from_user.id):
        await message.answer("Выберите действие:", reply_markup=main_submenu_markup)
    else:
        await message.answer("Сначала нужно войти.", reply_markup=login_markup)

@dp.message(lambda message: message.text == "Назад", StateFilter(None))
async def show_main_menu_from_submenu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_markup)

@dp.message(lambda message: message.text == "Управление аккаунтами ⚙️", StateFilter(None))
async def manage_accounts(message: types.Message, state: MemoryStorage):
    # меню управления аккаунтами
    user_id = message.from_user.id
    accounts = get_all_accounts(user_id)

    if not accounts:
        await message.answer(
            "Аккаунтов пока нет.",
            reply_markup=login_markup
        )
        return

    keyboard_buttons = []
    for username, is_active in accounts:
        text = f"✅ {username}" if is_active else username
        keyboard_buttons.append([KeyboardButton(text=text)])

    keyboard_buttons.append([KeyboardButton(text="Добавить новый аккаунт ➕")])
    keyboard_buttons.append([KeyboardButton(text="Удалить аккаунт 🗑️")])
    keyboard_buttons.append([KeyboardButton(text="Назад")])

    markup = ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        "Выберите аккаунт или действие:",
        reply_markup=markup
    )
    await state.set_state(AccountManagement.choosing_account)

@dp.message(AccountManagement.choosing_account)
async def process_account_choice(message: types.Message, state: MemoryStorage):
    # обработка выбора в управлении аккаунтами
    user_id = message.from_user.id
    text = message.text

    if text == "Добавить новый аккаунт ➕":
        await message.answer(
            "Введите логин нового аккаунта:",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(Form.username)

    elif text == "Удалить аккаунт 🗑️":
        accounts = get_all_accounts(user_id)
        keyboard_buttons = [[KeyboardButton(text=u)] for u, _ in accounts]
        keyboard_buttons.append([KeyboardButton(text="Отмена")])

        markup = ReplyKeyboardMarkup(
            keyboard=keyboard_buttons,
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            "Выберите аккаунт для удаления:",
            reply_markup=markup
        )
        await state.set_state(AccountManagement.deleting_account)

    elif text == "Назад":
        await message.answer("Главное меню:", reply_markup=main_markup)
        await state.clear()

    else:
        # делаем выбранный аккаунт активным
        username = re.sub(r"✅ (.*)", r"\1", text)
        set_active_account(user_id, username)
        await message.answer(
            f"Аккаунт <b>{username}</b> теперь активен",
            parse_mode=ParseMode.HTML,
            reply_markup=main_markup
        )
        await state.clear()

@dp.message(AccountManagement.deleting_account)
async def process_delete_account(message: types.Message, state: MemoryStorage):
    # удаление аккаунта
    user_id = message.from_user.id
    username_to_delete = message.text

    if username_to_delete != "Отмена":
        delete_account(user_id, username_to_delete)

    await message.answer(
        "Готово.",
        reply_markup=main_markup
    )
    await state.clear()

@dp.message(lambda message: message.text == "Получить расписание 📆", StateFilter(None))
async def get_schedule_button(message: types.Message):
    # основной функционал — расписание
    credentials = get_active_account(message.from_user.id)

    if credentials:
        _, token = credentials
        await message.answer("Получаю расписание...")
        await get_user_schedule(message, token)
    else:
        await message.answer("Сначала нужно войти.", reply_markup=login_markup)

async def get_user_schedule(message: types.Message, token: str):
    # получаем и отправляем расписание за текущую неделю
    start_of_week, end_of_week, _ = get_current_week_range()
    user_id = message.from_user.id

    try:
        schedule_json = await schedule_get(start_of_week, end_of_week, token)

        json_file_path = os.path.join(JSON_FOLDER, f"schedule_{user_id}.json")
        save_json_to_file(schedule_json, json_file_path)

        markdown_text = convert_schedule_to_markdown(schedule_json)
        await message.answer(
            markdown_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=main_markup
        )

    except Exception as e:
        await handle_api_error(message, user_id, str(e))

async def handle_api_error(message: types.Message, user_id: int, error_message: str):
    # единая обработка ошибок API
    logging.error(f"Ошибка API для {user_id}: {error_message}")

    await message.answer(
        "Произошла ошибка. Попробуйте позже или напишите в поддержку: @Liebe_Rin",
        reply_markup=main_markup
    )

async def main():
    # инициализация БД и запуск бота
    init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())