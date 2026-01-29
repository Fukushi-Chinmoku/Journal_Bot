import httpx
import asyncio
import json
from datetime import datetime, timedelta
from collections import defaultdict
import os
import re
import logging
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from cryptography.fernet import Fernet, InvalidToken
import pymongo

# API
LOGIN_URL = "https://msapi.top-academy.ru/api/v2/auth/login"
SCHEDULE_API_URL = "https://msapi.top-academy.ru/api/v2/schedule/operations/get-by-date-range"
LEADER_STREAM_URL = "https://msapi.top-academy.ru/api/v2/dashboard/progress/leader-stream"
LEADER_GROUP_URL = "https://msapi.top-academy.ru/api/v2/dashboard/progress/leader-group"
FUTURE_EXAMS_URL = "https://msapi.top-academy.ru/api/v2/dashboard/info/future-exams"
APPLICATION_KEY = "6a56a5df2667e65aab73ce76d1dd737f7d1faef9c52e8b8c55ac75f565d8e8a6"

HEADERS = {
    "User-Agent": "Mozilla/5.5 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://journal.top-academy.ru/",
    "Origin": "https://journal.top-academy.ru"
}

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongo:27017/botdb")
MONGODB_DB = os.getenv("MONGODB_DB", "journalbot")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "accounts")
PASSWORD_ENC_KEY = os.getenv("PASSWORD_ENC_KEY")



mongo_client: MongoClient | None = None
accounts_col = None

logging.basicConfig(level=logging.INFO)

def generate_password_enc_key() -> str:
    return Fernet.generate_key().decode("utf-8")

def _get_fernet() -> Fernet | None:
    if not PASSWORD_ENC_KEY:
        return None
    try:
        return Fernet(PASSWORD_ENC_KEY.encode("utf-8"))
    except Exception:
        logging.error("Некорректный PASSWORD_ENC_KEY. Сгенерируйте новый ключ")
        return None

def encrypt_password(password: str) -> str:
    f = _get_fernet()
    if not f:
        raise RuntimeError("PASSWORD_ENC_KEY не задан. Нельзя шифровать пароль")
    return f.encrypt(password.encode("utf-8")).decode("utf-8")

