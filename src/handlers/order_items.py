# src/handlers/order_items.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDER_ITEMS
from src.auth import ROLE_SALES_MANAGER
from src.helpers import get_product_choices
from typing import Optional


@dataclass
class OrderItem:
    id: int
    product_id: int
    price: Decimal
    quantity: int
    orders_id: int
    product_sku: str
    product_name: str


def _render_order_item(item: OrderItem) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID позиции", str(item.id))
    table.add_row("Товар", f"{item.product_name} (SKU: {item.product_sku})")
    table.add_row("Цена за ед.", f"{item.price:.2f}")
    table.add_row("Количество", str(item.quantity))
    table.add_row("Сумма", f"{(item.price * item.quantity):.2f}")
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Позиция #{item.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_order_item_list(items: list[OrderItem]) -> None:
    table = Table(title="Позиции заказа", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=8, justify="right")
    table.add_column("Товар", style="blue", min_width=25)
    table.add_column("Цена", style="yellow", min_width=10, justify="right")
    table.add_column("Кол-во", style="magenta", min_width=6, justify="right")
    table.add_column("Сумма", style="red", min_width=10, justify="right")

    for i in items:
        table.add_row(
            str(i.id),
            f"{i.product_name} (SKU: {i.product_sku})",
            f"{i.price:.2f}",
            str(i.quantity),
            f"{(i.price * i.quantity):.2f}",
        )
    console.print(table)


def _get_order_items_by_order_id(oid: int) -> list[OrderItem]:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(OrderItem)) as cur:
        cur.execute("""
            SELECT oi.id, oi.product_id, oi.price, oi.quantity, oi.orders_id,
                   p.sku, p.name
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.orders_id = %s
            ORDER BY oi.id
        """, (oid,))
        return cur.fetchall()


def _update_order_total(oid: int) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sales.orders
            SET total_amount = COALESCE((SELECT SUM(price * quantity) FROM sales.order_items WHERE orders_id = %s), 0)
            WHERE id = %s
        """, (oid, oid))


def add_order_item_interactive(oid: int) -> None:
    conn = get_conn()
    prod_choices = get_product_choices()
    if not prod_choices:
        render_error("Нет товаров для выбора.")
        return

    prod_display = [disp for _, disp in prod_choices]
    selected = prompt("Товар: ", choices=prod_display).strip()
    try:
        pid: int = next(id_ for id_, disp in prod_choices if disp == selected)
    except StopIteration:
        render_error("Товар не найден.")
        return

    with conn.cursor(row_factory=class_row(OrderItem)) as cur:
        cur.execute("SELECT id, sku, name, price FROM catalog.products WHERE id = %s", (pid,))
        prod = cur.fetchone()
        if not prod:
            render_error("Товар не найден.")
            return

    qty_str = prompt("Количество: ", validator=NonEmptyValidator()).strip()
    try:
        qty = int(qty_str)
        if qty <= 0:
            raise ValueError
    except ValueError:
        render_error("Количество должно быть положительным целым числом.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales.order_items (product_id, price, quantity, orders_id) VALUES (%s, %s, %s, %s)",
            (pid, prod.price, qty, oid)
        )
    console.print(f"[green]Добавлено: {qty} × {prod.name} (#{pid}) в заказ #{oid}[/green]")


def _select_order_item(oid: int) -> Optional[OrderItem]:
    items = _get_order_items_by_order_id(oid)
    if not items:
        console.print(f"[yellow]В заказе #{oid} нет позиций.[/yellow]")
        return None

    choices = [f"{i.id}: {i.product_name} (x{i.quantity})" for i in items]
    selected = prompt("Выберите позицию: ", choices=choices).strip()
    try:
        iid = int(selected.split(':')[0])
        return next(i for i in items if i.id == iid)
    except (ValueError, StopIteration):
        render_error("Неверный выбор.")
        return None


@command("add order_item", "добавить позицию в заказ (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def add_order_item(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error("Добавление возможно только для заказов со статусом 'unpublished'.")
        return

    add_order_item_interactive(oid)
    _update_order_total(oid)
    console.print(f"[green]Позиция добавлена в заказ #{oid}. Сумма обновлена.[/green]")


@command("edit order_item", "редактировать позицию в заказе (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def edit_order_item(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error("Редактирование возможно только для заказов со статусом 'unpublished'.")
        return

    item = _select_order_item(oid)
    if not item:
        return

    _render_order_item(item)
    qty_str: str = prompt(f"Новое количество (текущее: {item.quantity}): ", default=str(item.quantity), validator=NonEmptyValidator()).strip()
    try:
        new_qty = int(qty_str)
        if new_qty <= 0:
            raise ValueError
    except ValueError:
        render_error("Количество должно быть положительным целым числом.")
        return

    with get_conn().cursor() as cur:
        cur.execute("UPDATE sales.order_items SET quantity = %s WHERE id = %s", (new_qty, item.id))
    console.print(f"[green]Позиция #{item.id} обновлена (кол-во: {new_qty})[/green]")
    _update_order_total(oid)


@command("delete order_item", "удалить позицию из заказа (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def delete_order_item(_id: str) -> None:
    try:
        oid = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error("Удаление возможно только для заказов со статусом 'unpublished'.")
        return

    item = _select_order_item(oid)
    if not item:
        return

    _render_order_item(item)
    answer = prompt("Удалить позицию? (y/n): ", validator=YesNoValidator())
    if YesNoValidator.is_yes(answer):
        with get_conn().cursor() as cur:
            cur.execute("DELETE FROM sales.order_items WHERE id = %s", (item.id,))
        console.print(f"[green]Позиция #{item.id} удалена[/green]")
        _update_order_total(oid)