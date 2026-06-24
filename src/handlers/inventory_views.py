# src/handlers/inventory_views.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table
from prompt_toolkit.completion import FuzzyWordCompleter

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, PriceValidator
from commands import command, CATEGORY_INVENTORY_READ
from src.auth import ROLE_INVENTORY_MANAGER, ROLE_WORKER
from src.helpers import get_warehouse_choices, get_category_choices, get_username_by_id
from typing import Optional, List
from src.handlers.products import Product
from src.handlers.warehouses import Warehouse
from src.helpers import yes_no_choice


@dataclass
class OrderItemWithStatus:
    id: int
    product_id: int
    price: Decimal
    quantity: int
    orders_id: int
    product_sku: str
    product_name: str
    calculated_status: str

# Вычисляет статус для каждой позиции в заказе по inventory, необходим
def get_order_item_statuses(oid: int) -> List[OrderItemWithStatus]:
    conn = get_conn()

    # Получаем основную информацию о заказе
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by"
            "FROM sales.orders o WHERE o.id = %s", (oid,)
        )
        order_details = cur.fetchone()

    if not order_details:
        console.print(f"[yellow]Заказ с ID {oid} не найден.[/yellow]")
        return []

    order_status = order_details.status
    order_warehouse_id = order_details.warehouses_id
    processed_by = order_details.processed_by

    # Получаем позиции заказа
    with conn.cursor(row_factory=class_row(OrderItemWithStatus)) as cur:
        cur.execute(
            "SELECT oi.id, oi.product_id, oi.price, oi.quantity, oi.orders_id, p.sku AS product_sku, p.name AS product_name, 'placeholder' AS calculated_status"
            "FROM sales.order_items oi"
            "JOIN catalog.products p ON oi.product_id = p.id"
            "WHERE oi.orders_id = %s", (oid,)
        )
        raw_items = cur.fetchall()

    # Вычисляем статус для каждой позиции
    final_items = []
    for item in raw_items:
        status = _calculate_item_status(item, order_status, processed_by, order_warehouse_id, conn)
        final_item = OrderItemWithStatus(
            id=item.id,
            product_id=item.product_id,
            price=item.price,
            quantity=item.quantity,
            orders_id=item.orders_id,
            product_sku=item.product_sku,
            product_name=item.product_name,
            calculated_status=status
        )
        final_items.append(final_item)

    return final_items

# Для вычисления статуса по позициям
def _calculate_item_status(item: OrderItemWithStatus, order_status: str, processed_by: Optional[int], order_warehouse_id: int, conn) -> str:
    item_id = item.id
    product_id = item.product_id
    item_quantity = item.quantity

    if order_status == 'new' and processed_by is None:
        return 'ожидает обработки'

    elif order_status in ('processing', 'pending'):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SUM(quantity) FROM inventory.reserves"
                "WHERE order_id = %s AND product_id = %s AND warehouse_id = %s", (item.orders_id, product_id, order_warehouse_id)
            )
            reserved_qty_result = cur.fetchone()
            reserved_qty = reserved_qty_result[0] if reserved_qty_result[0] is not None else 0

        if reserved_qty >= item_quantity:
            return 'в резерве'
        else:
            # Проверяем, есть ли товар в пути
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM inventory.transfer_items ti"
                    "JOIN inventory.transfers t ON ti.transfer_id = t.id"
                    "WHERE ti.product_id = %s"
                    "AND t.to_warehouse_id = %s"
                    "AND t.status IN ('planned', 'shipping', 'in_transit')"
                    "AND ti.reserve_id IN ("
                    "SELECT r.id FROM inventory.reserves r"
                    "WHERE r.order_id = %s AND r.product_id = %s"
                    ")", (product_id, order_warehouse_id, item.orders_id, product_id)
                )
                exists_pending_transfer = cur.fetchone()

            if exists_pending_transfer:
                with conn.cursor() as cur_time:
                    cur_time.execute(
                        "SELECT MIN(t.arriving_at)"
                        "FROM inventory.transfer_items ti"
                        "JOIN inventory.transfers t ON ti.transfer_id = t.id"
                        "WHERE ti.product_id = %s"
                        "AND t.to_warehouse_id = %s"
                        "AND t.status IN ('planned', 'shipping', 'in_transit')"
                        "AND ti.reserve_id IN ("
                        "SELECT r.id FROM inventory.reserves r"
                        "WHERE r.order_id = %s AND r.product_id = %s"
                        ")", (product_id, order_warehouse_id, item.orders_id, product_id)
                    )
                    earliest_arrival = cur_time.fetchone()[0]

                arrival_str = f", ожидается до {earliest_arrival.strftime('%Y-%m-%d %H:%M')}" if earliest_arrival else ""
                return f'в пути (ожидается до {earliest_arrival}{arrival_str})' if earliest_arrival else 'в пути'
            else:
                return 'ожидает обработки'

    elif order_status == 'packing':
        return 'запланирована отгрузка'

    elif order_status == 'shipped':
        return 'отгружено'

    return 'неизвестно'