def decrypt_password(token_str: str) -> str:
    f = _get_fernet()
    if not f:
        raise RuntimeError("PASSWORD_ENC_KEY не задан. Нельзя расшифровать пароль")
    try:
        return f.decrypt(token_str.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise RuntimeError("Не удалось расшифровать пароль. Неверный ключ или поврежденные данные")

def init_db():
    # Инициализация MongoDB, коллекция и индексы
    global mongo_client, accounts_col
    try:
        # Таймер на подключение к MongoDB
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        db = mongo_client[MONGODB_DB]
        accounts_col = db[MONGODB_COLLECTION]
        # ping для проверки соединения
        mongo_client.admin.command("ping")
        # уникальность пары (user_id, username)
        accounts_col.create_index([("user_id", 1), ("username", 1)], unique=True)
        logging.info("MongoDB инициализирована (%s / %s)", MONGODB_DB, MONGODB_COLLECTION)
    except PyMongoError as e:
        logging.error("Ошибка при инициализации MongoDB: %s", e)
        raise

def add_account(user_id, username, token):
    # Добавляет/обновляет аккаунт и делает его активным. Пароль не сохраняется
    if accounts_col is None:
        init_db()
    try:
        accounts_col.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
        accounts_col.update_one(
            {"user_id": user_id, "username": username},
            {"$set": {"token": token, "is_active": True}, "$unset": {"password": "", "password_enc": ""}},
            upsert=True,
        )
        logging.info("Аккаунт %s для пользователя %d сохранен (без пароля)", username, user_id)
    except PyMongoError as e:
        logging.error("Ошибка при добавлении аккаунта для пользователя %d: %s", user_id, e)

def add_account_with_password(user_id: int, username: str, password: str, token: str):
    # бновляем аккаунт, сохраняя токен и пароль (для автологина при 401 ведь колледж не выдаст нормальный апи)
    if accounts_col is None:
        init_db()
    try:
        password_enc = encrypt_password(password)
        accounts_col.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
        accounts_col.update_one(
            {"user_id": user_id, "username": username},
            {"$set": {"token": token, "password_enc": password_enc, "is_active": True}, "$unset": {"password": ""}},
            upsert=True,
        )
        logging.info("Аккаунт %s для пользователя %d сохранен (с шифрованным паролем).", username, user_id)
    except DuplicateKeyError:
        logging.warning("Дубликат аккаунта %s для пользователя %d", username, user_id)
    except RuntimeError as e:
        logging.error("%s", e)
        raise
    except PyMongoError as e:
        logging.error("Ошибка при добавлении аккаунта (с паролем) для пользователя %d: %s", user_id, e)

def get_active_account(user_id):
    # Получаем активный аккаунт и его токен для указанного пользователя
    if accounts_col is None:
        init_db()
    try:
        doc = accounts_col.find_one({"user_id": user_id, "is_active": True}, {"username": 1, "token": 1, "_id": 0})
        if doc:
            logging.info("Активный аккаунт для пользователя %d получен из БД", user_id)
            return (doc.get("username"), doc.get("token"))
        return None
    except PyMongoError as e:
        logging.error("Ошибка при получении активного аккаунта для пользователя %d: %s", user_id, e)
        return None

def get_active_account_full(user_id: int):
    # Получаем активный аккаунт (username, token, password)
    if accounts_col is None:
        init_db()
    try:
        doc = accounts_col.find_one(
            {"user_id": user_id, "is_active": True},
            {"username": 1, "token": 1, "password_enc": 1, "password": 1, "_id": 0},
        )
        if doc:
            logging.info("Активный аккаунт для пользователя %d получен из БД", user_id)
            username = doc.get("username")
            token = doc.get("token")

            # если старый plaintext password есть шифруем
            if doc.get("password") and not doc.get("password_enc"):
                if _get_fernet():
                    enc = encrypt_password(doc["password"])
                    accounts_col.update_one(
                        {"user_id": user_id, "username": username},
                        {"$set": {"password_enc": enc}, "$unset": {"password": ""}},
                    )
                    doc["password_enc"] = enc

            password = None
            if doc.get("password_enc"):
                password = decrypt_password(doc["password_enc"])
            return (username, token, password)
        return None
    except PyMongoError as e:
        logging.error("Ошибка при получении активного аккаунта для пользователя %d: %s", user_id, e)
        return None

def get_all_accounts(user_id):
    # Получаем все аккаунты для указанного пользователя
    if accounts_col is None:
        init_db()
    try:
        cursor = accounts_col.find({"user_id": user_id}, {"username": 1, "is_active": 1, "_id": 0})
        accounts = [(doc.get("username"), bool(doc.get("is_active"))) for doc in cursor]
        logging.info("Список аккаунтов для пользователя %d получен", user_id)
        return accounts
    except PyMongoError as e:
        logging.error("[Ошибка при получении всех аккаунтов для пользователя %d: %s", user_id, e)
        return []

def set_active_account(user_id, username):
    # Устанавливаем указанный аккаунт как активный для пользователя
    if accounts_col is None:
        init_db()
    try:
        accounts_col.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
        accounts_col.update_one({"user_id": user_id, "username": username}, {"$set": {"is_active": True}})
        logging.info("Активным аккаунтом для пользователя %d установлен %s", user_id, username)
    except PyMongoError as e:
        logging.error("Ошибка при смене активного аккаунта для пользователя %d: %s", user_id, e)

def delete_account(user_id, username):
    # Удаляет аккаунт из базы данных
    if accounts_col is None:
        init_db()
    try:
        accounts_col.delete_one({"user_id": user_id, "username": username})
        logging.info("Аккаунт %s для пользователя %d удален", username, user_id)
    except PyMongoError as e:
        logging.error("Ошибка при удалении аккаунта %s для пользователя %d: %s", username, user_id, e)

def has_accounts(user_id):
    # Проверяет, есть ли у пользователя какие-либо аккаунты
    if accounts_col is None:
        init_db()
    try:
        count = accounts_col.count_documents({"user_id": user_id})
        return count > 0
    except PyMongoError as e:
        logging.error("Ошибка при проверке наличия аккаунтов для пользователя %d: %s", user_id, e)
        return False

def delete_all_accounts(user_id: int):
   # Удаляет все аккаунты для указанного пользователя
    if accounts_col is None:
        init_db()
    try:
        accounts_col.delete_many({"user_id": user_id})
        logging.info("Все аккаунты для пользователя %d удалены", user_id)
    except PyMongoError as e:
        logging.error("Ошибка при удалении всех аккаунтов для пользователя %d: %s", user_id, e)



def escape_for_markdown_v2(text: str) -> str:
    # Экранирует специальные символы Markdown V2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def get_current_week_range():
    # Возвращает диапазон дат для текущей недели
    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week.date(), end_of_week.date(), today.date()

# ипользование API

async def get_auth_token(username, password):
    # Получаем токен авторизации, используя имя пользователя и пароль. Возвращаем токен
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            login_payload = {
                "application_key": APPLICATION_KEY,
                "id_city": None,
                "password": password,
                "username": username
            }
            login_resp = await client.post(
                LOGIN_URL,
                headers=HEADERS,
                json=login_payload
            )
            login_resp.raise_for_status() # Вызываем исключение при ошибках HTTP
            
            login_json = login_resp.json()
            token = login_json.get("access_token") or login_json.get("token")
            if not token:
                raise Exception("Не удалось получить токен авторизации")
            return token
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise Exception("Ошибка авторизации: Неверный логин или пароль")
        else:
            raise Exception(f"Ошибка авторизации: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise Exception(f"Ошибка получения токена: {e}")

async def schedule_get(start_date, end_date, token):
    # Получает расписание по токену
    try:
        auth_headers = HEADERS.copy()
        auth_headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            params = {
                "date_start": start_date.strftime("%Y-%m-%d"),
                "date_end": end_date.strftime("%Y-%m-%d")
            }
            schedule_resp = await client.get(SCHEDULE_API_URL, headers=auth_headers, params=params)
            schedule_resp.raise_for_status()
            
            return schedule_resp.json()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise Exception("Ошибка авторизации") # Токен недействителен
        else:
            raise Exception(f"Ошибка получения расписания: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"[!] Неожиданная ошибка в schedule_get: {e}")
        raise

async def get_leader_stream(token):
    # Получаем топ-3 студентов потока по токену
    try:
        auth_headers = HEADERS.copy()
        auth_headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            response = await client.get(LEADER_STREAM_URL, headers=auth_headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise Exception("Ошибка авторизации") # Токен недействителен
        else:
            raise Exception(f"Ошибка HTTP при получении лидеров потока: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise Exception(f"Непредвиденная ошибка при получении лидеров потока: {e}")

async def get_leader_group(token):
   # Получаем список студентов группы по токену
    try:
        auth_headers = HEADERS.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(LEADER_GROUP_URL, headers=auth_headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise Exception("Ошибка авторизации") # Токен недействителен
        else:
            raise Exception(f"Ошибка HTTP при получении студентов группы: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise Exception(f"Непредвиденная ошибка при получении студентов группы: {e}")

async def get_future_exams(token):
    # Получаем список будущих экзаменов по токену
    try:
        auth_headers = HEADERS.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(FUTURE_EXAMS_URL, headers=auth_headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise Exception("Ошибка авторизации") # Токен недействителен
        else:
            raise Exception(f"Ошибка HTTP при получении списка экзаменов: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise Exception(f"Непредвиденная ошибка при получении списка экзаменов: {e}")

# Форматирование данных

def save_json_to_file(json_data: dict, file_path: str):
    # Сохраняем JSON данные в файл
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
        print(f"Файл {file_path} успешно создан.")
    except Exception as e:
        print(f"Ошибка при сохранении JSON в файл: {e}")
        raise

def convert_schedule_to_markdown(schedule: list) -> str:
    # Конвертируем данные расписания в Markdown
    try:
        today = datetime.today().date()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        weekdays_ru = {
            "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
            "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота",
            "Sunday": "Воскресенье"
        }

        if not isinstance(schedule, list):
            raise ValueError("Данные расписания должны быть списком.")

        filtered_schedule = [
            item for item in schedule
            if start_of_week <= datetime.strptime(item["date"], "%Y-%m-%d").date() <= end_of_week
        ]

        grouped = defaultdict(list)
        for item in filtered_schedule:
            grouped[item["date"]].append(item)

        start_date_escaped = escape_for_markdown_v2(str(start_of_week))
        end_date_escaped = escape_for_markdown_v2(str(end_of_week))
        md_lines = [f"*Расписание на неделю* {start_date_escaped} — {end_date_escaped}\n"]

        for i in range(7):
            current_day = start_of_week + timedelta(days=i)
            date_str = current_day.strftime("%Y-%m-%d")
            weekday_eng = current_day.strftime("%A")
            weekday_ru = weekdays_ru.get(weekday_eng, weekday_eng)

            weekday_md = escape_for_markdown_v2(weekday_ru)
            date_md = escape_for_markdown_v2(date_str)

            md_lines.append(f"\n━━━━━━━━━━━━━━\n*{weekday_md}* — _{date_md}_\n━━━━━━━━━━━━━━")

            if date_str in grouped:
                for lesson in sorted(grouped[date_str], key=lambda x: x["started_at"]):
                    subject_name = escape_for_markdown_v2(lesson['subject_name'])
                    teacher_name = escape_for_markdown_v2(lesson['teacher_name'])
                    room_name = escape_for_markdown_v2(lesson['room_name'])
                    
                    md_lines.append(f"📚 *{subject_name}*")
                    md_lines.append(f"⏰ {lesson['started_at']} — {lesson['finished_at']}")
                    md_lines.append(f"👨‍🏫 {teacher_name}")
                    md_lines.append(f"📍 {room_name}\n")
            else:
                md_lines.append("_Выходной_ 💤\n")
        
        markdown_text = "\n".join(md_lines)
        return markdown_text

    except Exception as e:
        print(f"Ошибка при создании Markdown: {e}")
        raise

def get_student_name(student_data: dict) -> str:
    # Возвращаем имя студента
    name = student_data.get('student_name') or student_data.get('full_name') or student_data.get('name')
    if name:
        return escape_for_markdown_v2(name)
    return "Неизвестный"

def convert_leader_stream_to_markdown(json_data: list) -> str:
    # Конвертируем данные лидеров потока в Markdown
    if not json_data:
        return "Список лидеров потока пуст\\"

    top_3 = json_data[:3]
    md_lines = ["🏆 Топ\\-3 в потоке🏆\n"]
    for i, student in enumerate(top_3):
        student_name = get_student_name(student)
        topcoins = escape_for_markdown_v2(str(student.get('amount', 'N/A')))
        md_lines.append(f"{i+1}\\. {student_name} \\- `{topcoins}` topcoins")

    return "\n".join(md_lines)

def create_leader_group_markdown(json_data: list) -> str:
    # Конвертируем данные студентов группы в Markdown
    if not json_data:
        return "Список студентов группы пуст\\"

    md_lines = ["👥 Студенты вашей группы 👥\n"]
    sorted_students = sorted(json_data, key=lambda x: x.get('amount', 0), reverse=True)

    for i, student in enumerate(sorted_students):
        student_name = get_student_name(student)
        topcoins = escape_for_markdown_v2(str(student.get('amount', 'N/A')))
        md_lines.append(f"{i+1}\\. {student_name}: `{topcoins}` topcoins")

    return "\n".join(md_lines)

def convert_exams_to_markdown(json_data: list) -> str:
    # Конвертируем данные экзаменов в Markdown V2
    if not json_data:
        return "🎉 Пока экзаменов нет, наслаждайтесь свободным временем\\!"

    md_lines = ["📝 *Будущие экзамены* 📝\n"]

    for exam in json_data:
        discipline = escape_for_markdown_v2(exam.get('spec', 'N/A'))
        date = escape_for_markdown_v2(exam.get('date', 'N/A'))

        md_lines.append(f"*{discipline}*")
        md_lines.append(f"⏰ {date}")
        md_lines.append("")  # пустая строка между экзаменами

    return "\n".join(md_lines)

if __name__ == "__main__":
    init_db()
