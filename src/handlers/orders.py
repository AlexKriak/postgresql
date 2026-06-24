# src/handlers/orders.py
import datetime
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table
import psycopg.errors as pg_errors

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDERS
from src.auth import ROLE_SALES_MANAGER, auth_user
from src.users import get_user
from src.helpers import get_warehouse_choices

from typing import Optional

from src.handlers.warehouses import Warehouse
from src.handlers.order_items import _render_order_item_list, _get_order_items_by_order_id, add_order_item_interactive, _update_order_total, _get_order_items_by_order_id
from src.helpers import yes_no_choice


@dataclass
class Order:
    id: int
    status: str
    total_amount: Decimal
    created_at: datetime.datetime
    warehouses_id: int
    created_by: int
    processed_by: Optional[int] = None


def _get_warehouse_by_id(wid: int) -> Optional['Warehouse']:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (wid,))
        return cur.fetchone()


def _render_order(order: Order) -> None:
    warehouse = _get_warehouse_by_id(order.warehouses_id)
    wh_display: str = f"{warehouse.city} ({warehouse.label or 'без метки'})" if warehouse else f"Склад ID {order.warehouses_id}"
    creator: str = get_username_by_id(order.created_by)
    processor: str = get_username_by_id(order.processed_by) if order.processed_by else "Не назначен"

    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(order.id))
    table.add_row("Статус", order.status)
    table.add_row("Сумма", f"{order.total_amount:.2f}")
    table.add_row("Дата создания", order.created_at.strftime("%Y-%m-%d %H:%M"))
    table.add_row("Склад", wh_display)
    table.add_row("Создано", creator)
    table.add_row("Обрабатывает", processor)
    table.add_column("Товаров (уникальных)", str(order.unique_items_count))

    panel: Panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Заказ #{order.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_order_list(orders: list[Order]) -> None:
    table = Table(title="Заказы", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Статус", style="blue", min_width=12)
    table.add_column("Сумма", style="yellow", min_width=10, justify="right")
    table.add_column("Дата", style="magenta", min_width=20)
    table.add_column("Склад", style="green", min_width=20)
    table.add_column("Создано", style="cyan", min_width=15)
    table.add_column("Обрабатывает", style="magenta", min_width=15)
    table.add_column("Товаров (уникальных)", style="white", min_width=10, justify="right")

    for o in orders:
        wh = _get_warehouse_by_id(o.warehouses_id)
        wh_disp: str = f"{wh.city} ({wh.label or 'без метки'})" if wh else str(o.warehouses_id)

        creator: str = get_username_by_id(o.created_by)
        processor: str = get_username_by_id(o.processed_by) if o.processed_by else "Не назначен"

        table.add_row(
            str(o.id),
            o.status,
            f"{o.total_amount:.2f}",
            o.created_at.strftime("%Y-%m-%d %H:%M"),
            wh_disp,
            creator,
            processor,
            str(o.unique_items_count)
        )
    console.print(table)


def _get_order_by_id(oid: int) -> Optional[Order]:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by"
            "FROM sales.orders o WHERE o.id = %s", (oid,))
        return cur.fetchone()


def _can_modify_order(status: str) -> bool:
    return status == "unpublished"


@command("list orders", "список всех заказов", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def list_orders() -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by,"
            "COALESCE(oi_counts.cnt, 0) AS unique_items_count"
            "FROM sales.orders o"
            "LEFT JOIN ("
            "SELECT orders_id, COUNT(DISTINCT product_id) AS cnt"
            "FROM sales.order_items"
            "GROUP BY orders_id"
            ") oi_counts ON o.id = oi_counts.orders_id"
            "ORDER BY o.created_at DESC"
        )
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Заказов пока нет.[/yellow]")
        return
    _render_order_list(orders)


@command("list orders new", "список новых заказов", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_new_orders() -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by,"
            "COALESCE(oi_counts.cnt, 0) AS unique_items_count"
            "FROM sales.orders o"
            "LEFT JOIN ("
            "SELECT orders_id, COUNT(DISTINCT product_id) AS cnt"
            "FROM sales.order_items"
            "GROUP BY orders_id"
            ") oi_counts ON o.id = oi_counts.orders_id"
            "WHERE o.status = 'new'"
            "ORDER BY o.created_at DESC"
        )
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Новых заказов нет.[/yellow]")
        return
    console.print("\n[yellow]Новые заказы:[/yellow]")
    _render_order_list(orders)


