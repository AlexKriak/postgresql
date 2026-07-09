# src/helpers.py
from db import get_conn
from psycopg.rows import class_row, Row
from src.handlers.products import Product
from src.handlers.warehouses import Warehouse
from prompt_toolkit.shortcuts import choice
from validators import YesNoValidator
import psycopg.errors as pg_errors
from dataclasses import dataclass
import datetime
from typing import Optional

#Возвращает список (id, display_name) для выбора склада
def get_warehouse_choices() -> list[tuple[int, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT w.id, w.city_name || ' (' || COALESCE(w.label, '') || ')' AS display"
            "FROM catalog.warehouses w"
            "ORDER BY w.city_name, w.label"
        )
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


# Получить имя пользователя по идентификатору
def get_username_by_id(uid: int) -> str:
    try:
        u = get_user(uid)
        return u.username
    except Exception:
        return f"UID:{uid}"


@dataclass
class Transfer:
    id: int
    from_warehouse_id: int
    to_warehouse_id: int
    status: str
    created_at: datetime.datetime
    started_at: Optional[datetime.datetime]
    arriving_at: Optional[datetime.datetime]
    received_at: Optional[datetime.datetime]
    from_city_name: str
    from_label: str
    to_city_name: str
    to_label: str

# Получает информацию о перемещении по ID
def _get_transfer_by_id(tid: int) -> Optional[Transfer]:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Transfer)) as cur:
        cur.execute("""
            SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status,
                   t.created_at, t.started_at, t.arriving_at, t.received_at,
                   fw.city_name as from_city_name, fw.label as from_label,
                   tw.city_name as to_city_name, tw.label as to_label
            FROM inventory.transfers t
            JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
            JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
            WHERE t.id = %s
        """, (tid,))
        return cur.fetchone()

# Находит существующий перемещение со статусом 'planned' между указанными складами или создаёт новое, если такого нет, с учетом гонки
def _get_or_create_planned_transfer(from_warehouse_id: int, to_warehouse_id: int) -> Optional[Transfer]:
    conn = get_conn()
    with conn:
        with conn.transaction(isolation_level="REPEATABLE READ"):
            with conn.cursor(row_factory=class_row(Transfer)) as cur:
                cur.execute("""
                    SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status,
                           t.created_at, t.started_at, t.arriving_at, t.received_at,
                           fw.city_name as from_city_name, fw.label as from_label,
                           tw.city_name as to_city_name, tw.label as to_label
                    FROM inventory.transfers t
                    JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                    JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                    WHERE t.from_warehouse_id = %s AND t.to_warehouse_id = %s AND t.status = 'planned'
                """, (from_warehouse_id, to_warehouse_id))
                existing_transfer = cur.fetchone()

                if existing_transfer:
                    return existing_transfer

                cur.execute("""
                    INSERT INTO inventory.transfers (from_warehouse_id, to_warehouse_id, status)
                    VALUES (%s, %s, 'planned')
                    RETURNING t.id;
                """, (from_warehouse_id, to_warehouse_id))
                inserted_id_row = cur.fetchone()

                if inserted_id_row:
                     inserted_id = inserted_id_row[0]
                     cur.execute("""
                        SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status,
                               t.created_at, t.started_at, t.arriving_at, t.received_at,
                               fw.city_name as from_city_name, fw.label as from_label,
                               tw.city_name as to_city_name, tw.label as to_label
                        FROM inventory.transfers t
                        JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                        JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                        WHERE t.id = %s;
                    """, (inserted_id,))
                     return cur.fetchone()
                else:
                    render_error("Не удалось получить ID вставленного перемещения в SERIALIZABLE транзакции.")
                    return None

    return None


# Получает список городов (id, name), из которых есть склады с товаром и маршруты
def _get_available_departure_cities_with_stock_and_routes() -> List[Tuple[int, str]]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT DISTINCT c.id, c.name
            FROM inventory.stock s
            JOIN catalog.warehouses w ON s.warehouse_id = w.id
            JOIN catalog.cities c ON w.city_id = c.id
            JOIN inventory.routes r ON c.id = r.from_city_id
            WHERE s.quantity > 0
            ORDER BY c.name;
        """)
        return cur.fetchall()


# Получает список складов (id, display) в заданном городе, участвующих в маршрутах отправителя
def _get_available_departure_warehouses_by_city(city_id: int) -> List[Tuple[int, str]]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT w.id, w.city_name || ' (' || COALESCE(w.label, '') || ')' AS display
            FROM catalog.warehouses w
            JOIN inventory.routes r ON w.city_id = r.from_city_id
            WHERE w.city_id = %s
            ORDER BY w.city_name, w.label;
        """, (city_id,))
        return cur.fetchall()


# Получает список городов (id, name), в которые есть маршрут из города отправления
def _get_available_destination_cities_by_departure_city(departure_city_id: int) -> List[Tuple[int, str]]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
             SELECT DISTINCT ct.id, ct.name
             FROM inventory.routes r
             JOIN catalog.cities ct ON r.to_city_id = ct.id
             WHERE r.from_city_id = %s
             ORDER BY ct.name;
        """, (departure_city_id,))
        return cur.fetchall()


# Получает список складов (id, display) в заданном городе получателя
def _get_available_destination_warehouses_by_city(city_id: int) -> List[Tuple[int, str]]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT w.id, w.city_name || ' (' || COALESCE(w.label, '') || ')' AS display
            FROM catalog.warehouses w
            JOIN inventory.routes r ON w.city_id = r.to_city_id
            WHERE w.city_id = %s
            ORDER BY w.city_name, w.label;
        """, (city_id,))
        return cur.fetchall()


# Получает список перемещений (id, from_warehouse_id, to_warehouse_id, from_city_name, to_city_name)
def _get_user_planned_transfers_with_routes(user_id: int) -> List[Tuple[int, int, int, str, str]]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT DISTINCT t.id, t.from_warehouse_id, t.to_warehouse_id,
                   fw.city_name as from_city_name, tw.city_name as to_city_name
            FROM inventory.transfers t
            JOIN inventory.transfer_items ti ON t.id = ti.transfer_id
            JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
            JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
            JOIN inventory.routes r ON fw.city_id = r.from_city_id AND tw.city_id = r.to_city_id
            WHERE t.status = 'planned' AND ti.requested_by = %s
        """, (user_id,))
        return cur.fetchall()