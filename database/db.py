import sqlite3
import logging
from pathlib import Path
import bcrypt

# путь к файлу БД (кладём рядом с этим скриптом)
current_file_path = Path(__file__).resolve()
database_folder = current_file_path.parent
DATABASE_FILE = 'user_credentials.db'
DATABASE_PATH = database_folder / DATABASE_FILE

logging.basicConfig(level=logging.INFO)


def init_db():
    # создаём базу и таблицу, если их ещё нет
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                PRIMARY KEY (user_id, username)
            )
        """)

        conn.commit()
        conn.close()
        logging.info("[DB] База данных и таблица готовы")

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при инициализации БД: %s", e)


def add_account(user_id, username, password):
    # добавляем аккаунт, пароль сразу хешируем
    # новый аккаунт автоматически становится активным
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # хешируем пароль перед сохранением
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # сначала выключаем все аккаунты пользователя
        cursor.execute(
            "UPDATE accounts SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )

        # сохраняем текущий и делаем его активным
        cursor.execute(
            """
            INSERT OR REPLACE INTO accounts (user_id, username, password, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (user_id, username, hashed_password)
        )

        conn.commit()
        conn.close()
        logging.info("[DB] Аккаунт %s сохранён и активирован", username)

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при добавлении аккаунта: %s", e)


def verify_account(user_id, username, password):
    # проверяем, совпадает ли введённый пароль с тем, что лежит в БД
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT password FROM accounts WHERE user_id = ? AND username = ?",
            (user_id, username)
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return False

        # сравниваем пароль с хешем
        return bcrypt.checkpw(password.encode('utf-8'), row[0])

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при проверке аккаунта: %s", e)
        return False


def get_active_account(user_id):
    # получаем активный аккаунт пользователя
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT username, password FROM accounts WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )

        account = cursor.fetchone()
        conn.close()

        return account

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при получении активного аккаунта: %s", e)
        return None


def get_all_accounts(user_id):
    # список всех аккаунтов пользователя (нужно для выбора)
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT username, is_active FROM accounts WHERE user_id = ?",
            (user_id,)
        )

        accounts = cursor.fetchall()
        conn.close()
        return accounts

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при получении списка аккаунтов: %s", e)
        return []


def set_active_account(user_id, username):
    # делаем выбранный аккаунт активным
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE accounts SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )
        cursor.execute(
            "UPDATE accounts SET is_active = 1 WHERE user_id = ? AND username = ?",
            (user_id, username)
        )

        conn.commit()
        conn.close()

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при смене активного аккаунта: %s", e)


def delete_account(user_id, username):
    # удаляем конкретный аккаунт
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM accounts WHERE user_id = ? AND username = ?",
            (user_id, username)
        )

        conn.commit()
        conn.close()

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при удалении аккаунта: %s", e)


def has_accounts(user_id):
    # проверяем, есть ли у пользователя хоть один аккаунт
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM accounts WHERE user_id = ?",
            (user_id,)
        )

        count = cursor.fetchone()[0]
        conn.close()
        return count > 0

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при проверке аккаунтов: %s", e)
        return False


def delete_all_accounts(user_id: int):
    # полностью чистим все аккаунты пользователя
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM accounts WHERE user_id = ?",
            (user_id,)
        )

        conn.commit()
        conn.close()

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при удалении всех аккаунтов: %s", e)


def get_all_accounts_to_migrate():
    # вытаскиваем все аккаунты — нужно для миграции старых паролей
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT user_id, username, password FROM accounts"
        )

        accounts = cursor.fetchall()
        conn.close()
        return accounts

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при получении аккаунтов для миграции: %s", e)
        return []


def migrate_passwords():
    # хешируем старые пароли, если вдруг они лежат в БД в открытом виде
    accounts = get_all_accounts_to_migrate()

    if not accounts:
        logging.info("[DB] Мигрировать нечего")
        return

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        for user_id, username, password in accounts:
            # если пароль уже похож на bcrypt — пропускаем
            if isinstance(password, bytes) and (
                password.startswith(b'$2b$') or password.startswith(b'$2a$')
            ):
                continue

            hashed_password = bcrypt.hashpw(
                password.encode('utf-8'),
                bcrypt.gensalt()
            )

            cursor.execute(
                "UPDATE accounts SET password = ? WHERE user_id = ? AND username = ?",
                (hashed_password, user_id, username)
            )

        conn.commit()
        conn.close()
        logging.info("[DB] Миграция паролей завершена")

    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при миграции паролей: %s", e)


if __name__ == "__main__":
    # при запуске файла напрямую — подготавливаем БД и мигрируем пароли
    init_db()
    migrate_passwords()

    # небольшой тест, чтобы убедиться, что всё работает
    user_id_test = 101
    username_test = "test_user"
    password_test = "password123"

    add_account(user_id_test, username_test, password_test)

    credentials = get_active_account(user_id_test)

    if credentials:
        username, password_hash = credentials
        print("\n--- Проверка пароля в БД ---")
        print(f"Пользователь: {username}")
        print(f"Хеш пароля: {password_hash.decode('utf-8')}")
        print("----------------------------\n")