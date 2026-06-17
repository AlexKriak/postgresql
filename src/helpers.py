# src/helpers.py
from db import get_conn
from psycopg.rows import class_row
from src.handlers.products import Product
from src.handlers.warehouses import Warehouse
from prompt_toolkit.shortcuts import choice
from validators import YesNoValidator

#Возвращает список (id, display_name) для выбора склада
def get_warehouse_choices() -> list[tuple[int, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, city || ' (' || COALESCE(label, '') || ')' AS display
            FROM catalog.warehouses
            ORDER BY city, label
        """)
        return cur.fetchall()

#Возвращает список (id, name) для выбора категории
def get_category_choices() -> list[tuple[int, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories ORDER BY name")
        return cur.fetchall()

#Возвращает список допустимых статусов заказа
def get_order_status_choices() -> list[str]:
    return [
        "unpublished",
        "new",
        "processing",
        "pending",
        "packing",
        "shipped"
    ]

#Возвращает список городов (для автодополнения или выбора)
def get_city_choices() -> list[str]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM catalog.cities ORDER BY name")
        rows = cur.fetchall()
    # fetchall возвращает список кортежей, извлекаем первый элемент каждого
    return [row[0] for row in rows]

# Вспомогательная функция для получения списка городов
def get_city_id_name_choices() -> list[tuple[int, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM catalog.cities ORDER BY name")
        return cur.fetchall()

#Функция выбора Да/Нет для пользователя
def yes_no_choice(message: str) -> bool:
    result: str = choice(
        message=message,
        options=[
            ("y", "Да"),
            ("n", "Нет"),
        ],
        default="n",
        validator=YesNoValidator()
    )
    return result == "y"