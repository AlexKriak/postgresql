# src/handlers/order_items.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.completion import FuzzyWordCompleter
from prompt_toolkit.shortcuts import CompleteStyle, choice
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDER_ITEMS
from src.auth import ROLE_SALES_MANAGER
from src.helpers import get_warehouse_choices
from typing import Optional
from src.handlers.products import Product
from src.handlers.orders import _get_order_by_id, _can_modify_order

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


def _get_product_completer(exclude_product_ids: list[int]) -> FuzzyWordCompleter:
    """Возвращает fuzzy-комплетер для товаров, исключая уже добавленные в заказ."""
    conn = get_conn()
    with conn.cursor() as cur:
        where_clause = ""
        if exclude_product_ids:
            where_clause = " AND p.id NOT IN (" + ",".join(map(str, exclude_product_ids)) + ")"
        cur.execute(f"""
            SELECT sku || ' - ' || name
            FROM catalog.products p
            WHERE 1=1 {where_clause}
            ORDER BY id DESC
            LIMIT 50
        """)
        products = [row[0] for row in cur.fetchall()]
    return FuzzyWordCompleter(products, match_middle=True)


def add_order_item_interactive(oid: int) -> None:

    conn: object = get_conn()

    # Получаем уже добавленные товары в заказе
    existing_product_ids: list[int] = [
        item.product_id for item in _get_order_items_by_order_id(oid)
    ]

    # Используем fuzzy-автодополнение с фильтрацией
    product_completer: FuzzyWordCompleter = _get_product_completer(existing_product_ids)

    selected: str = prompt(
        f"Товар для заказа #{oid} (введите часть SKU/названия, Tab для автодополнения): ",
        completer=product_completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
    ).strip()

    if not selected:
        render_error("Товар не выбран.")
        return

    # Парсим: "SKU - Название"
    parts: list[str] = selected.split(' - ', 1)
    if len(parts) < 2:
        # Поиск по SKU или названию напрямую
        with conn.cursor(row_factory=class_row(Product)) as cur:
            cur.execute("""
                SELECT id, sku, name, price
                FROM catalog.products
                WHERE sku ILIKE %s OR name ILIKE %s
                AND id NOT IN (%s)
                ORDER BY CASE WHEN sku ILIKE %s THEN 1 ELSE 2 END
                LIMIT 1
            """, (selected, selected, ",".join(map(str, existing_product_ids)) if existing_product_ids else "-1", selected))
            prod: Optional[Product] = cur.fetchone()
        if not prod:
            render_error(f"Товар '{selected}' не найден или уже добавлен в заказ.")
            return
    else:
        sku, name_part = parts[0], parts[1]
        with conn.cursor(row_factory=class_row(Product)) as cur:
            cur.execute("""
                SELECT id, sku, name, price
                FROM catalog.products
                WHERE sku = %s AND name ILIKE %s
                AND id NOT IN (%s)
                LIMIT 1
            """, (sku, f"%{name_part}%", ",".join(map(str, existing_product_ids)) if existing_product_ids else "-1"))
            prod = cur.fetchone()
        if not prod:
            # Повторная попытка без фильтрации по name_part
            with conn.cursor(row_factory=class_row(Product)) as cur:
                cur.execute("""
                    SELECT id, sku, name, price
                    FROM catalog.products
                    WHERE sku ILIKE %s OR name ILIKE %s
                    AND id NOT IN (%s)
                    LIMIT 1
                """, (sku, name_part, ",".join(map(str, existing_product_ids)) if existing_product_ids else "-1"))
                prod = cur.fetchone()
            if not prod:
                render_error(f"Товар '{selected}' не найден или уже добавлен в заказ.")
                return

    qty_str: str = prompt("Количество: ", validator=NonEmptyValidator()).strip()
    try:
        qty: int = int(qty_str)
        if qty <= 0:
            raise ValueError
    except ValueError:
        render_error("Количество должно быть положительным целым числом.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales.order_items (product_id, price, quantity, orders_id) VALUES (%s, %s, %s, %s)",
            (prod.id, prod.price, qty, oid)
        )
    console.print(f"[green]Добавлено: {qty} × {prod.name} (SKU: {prod.sku}) в заказ #{oid}[/green]")


def _select_order_item(oid: int) -> Optional[OrderItem]:
    items: list[OrderItem] = _get_order_items_by_order_id(oid)
    if not items:
        console.print(f"[yellow]В заказе #{oid} нет позиций.[/yellow]")
        return None

    choices: list[tuple[str, str]] = [
        (str(i.id), f"{i.product_name} (x{i.quantity})") for i in items
    ]
    selected_id_str: str = choice(
        message="Выберите позицию: ",
        options=choices,
        default=choices[0][0]
    )
    try:
        iid: int = int(selected_id_str)
        return next(i for i in items if i.id == iid)
    except (ValueError, StopIteration):
        render_error("Неверный выбор.")
        return None


@command("add order_item", "добавить позицию в заказ (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def add_order_item(_id: str) -> None:
    try:
        oid: int = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return


    order: Optional[Order] = _get_order_by_id(oid)
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
        oid: int = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return


    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error("Редактирование возможно только для заказов со статусом 'unpublished'.")
        return

    item: Optional[OrderItem] = _select_order_item(oid)
    if not item:
        return

    _render_order_item(item)
    qty_str: str = prompt(f"Новое количество (текущее: {item.quantity}): ", default=str(item.quantity), validator=NonEmptyValidator()).strip()
    try:
        new_qty: int = int(qty_str)
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
        oid: int = int(_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    order: Optional[Order] = _get_order_by_id(oid)
    if not order:
        render_error(f"Заказ с ID {oid} не найден")
        return
    if not _can_modify_order(order.status):
        render_error("Удаление возможно только для заказов со статусом 'unpublished'.")
        return

    item: Optional[OrderItem] = _select_order_item(oid)
    if not item:
        return

    _render_order_item(item)
    answer: bool = yes_no_choice("Удалить позицию?")
    if answer:
        with get_conn().cursor() as cur:
            cur.execute("DELETE FROM sales.order_items WHERE id = %s", (item.id,))
        console.print(f"[green]Позиция #{item.id} удалена[/green]")
        _update_order_total(oid)


def yes_no_choice(message: str) -> bool:
    result: str = choice(
        message=message,
        options=[
            ("y", "Да"),
            ("n", "Нет"),
        ],
        default="n"
    )
    return result == "y"