@command("view warehouse stock", "просмотр остатков на складе", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER, ROLE_WORKER])
def view_warehouse_stock(_id: Optional[str] = None) -> None:
    warehouse_id = None
    if _id:
        try:
            warehouse_id = int(_id)
        except ValueError:
            render_error("ID склада должен быть числом.")
            return

    if not warehouse_id:
        wh_choices = [(str(wid), disp) for wid, disp in get_warehouse_choices()]
        if not wh_choices:
            console.print("[yellow]Нет доступных складов.[/yellow]")
            return
        selected_wh_id_str = choice(
            message="Выберите склад: ",
            options=wh_choices,
            default=wh_choices[0][0]
        )
        try:
            warehouse_id = int(selected_wh_id_str)
        except ValueError:
            render_error("Склад не выбран.")
            return

    conn = get_conn()
    table = Table(title=f"Остатки на складе #{warehouse_id}", show_header=True, header_style="bold cyan")
    table.add_column("Товар", style="green", min_width=25)
    table.add_column("Количество", style="magenta", min_width=10, justify="right")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.quantity, p.name, p.sku"
            "FROM inventory.stock s"
            "JOIN catalog.products p ON s.product_id = p.id"
            "WHERE s.warehouse_id = %s"
            "ORDER BY p.name", (warehouse_id,)
        )
        rows = cur.fetchall()

    if not rows:
        console.print(f"[yellow]На складе #{warehouse_id} нет товаров.[/yellow]")
        return

    for qty, name, sku in rows:
        table.add_row(f"{name} (SKU: {sku})", str(qty))

    console.print(table)


@command("view product stock", "просмотр остатков товара на складах", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER, ROLE_WORKER])
def view_product_stock(_id: Optional[str] = None) -> None:
    product_id = None
    if _id:
        try:
            product_id = int(_id)
        except ValueError:
            render_error("ID товара должен быть числом.")
            return

    if not product_id:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT sku, name FROM catalog.products ORDER BY id DESC")
            products_data = cur.fetchall()
        products_for_completer = [f"{sku} - {name}" for sku, name in products_data]

        completer = FuzzyWordCompleter(products_for_completer, match_middle=True)
        selected = prompt(
            "Выберите товар (введите часть SKU/названия, Tab для автодополнения): ",
            completer=completer,
            complete_while_typing=True,
        ).strip()

        if not selected:
            render_error("Товар не выбран.")
            return

        parts = selected.split(' - ', 1)
        if len(parts) < 2:
            render_error(f"Не удалось распознать выбранный товар: '{selected}'")
            return

        sku, name_part = parts[0], parts[1]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM catalog.products WHERE sku = %s", (sku,))
            result = cur.fetchone()
            if not result:
                render_error(f"Товар с SKU '{sku}' не найден.")
                return
            product_id = result[0]

    conn = get_conn()
    table = Table(title=f"Остатки товара #{product_id} на складах", show_header=True, header_style="bold cyan")
    table.add_column("Склад", style="green", min_width=25)
    table.add_column("Количество", style="magenta", min_width=10, justify="right")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.quantity, w.city_name, w.label, w.id"
            "FROM inventory.stock s"
            "JOIN catalog.warehouses w ON s.warehouse_id = w.id"
            "WHERE s.product_id = %s"
            "ORDER BY w.city_name, w.label", (product_id,)
        )
        rows = cur.fetchall()

    if not rows:
        console.print(f"[yellow]Товар #{product_id} отсутствует на всех складах.[/yellow]")
        return

    for qty, city_name, label, wid in rows:
        table.add_row(f"{city_name} ({label or 'без метки'} - ID:{wid})", str(qty))

    console.print(table)


