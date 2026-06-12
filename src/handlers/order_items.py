# src/handlers/order_items.py
import datetime
from dataclasses import dataclass
from decimal import Decimal

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDER_ITEMS
from src.handlers.products import _get_product_choices, _get_product_by_id
from src.auth import ROLE_SALES_MANAGER


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
    """Отображает информацию о позиции заказа в виде таблицы внутри панели"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID позиции", str(item.id))
    table.add_row("ID заказа", str(item.orders_id))
    table.add_row("Товар", f"{item.product_name} (SKU: {item.product_sku})")
    table.add_row("Цена за ед.", f"{item.price:.2f}")
    table.add_row("Количество", str(item.quantity))
    table.add_row("Сумма", f"{(item.price * item.quantity):.2f}")
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Позиция заказа #{item.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_order_item_list(items: list[OrderItem]) -> None:
    """Отображает список позиций заказа в таблице"""
    table = Table(title="Позиции заказа", show_header=True, header_style="bold cyan")
    table.add_column("ID позиции", style="dim", width=10, justify="right")
    table.add_column("Товар", style="blue", min_width=25)
    table.add_column("Цена за ед.", style="yellow", min_width=10, justify="right")
    table.add_column("Кол-во", style="magenta", min_width=6, justify="right")
    table.add_column("Сумма", style="red", min_width=10, justify="right")

    for item in items:
        table.add_row(
            str(item.id),
            f"{item.product_name} (SKU: {item.product_sku})",
            f"{item.price:.2f}",
            str(item.quantity),
            f"{(item.price * item.quantity):.2f}",
        )
    console.print(table)


def _get_order_items_by_order_id(order_id: int) -> list[OrderItem]:
    """Получает все позиции заказа по ID заказа"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(OrderItem)) as cur:
        cur.execute("""
            SELECT oi.id, oi.product_id, oi.price, oi.quantity, oi.orders_id,
                   p.sku as product_sku, p.name as product_name
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.orders_id = %s
            ORDER BY oi.id
        """, (order_id,))
        return cur.fetchall()


def _update_order_total(order_id: int):
    """Обновляет поле total_amount в таблице orders на основе позиций из order_items"""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(price * quantity), 0) FROM sales.order_items
            WHERE orders_id = %s
        """, (order_id,))
        calculated_total = cur.fetchone()[0]

        cur.execute(
            "UPDATE sales.orders SET total_amount = %s WHERE id = %s",
            (calculated_total, order_id)
        )


def add_order_item_interactive(order_id: int) -> None:
    """Внутренняя функция для интерактивного добавления позиции к заказу"""
    conn = get_conn()

    product_choices = _get_product_choices()
    if not product_choices:
        render_error("Нет доступных товаров для добавления в заказ.")
        return

    product_completer = WordCompleter(product_choices, ignore_case=True)
    product_name = prompt(
        f"Товар для добавления в заказ #{order_id} (автодополнение): ",
        completer=product_completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN
    ).strip()

    product = _get_product_by_name(product_name)
    if not product:
         render_error(f"Товар '{product_name}' не найден в базе данных.")
         return

    price = product.price

    quantity_str = prompt(f"Количество '{product.name}' (SKU: {product.sku}): ", validator=NonEmptyValidator()).strip()
    try:
        quantity = int(quantity_str)
        if quantity <= 0:
            render_error("Количество должно быть положительным числом.")
            return
    except ValueError:
        render_error(f"Неверное количество: {quantity_str}. Ожидается целое число.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales.order_items (product_id, price, quantity, orders_id) VALUES (%s, %s, %s, %s)",
            (product.id, price, quantity, order_id)
        )

    console.print(f"[green]Добавлено: {quantity} x {product.name} (#{product.id}) в заказ #{order_id}[/green]")


def _get_product_by_name(name: str) -> 'Product | None':
    """Получает продукт по имени (или SKU)"""
    from src.handlers.products import Product
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name
            FROM catalog.products p
            JOIN catalog.product_categories pc ON p.category_id = pc.id
            WHERE p.name = %s OR p.sku = %s
        """, (name, name))
        return cur.fetchone()


