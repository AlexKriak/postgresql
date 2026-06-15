# src/handlers/orders.py
import datetime
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDERS
from src.auth import ROLE_SALES_MANAGER, auth_user
from src.users import get_user
from src.helpers import get_warehouse_choices, get_order_status_choices
from typing import Optional


@dataclass
class Order:
    id: int
    status: str
    total_amount: Decimal
    created_at: datetime.datetime
    warehouses_id: int
    created_by: int


def _get_username_by_id(uid: int) -> str:
    try:
        u = get_user(uid)
        return u.username
    except Exception:
        return f"UID:{uid}"


def _render_order(order: Order) -> None:
    warehouse = _get_warehouse_by_id(order.warehouses_id)
    wh_display = f"{warehouse.city} ({warehouse.label or 'без метки'})" if warehouse else f"Склад ID {order.warehouses_id}"
    creator = _get_username_by_id(order.created_by)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(order.id))
    table.add_row("Статус", order.status)
    table.add_row("Сумма", f"{order.total_amount:.2f}")
    table.add_row("Дата создания", order.created_at.strftime("%Y-%m-%d %H:%M"))
    table.add_row("Склад", wh_display)
    table.add_row("Создано", creator)

    panel = Panel(
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

    for o in orders:
        wh = _get_warehouse_by_id(o.warehouses_id)
        wh_disp = f"{wh.city} ({wh.label or 'без метки'})" if wh else str(o.warehouses_id)
        creator = _get_username_by_id(o.created_by)
        table.add_row(
            str(o.id),
            o.status,
            f"{o.total_amount:.2f}",
            o.created_at.strftime("%Y-%m-%d %H:%M"),
            wh_disp,
            creator,
        )
    console.print(table)


def _get_order_by_id(oid: int) -> Optional[Order]:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by
            FROM sales.orders o WHERE o.id = %s
        """, (oid,))
        return cur.fetchone()


def _can_modify_order(status: str) -> bool:
    return status == "unpublished"


@command("list orders", "список всех заказов", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def list_orders() -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by
            FROM sales.orders o ORDER BY o.created_at DESC
        """)
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Заказов пока нет.[/yellow]")
        return
    _render_order_list(orders)


@command("show order", "информация о заказе", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def show_order(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    _render_order(order)

    from src.handlers.order_items import _render_order_item_list, _get_order_items_by_order_id
    items = _get_order_items_by_order_id(oid)
    if items:
        _render_order_item_list(items)
    else:
        console.print("[i]В заказе нет позиций.[/i]")


@command("add order", "добавить заказ (интерактивно)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def add_order() -> None:
    conn = get_conn()
    current_user_id: int = auth_user().id

    # Выбор склада через choices
    wh_choices = [(wid, disp) for wid, disp in get_warehouse_choices()]
    wh_display = [disp for _, disp in wh_choices]
    selected = prompt("Склад: ", choices=wh_display, default=wh_display[0]).strip()
    try:
        wh_id = next(wid for wid, disp in wh_choices if disp == selected)
    except StopIteration:
        render_error("Склад не найден.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales.orders (status, total_amount, warehouses_id, created_by) "
            "VALUES ('unpublished', 0, %s, %s) RETURNING id",
            (wh_id, current_user_id)
        )
        new_oid = cur.fetchone()[0]

    console.print(f"[green]Заказ #{new_oid} создан (статус: unpublished)[/green]")

    from src.handlers.order_items import add_order_item_interactive
    while True:
        add_another = prompt("Добавить товар в заказ? (y/n, д/н): ", validator=YesNoValidator())
        if not YesNoValidator.is_yes(add_another):
            break
        add_order_item_interactive(new_oid)

    from src.handlers.order_items import _update_order_total
    _update_order_total(new_oid)
    console.print(f"[green]Заказ #{new_oid} сохранён. Сумма рассчитана.[/green]")


@command("edit order", "редактировать заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def edit_order(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error(f"Нельзя редактировать заказ со статусом '{order.status}'.")
        return

    wh_choices = [(wid, disp) for wid, disp in get_warehouse_choices()]
    wh_display = [disp for _, disp in wh_choices]
    selected = prompt(
        "Склад: ",
        choices=wh_display,
        default=_get_warehouse_by_id(order.warehouses_id).city if _get_warehouse_by_id(order.warehouses_id) else "Неизвестно"
    ).strip()
    try:
        wh_id = next(wid for wid, disp in wh_choices if disp == selected)
    except StopIteration:
        render_error("Склад не найден.")
        return

    with get_conn().cursor() as cur:
        cur.execute("UPDATE sales.orders SET warehouses_id = %s WHERE id = %s", (wh_id, oid))
    console.print(f"[green]Заказ #{oid} обновлён[/green]")


@command("delete order", "удалить заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def delete_order(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error(f"Нельзя удалить заказ со статусом '{order.status}'.")
        return

    _render_order(order)
    answer = prompt("Удалить заказ и все его позиции? (y/n): ", validator=YesNoValidator())
    if YesNoValidator.is_yes(answer):
        with get_conn().cursor() as cur:
            cur.execute("DELETE FROM sales.order_items WHERE orders_id = %s", (oid,))
            cur.execute("DELETE FROM sales.orders WHERE id = %s", (oid,))
        console.print(f"[green]Заказ #{oid} удалён[/green]")


@command("publish order", "опубликовать заказ (unpublished → new)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def publish_order(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if order.status != "unpublished":
        render_error("Публикация возможна только для статуса 'unpublished'.")
        return

    from src.handlers.order_items import _get_order_items_by_order_id
    if not _get_order_items_by_order_id(oid):
        render_error("Нельзя опубликовать заказ без позиций.")
        return

    with get_conn().cursor() as cur:
        cur.execute("UPDATE sales.orders SET status = 'new' WHERE id = %s", (oid,))
    console.print(f"[green]Заказ #{oid} опубликован[/green]")