@command("list orders processing", "список заказов в обработке", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_processing_orders() -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by,"
            "COALESCE(oi_counts.cnt, 0) AS unique_items_count"
            "FROM sales.orders o"
            "LEFT JOIN ("
            "SELECT orders_id, COUNT(DISTINCT product_id) AS cnt"
            "FROM sales.order_items"
            "GROUP BY orders_id"
            ") oi_counts ON o.id = oi_counts.orders_id"
            "WHERE o.status = 'processing'"
            "ORDER BY o.created_at DESC"
        )
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Нет заказов в обработке.[/yellow]")
        return
    console.print("\n[yellow]Заказы в обработке:[/yellow]")
    _render_order_list(orders)


@command("list orders my", "список заказов, обрабатываемых мной", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_my_orders() -> None:
    current_user_id = auth_user().id
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute(
            "SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by, o.processed_by,"
            "COALESCE(oi_counts.cnt, 0) AS unique_items_count"
            "FROM sales.orders o"
            "LEFT JOIN ("
            "SELECT orders_id, COUNT(DISTINCT product_id) AS cnt"
            "FROM sales.order_items"
            "GROUP BY orders_id"
            ") oi_counts ON o.id = oi_counts.orders_id"
            "WHERE o.status IN ('processing', 'pending', 'packing') AND o.processed_by = %s"
            "ORDER BY o.created_at DESC", (current_user_id,)
        )
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Нет заказов, обрабатываемых вами.[/yellow]")
        return
    console.print("\n[yellow]Ваши заказы:[/yellow]")
    _render_order_list(orders)


# Для менеджера
@command("mark order processing", "взять заказ в обработку", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def mark_order_processing(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    current_user_id = auth_user().id
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute(
                "SELECT status, processed_by"
                "FROM sales.orders"
                "WHERE id = %s FOR UPDATE;", (oid,)
            )
            order_row = cur.fetchone()

            if not order_row:
                render_error(f"Заказ с ID {oid} не найден")
                cur.execute("ROLLBACK;")
                return

            order_status, current_processed_by = order_row

            if order_status != "new":
                render_error(f"Нельзя взять в обработку заказ со статусом '{order_status}'.")
                cur.execute("ROLLBACK;")
                return

            if current_processed_by is not None and current_processed_by != current_user_id:
                 render_error(f"Нельзя взять в обработку заказ, уже взятый пользователем ID {current_processed_by}.")
                 cur.execute("ROLLBACK;")
                 return

            console.print(f"Проверка заказа #{oid} (статус: {order_status})")

            answer: bool = yes_no_choice(f"Взять заказ #{oid} в обработку?")
            if not answer:
                cur.execute("ROLLBACK;")
                console.print("[yellow]Действие отменено.[/yellow]")
                return

            cur.execute(
                "UPDATE sales.orders"
                "SET status = 'processing', processed_by = %s"
                "WHERE id = %s AND status = 'new'", (current_user_id, oid)
            )

            rows_affected = cur.rowcount
            if rows_affected == 0:
                render_error(f"Не удалось взять заказ #{oid} в обработку. Возможно, его уже кто-то взял.")
                cur.execute("ROLLBACK;")
            else:
                cur.execute("COMMIT;")
                console.print(f"[green]Заказ #{oid} взят в обработку.[/green]")

        except Exception as e:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK;")
            render_error(f"Ошибка при взятии заказа в обработку: {e}")


@command("show order", "информация о заказе", CATEGORY_ORDERS, [ROLE_SALES_MANAGER, ROLE_INVENTORY_MANAGER])
def show_order(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    _render_order(order)

    items_with_status = get_order_item_statuses(oid)
        if items_with_status:
            _render_order_item_list_with_status(items_with_status)
        else:
            console.print("[i]В заказе нет позиций.[/i]")


def _render_order_item_list_with_status(items: list) -> None:
    table = Table(title="Позиции заказа (с вычисленным статусом)", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=8, justify="right")
    table.add_column("Товар", style="blue", min_width=25)
    table.add_column("Цена", style="yellow", min_width=10, justify="right")
    table.add_column("Кол-во", style="magenta", min_width=6, justify="right")
    table.add_column("Сумма", style="red", min_width=10, justify="right")
    table.add_column("Статус", style="green", min_width=15)

    for i in items:
        table.add_row(
            str(i.get('id', i.id)),
            f"{i.get('product_name', getattr(i, 'product_name', 'N/A'))} (SKU: {i.get('product_sku', getattr(i, 'product_sku', 'N/A'))})",
            f"{getattr(i, 'price', i.get('price', 0)):.2f}",
            str(getattr(i, 'quantity', i.get('quantity', 0))),
            f"{(getattr(i, 'price', i.get('price', 0)) * getattr(i, 'quantity', i.get('quantity', 0))):.2f}",
            i.get('calculated_status', getattr(i, 'calculated_status', 'Неизвестно'))
        )
    console.print(table)


@command("add order", "добавить заказ (интерактивно)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def add_order() -> None:

    conn: object = get_conn()
    current_user_id: int = auth_user().id

    # Выбор склада через choice()
    wh_choices: list[tuple[str, str]] = [(str(wid), disp) for wid, disp in get_warehouse_choices()]
    selected_wh_id_str: str = choice(
        message="Склад: ",
        options=wh_choices,
        default=wh_choices[0][0]
    )
    try:
        wh_id: int = int(selected_wh_id_str)
    except ValueError:
        render_error("Склад не выбран.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales.orders (status, total_amount, warehouses_id, created_by) "
            "VALUES ('unpublished', 0, %s, %s) RETURNING id",
            (wh_id, current_user_id)
        )
        new_oid: int = cur.fetchone()[0]

    console.print(f"[green]Заказ #{new_oid} создан (статус: unpublished)[/green]")


    while True:
        add_another: bool = yes_no_choice("Добавить товар в заказ?")
        if not add_another:
            break
        add_order_item_interactive(new_oid)

    _update_order_total(new_oid)
    console.print(f"[green]Заказ #{new_oid} сохранён. Сумма рассчитана.[/green]")


@command("edit order", "редактировать заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def edit_order(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        error_msg = f"Нельзя редактировать заказ со статусом '{order.status}'."
        if order.processed_by is not None:
            processor_name = get_username_by_id(order.processed_by)
            error_msg += f" Заказ уже взят в обработку пользователем {processor_name}."
        render_error(error_msg)
        return

    wh_choices: list[tuple[str, str]] = [(str(wid), disp) for wid, disp in get_warehouse_choices()]
    selected_wh_id_str: str = choice(
        message="Склад: ",
        options=wh_choices,
        default=str(order.warehouses_id)
    )
    try:
        wh_id: int = int(selected_wh_id_str)
    except ValueError:
        render_error("Склад не выбран.")
        return

    with get_conn().cursor() as cur:
        cur.execute("UPDATE sales.orders SET warehouses_id = %s WHERE id = %s", (wh_id, oid))
    console.print(f"[green]Заказ #{oid} обновлён[/green]")


@command("delete order", "удалить заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def delete_order(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        error_msg = f"Нельзя удалить заказ со статусом '{order.status}'."
        if order.processed_by is not None:
            processor_name = get_username_by_id(order.processed_by)
            error_msg += f" Заказ уже взят в обработку пользователем {processor_name}."
        render_error(error_msg)
        return

    _render_order(order)
    answer: bool = yes_no_choice("Удалить заказ и все его позиции?")
    if answer:
        with get_conn().cursor() as cur:
            cur.execute("DELETE FROM sales.order_items WHERE orders_id = %s", (oid,))
            cur.execute("DELETE FROM sales.orders WHERE id = %s", (oid,))
        console.print(f"[green]Заказ #{oid} удалён[/green]")


@command("publish order", "опубликовать заказ (unpublished → new)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def publish_order(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if order.status != "unpublished":
        render_error("Публикация возможна только для статуса 'unpublished'.")
        return
    if order.processed_by is not None:
        processor_name = get_username_by_id(order.processed_by)
        render_error(f"Невозможно опубликовать заказ, уже взятый в обработку пользователем {processor_name}.")
        return

    if not _get_order_items_by_order_id(oid):
        render_error("Нельзя опубликовать заказ без позиций.")
        return

    with get_conn().cursor() as cur:
        cur.execute("UPDATE sales.orders SET status = 'new' WHERE id = %s", (oid,))
    console.print(f"[green]Заказ #{oid} опубликован[/green]")