def _select_order_item(order_id: int) -> OrderItem | None:
    """Позволяет пользователю выбрать позицию заказа из списка"""
    items = _get_order_items_by_order_id(order_id)
    if not items:
        console.print(f"[yellow]В заказе #{order_id} нет позиций для выбора.[/yellow]")
        return None

    choices = [f"{item.id}: {item.product_name} (x{item.quantity})" for item in items]
    completer = WordCompleter(choices, ignore_case=True)

    selected_choice = prompt(
        f"Выберите позицию для действия (ID: Название) [Tab для списка]: ",
        completer=completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN
    ).strip().split(':')[0]

    try:
        selected_item_id = int(selected_choice)
        for item in items:
            if item.id == selected_item_id:
                return item
        render_error(f"Позиция с ID {selected_item_id} не найдена в заказе #{order_id}.")
        return None
    except ValueError:
        render_error(f"Неверный выбор: {selected_choice}. Ожидается ID позиции.")
        return None


@command("add order_item", "добавить позицию в заказ (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def add_order_item(_id: str) -> None:
    """Добавляет позицию в заказ (только если статус 'unpublished')"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    # Импортируем проверку статуса из orders.py
    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if not _can_modify_order(order.status):
        render_error(f"Невозможно добавить позицию в заказ со статусом '{order.status}'. Добавление возможно только для статуса 'unpublished'.")
        return

    add_order_item_interactive(order_id)
    _update_order_total(order_id)
    console.print(f"[green]Позиция добавлена в заказ #{order_id}. Общая сумма обновлена.[/green]")


@command("edit order_item", "редактировать позицию в заказе (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def edit_order_item(_id: str) -> None:
    """Редактирует позицию в заказе (только если статус 'unpublished')"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if not _can_modify_order(order.status):
        render_error(f"Невозможно редактировать позицию в заказе со статусом '{order.status}'. Редактирование возможно только для статуса 'unpublished'.")
        return

    item_to_edit = _select_order_item(order_id)
    if not item_to_edit:
        return

    _render_order_item(item_to_edit)

    quantity_str = prompt(f"Новое количество для '{item_to_edit.product_name}' (текущее: {item_to_edit.quantity}): ", default=str(item_to_edit.quantity), validator=NonEmptyValidator()).strip()
    try:
        new_quantity = int(quantity_str)
        if new_quantity <= 0:
            render_error("Количество должно быть положительным числом.")
            return
    except ValueError:
        render_error(f"Неверное количество: {quantity_str}. Ожидается целое число.")
        return

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales.order_items SET quantity = %s WHERE id = %s",
            (new_quantity, item_to_edit.id),
        )
    console.print(f"[green]Позиция #{item_to_edit.id} в заказе #{order_id} обновлена (новое кол-во: {new_quantity})[/green]")

    _update_order_total(order_id)
    console.print(f"[green]Общая сумма заказа #{order_id} обновлена.[/green]")


@command("delete order_item", "удалить позицию из заказа (только unpublished)", CATEGORY_ORDER_ITEMS, [ROLE_SALES_MANAGER])
def delete_order_item(_id: str) -> None:
    """Удаляет позицию из заказа (только если статус 'unpublished')"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    from src.handlers.orders import _get_order_by_id, _can_modify_order
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if not _can_modify_order(order.status):
        render_error(f"Невозможно удалить позицию из заказа со статусом '{order.status}'. Удаление возможно только для статуса 'unpublished'.")
        return

    item_to_delete = _select_order_item(order_id)
    if not item_to_delete:
        return

    _render_order_item(item_to_delete)

    answer = prompt("Вы уверены, что хотите удалить эту позицию? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sales.order_items WHERE id = %s", (item_to_delete.id,))
        console.print(f"[green]Позиция #{item_to_delete.id} из заказа #{order_id} удалена[/green]")

        _update_order_total(order_id)
        console.print(f"[green]Общая сумма заказа #{order_id} обновлена.[/green]")
