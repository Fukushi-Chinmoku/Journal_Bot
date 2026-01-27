import httpx
import asyncio
import json
from datetime import datetime, timedelta
from collections import defaultdict
import os
import re
import sqlite3
import logging
from pathlib import Path

#API
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

#Database
current_file_path = Path(__file__).resolve()
database_folder = current_file_path.parent
DATABASE_FILE = 'user_credentials.db'
DATABASE_PATH = database_folder / DATABASE_FILE

logging.basicConfig(level=logging.INFO)

def init_db():
    """Инициализирует базу данных и создает таблицу 'accounts', если она не существует"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                token TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                PRIMARY KEY (user_id, username)
            )
        """)
        conn.commit()
        conn.close()
        logging.info("[DB] База данных %s инициализирована", DATABASE_PATH)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при инициализации базы данных: %s", e)

def add_account(user_id, username, token):
    """
    Добавляет новый аккаунт в базу данных. Сохраняет токен вместо пароля
    Деактивирует все остальные аккаунты для этого пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Деактивируем все остальные аккаунты 
        cursor.execute("UPDATE accounts SET is_active = 0 WHERE user_id = ?", (user_id,))

        # Добавляем или обновляем текущий аккаунт и делаем его активным
        cursor.execute("INSERT OR REPLACE INTO accounts (user_id, username, token, is_active) VALUES (?, ?, ?, ?)", (user_id, username, token, 1))

        conn.commit()
        conn.close()
        logging.info("[DB] Аккаунт %s для пользователя %d сохранен.", username, user_id)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при добавлении аккаунта для пользователя %d: %s", user_id, e)

def get_active_account(user_id):
    """
    Получает активный аккаунт и его токен для указанного пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        # Теперь возвращаем токен вместо пароля
        cursor.execute("SELECT username, token FROM accounts WHERE user_id = ? AND is_active = 1", (user_id,))
        credentials = cursor.fetchone()
        conn.close()
        if credentials:
            logging.info("[DB] Активный аккаунт для пользователя %d получен из БД", user_id)
        return credentials
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при получении активного аккаунта для пользователя %d: %s", user_id, e)
        return None

def get_all_accounts(user_id):
    """
    Получает все аккаунты для указанного пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT username, is_active FROM accounts WHERE user_id = ?", (user_id,))
        accounts = cursor.fetchall()
        conn.close()
        logging.info("[DB] Список аккаунтов для пользователя %d получен", user_id)
        return accounts
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при получении всех аккаунтов для пользователя %d: %s", user_id, e)
        return []

def set_active_account(user_id, username):
    """
    Устанавливает указанный аккаунт как активный для пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET is_active = 0 WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE accounts SET is_active = 1 WHERE user_id = ? AND username = ?", (user_id, username))
        conn.commit()
        conn.close()
        logging.info("[DB] Активным аккаунтом для пользователя %d установлен %s", user_id, username)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при смене активного аккаунта для пользователя %d: %s", user_id, e)

def delete_account(user_id, username):
    """
    Удаляет аккаунт из базы данных
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE user_id = ? AND username = ?", (user_id, username))
        conn.commit()
        conn.close()
        logging.info("[DB] Аккаунт %s для пользователя %d удален", username, user_id)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при удалении аккаунта %s для пользователя %d: %s", username, user_id, e)

def has_accounts(user_id):
    """
    Проверяет, есть ли у пользователя какие-либо аккаунты
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при проверке наличия аккаунтов для пользователя %d: %s", user_id, e)
        return False

def delete_all_accounts(user_id: int):
    """
    Удаляет все аккаунты для указанного пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        logging.info("[DB] Все аккаунты для пользователя %d удалены", user_id)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при удалении всех аккаунтов для пользователя %d: %s", user_id, e)

#Utility Functions

def escape_for_markdown_v2(text: str) -> str:
    """Экранирует специальные символы Markdown V2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def get_current_week_range():
    """Возвращает диапазон дат для текущей недели"""
    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week.date(), end_of_week.date(), today.date()

#API Interaction Functions

async def get_auth_token(username, password):
    """
    Получает токен авторизации, используя имя пользователя и пароль
    Возвращает токен, если успешно, иначе вызывает исключение
    """
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
            login_resp.raise_for_status() # Вызывает исключение при ошибках HTTP (4xx/5xx)
            
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
    """Получает расписание по токену"""
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
    """Получает топ-3 студентов потока по токену"""
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
    """Получает список студентов группы по токену"""
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
    """Получает список будущих экзаменов по токену"""
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

# --- Formatting Functions ---

def save_json_to_file(json_data: dict, file_path: str):
    """Сохраняет JSON-данные в файл."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
        print(f"Файл {file_path} успешно создан.")
    except Exception as e:
        print(f"Ошибка при сохранении JSON в файл: {e}")
        raise

def convert_schedule_to_markdown(schedule: list) -> str:
    """Конвертирует данные расписания в Markdown-формат"""
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
    """Возвращает имя студента, экранируя его."""
    name = student_data.get('student_name') or student_data.get('full_name') or student_data.get('name')
    if name:
        return escape_for_markdown_v2(name)
    return "Неизвестный"

def convert_leader_stream_to_markdown(json_data: list) -> str:
    """Конвертирует данные лидеров потока в Markdown-формат"""
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
    """Конвертирует данные студентов группы в Markdown-формат"""
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
    """Конвертирует данные экзаменов в Markdown V2 для JSON с полями spec и date"""
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
