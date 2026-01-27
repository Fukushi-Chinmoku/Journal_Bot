import sqlite3
import logging
import os
from pathlib import Path
import bcrypt

current_file_path = Path(__file__).resolve()
database_folder = current_file_path.parent
DATABASE_FILE = 'user_credentials.db'
DATABASE_PATH = database_folder / DATABASE_FILE

logging.basicConfig(level=logging.INFO)

def init_db():
    """
    Инициализирует базу данных и создает таблицу 'accounts', если она не существует
    """
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
        logging.info("[DB] База данных %s инициализирована.", DATABASE_PATH)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при инициализации базы данных: %s", e)

def add_account(user_id, username, password):
    """
    Добавляет новый аккаунт в базу данных. Пароль хешируется перед сохранением
    Новый аккаунт становится активным
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Хешируем пароль
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Сначала деактивируем все аккаунты для этого пользователя
        cursor.execute("UPDATE accounts SET is_active = 0 WHERE user_id = ?", (user_id,))

        # Затем добавляем или обновляем текущий аккаунт и делаем его активным
        cursor.execute("INSERT OR REPLACE INTO accounts (user_id, username, password, is_active) VALUES (?, ?, ?, ?)", (user_id, username, hashed_password, 1))

        conn.commit()
        conn.close()
        logging.info("[DB] Аккаунт %s для пользователя %d сохранен и установлен как активный.", username, user_id)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при добавлении аккаунта для пользователя %d: %s", user_id, e)

def verify_account(user_id, username, password):
    """
    Проверяет, совпадает ли введенный пароль с хешем в базе данных
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM accounts WHERE user_id = ? AND username = ?", (user_id, username))
        hashed_password = cursor.fetchone()
        conn.close()
        
        if hashed_password:
            # Сравниваем введенный пароль с хешированным
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password[0])
        return False
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при верификации аккаунта для пользователя %d: %s", user_id, e)
        return False

def get_active_account(user_id):
    """
    Получает активный аккаунт и его хешированный пароль для указанного пользователя
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT username, password FROM accounts WHERE user_id = ? AND is_active = 1", (user_id,))
        credentials = cursor.fetchone()
        conn.close()
        if credentials:
            logging.info("[DB] Активный аккаунт для пользователя %d получен из БД.", user_id)
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
        logging.info("[DB] Активным аккаунтом для пользователя %d установлен %s.", user_id, username)
    except sqlite3.Error as e:
        logging.error("[DB] Ошибка при смене активного аккаунта для пользователя %d: %s", user_id, e)

def delete_account(user_id, username):
    """
    Удаляет аккаунт из базы данных.
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

# --- Функции для миграции существующих паролей ---

def get_all_accounts_to_migrate():
    """Извлекает все аккаунты с паролями для последующей миграции"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, password FROM accounts")
        accounts = cursor.fetchall()
        conn.close()
        return accounts
    except sqlite3.Error as e:
        logging.error("Ошибка при извлечении аккаунтов для миграции: %s", e)
        return []

def migrate_passwords():
    """Хеширует и обновляет пароли для всех существующих аккаунтов"""
    accounts_to_migrate = get_all_accounts_to_migrate()
    if not accounts_to_migrate:
        logging.info("Нет аккаунтов для миграции")
        return

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        for user_id, username, password in accounts_to_migrate:
            # Проверяем, если пароль уже хеширован.
            if isinstance(password, bytes) and (password.startswith(b'$2b$') or password.startswith(b'$2a$')):
                logging.info("Пароль для пользователя %s (ID %d) уже хеширован. Пропускаем", username, user_id)
                continue
            
            # Хешируем пароль
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            
            # Обновляем запись в БД
            cursor.execute("UPDATE accounts SET password = ? WHERE user_id = ? AND username = ?", (hashed_password, user_id, username))
            logging.info("Пароль для аккаунта %s (ID %d) успешно хеширован и обновлен", username, user_id)

        conn.commit()
        conn.close()
        logging.info("Миграция паролей завершена")
    except sqlite3.Error as e:
        logging.error("Ошибка при миграции паролей: %s", e)



if __name__ == "__main__":
    init_db()
    migrate_passwords()
    
    # Демонстрация того, как получить хешированный пароль из базы данных
    user_id_test = 101
    username_test = "test_user"
    password_test = "password123"
    
    # Добавляем тестовый аккаунт в базу данных
    add_account(user_id_test, username_test, password_test)
    
    # Получаем активный аккаунт и его хешированный пароль
    credentials = get_active_account(user_id_test)
    
    if credentials:
        retrieved_username, retrieved_password_hash = credentials
        print("\n--- Проверка хешированного пароля в базе данных ---")
        print(f"Пользователь: {retrieved_username}")
        # Декодируем байты в строку для удобного отображения
        print(f"Хешированный пароль (из БД): {retrieved_password_hash.decode('utf-8')}")
        print("----------------------------------------------------\n")
