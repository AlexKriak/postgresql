from typing import Final
import os
import psycopg
from psycopg import Connection, connect
from contextlib import contextmanager

# Загрузка .env файла
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv не установлен, используем переменные окружения OS.")

DB_NAME: Final[str] = os.environ["DB_NAME"]
DB_USER: Final[str] = os.environ["DB_USER"]
DB_PASSWORD: Final[str] = os.environ["DB_PASSWORD"]
DB_HOST: Final[str] = os.environ["DB_HOST"]
DB_PORT: Final[int] = int(os.environ["DB_PORT"])

def get_conn() -> Connection:
    return connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )