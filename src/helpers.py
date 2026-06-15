# src/helpers.py
from db import get_conn
from psycopg.rows import class_row
from src.handlers.products import Product
from src.handlers.warehouses import Warehouse

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

#Возвращает список (id, display_name) для выбора товара
def get_product_choices() -> list[tuple[int, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, sku || ' - ' || name AS display
            FROM catalog.products
            ORDER BY name
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
    return [
        "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
        "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
        "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград"
    ]