# src/handlers/orders.py
import datetime
from dataclasses import dataclass
from decimal import Decimal

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDERS
from src.handlers.warehouses import _get_warehouse_choices, _get_warehouse_by_id
from src.auth import auth_user, ROLE_SALES_MANAGER
from src.users import get_user


@dataclass
class Order:
    id: int
    status: str
    total_amount: Decimal
    created_at: datetime.datetime
    warehouses_id: int
    created_by: int


STATUS_CHOICES = ["unpublished", "new", "processing", "pending", "packing", "shipped"]
status_validator = ChoiceValidator(STATUS_CHOICES,
                                   message="Статус должен быть одним из следующего списка: " + ", ".join(
                                       STATUS_CHOICES))


def _get_username_by_id(user_id: int) -> str:
    """Получает имя пользователя по ID"""
    try:
        user = get_user(user_id)
        return user.username
    except ValueError:
        return f"User ID {user_id}"


def _render_order(order: Order) -> None:
    """Отображает информацию о заказе в виде таблицы внутри панели"""
    warehouse = _get_warehouse_by_id(order.warehouses_id)
    warehouse_name = f"{warehouse.city} ({warehouse.label or 'без метки'})" if warehouse else f"Склад ID {order.warehouses_id}"

    creator_username = _get_username_by_id(order.created_by)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(order.id))
    table.add_row("Статус", order.status)
    table.add_row("Сумма", f"{order.total_amount:.2f}")
    table.add_row("Дата создания", order.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("Склад", warehouse_name)
    table.add_row("Создано", creator_username)
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Заказ #{order.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_order_list(orders: list[Order]) -> None:
    """Отображает список заказов в таблице"""
    table = Table(title="Заказы", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Статус", style="blue", min_width=12)
    table.add_column("Сумма", style="yellow", min_width=10, justify="right")
    table.add_column("Дата создания", style="magenta", min_width=20)
    table.add_column("Склад ID", style="green", min_width=10, justify="right")
    table.add_column("Создано", style="cyan", min_width=15)

    for order in orders:
        warehouse = _get_warehouse_by_id(order.warehouses_id)
        warehouse_display = f"{warehouse.city} ({warehouse.label or 'без метки'})" if warehouse else str(order.warehouses_id)
        creator_username = _get_username_by_id(order.created_by)
        table.add_row(
            str(order.id),
            order.status,
            f"{order.total_amount:.2f}",
            order.created_at.strftime("%Y-%m-%d %H:%M"),
            warehouse_display,
            creator_username,
        )
    console.print(table)


def _get_order_by_id(order_id: int) -> Order | None:
    """Получает заказ по ID"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by
            FROM sales.orders o
            WHERE o.id = %s
        """, (order_id,))
        return cur.fetchone()


def _can_modify_order(status: str) -> bool:
    """Проверяет, можно ли изменять/удалять заказ с данным статусом"""
    return status == "unpublished"


@command("list orders", "список всех заказов", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def list_orders() -> None:
    """Выводит список всех заказов из таблицы sales.orders"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, o.warehouses_id, o.created_by
            FROM sales.orders o
            ORDER BY o.created_at DESC
        """)
        orders: list[Order] = cur.fetchall()

    if not orders:
        console.print("[yellow]Заказов пока нет.[/yellow]")
        return

    _render_order_list(orders)


@command("show order", "информация о заказе", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def show_order(_id: str) -> None:
    """Показывает детальную информацию о заказе по его ID"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    _render_order(order)

    from src.handlers.order_items import _render_order_item_list, _get_order_items_by_order_id
    items = _get_order_items_by_order_id(order_id)
    if items:
        _render_order_item_list(items)
    else:
        console.print("[i]В заказе пока нет позиций.[/i]")


@command("add order", "добавить заказ (интерактивно)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def add_order() -> None:
    """Добавляет новый заказ и позволяет сразу добавить позиции"""
    conn = get_conn()
    current_user_id = auth_user().id # Получаем ID текущего пользователя

    warehouse_choices = _get_warehouse_choices()
    if not warehouse_choices:
        render_error("Нет доступных складов. Сначала создайте склад.")
        return

    warehouse_completer = WordCompleter(warehouse_choices, ignore_case=True)
    warehouse_name = prompt(
        "Склад для заказа (выберите из списка): ",
        completer=warehouse_completer,
        validator=ChoiceValidator(warehouse_choices, "Выберите склад из списка. Используйте Tab для автодополнения.")
    ).strip()

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM catalog.warehouses WHERE city || ' (' || COALESCE(label, '') || ')' = %s OR city = %s", (warehouse_name, warehouse_name))
        warehouse_row = cur.fetchone()
        if not warehouse_row:
             render_error(f"Склад '{warehouse_name}' не найден в базе данных.")
             conn.close()
             return
        warehouse_id = warehouse_row[0]

        # Вставляем created_by
        cur.execute(
            "INSERT INTO sales.orders (status, total_amount, warehouses_id, created_by) VALUES ('unpublished', 0, %s, %s) RETURNING id",
            (warehouse_id, current_user_id) # Передаем ID пользователя
        )
        new_order_id = cur.fetchone()[0]

    conn.close() # Закрываем соединение после завершения операции

    console.print(f"[green]Заказ #{new_order_id} создан (статус: unpublished)[/green]")

    # Импортируем здесь, чтобы избежать циклической зависимости при запуске
    from src.handlers.order_items import add_order_item_interactive
    while True:
        add_another = prompt("Добавить товар в заказ? (y/n, д/н): ", validator=YesNoValidator())
        if not YesNoValidator.is_yes(add_another):
            break
        add_order_item_interactive(new_order_id)

    # Импортируем здесь, чтобы избежать циклической зависимости при запуске
    from src.handlers.order_items import _update_order_total
    _update_order_total(new_order_id)
    console.print(f"[green]Заказ #{new_order_id} сохранен. Общая сумма рассчитана.[/green]")


@command("edit order", "редактировать заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def edit_order(_id: str) -> None:
    """Редактирует заказ (только если статус 'unpublished')"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    conn = get_conn()
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if not _can_modify_order(order.status):
        render_error(f"Невозможно редактировать заказ со статусом '{order.status}'. Редактирование возможно только для статуса 'unpublished'.")
        return

    warehouse_choices = _get_warehouse_choices()
    if not warehouse_choices:
        render_error("Нет доступных складов.")
        return

    warehouse_completer = WordCompleter(warehouse_choices, ignore_case=True)
    current_warehouse = _get_warehouse_by_id(order.warehouses_id)
    current_warehouse_display = f"{current_warehouse.city} ({current_warehouse.label or 'без метки'})" if current_warehouse else str(order.warehouses_id)
    warehouse_name = prompt(
        f"Склад для заказа (выберите из списка) [текущий: {current_warehouse_display}]: ",
        default=current_warehouse_display,
        completer=warehouse_completer,
        validator=ChoiceValidator(warehouse_choices, "Выберите склад из списка. Используйте Tab для автодополнения.")
    ).strip()

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM catalog.warehouses WHERE city || ' (' || COALESCE(label, '') || ')' = %s OR city = %s", (warehouse_name, warehouse_name))
        warehouse_row = cur.fetchone()
        if not warehouse_row:
             render_error(f"Склад '{warehouse_name}' не найден в базе данных.")
             return
        warehouse_id = warehouse_row[0]

        cur.execute(
            "UPDATE sales.orders SET warehouses_id = %s WHERE id = %s",
            (warehouse_id, order_id),
        )
    console.print(f"[green]Заказ #{order_id} обновлён (новый склад: {warehouse_name})[/green]")


@command("delete order", "удалить заказ (только unpublished)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def delete_order(_id: str) -> None:
    """Удаляет заказ (только если статус 'unpublished')"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    conn = get_conn()
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if not _can_modify_order(order.status):
        render_error(f"Невозможно удалить заказ со статусом '{order.status}'. Удаление возможно только для статуса 'unpublished'.")
        return

    _render_order(order)

    answer = prompt("Вы уверены, что хотите удалить этот заказ и все его позиции? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        with conn.cursor() as cur:
            # Сначала удаляем позиции заказа
            # Импортируем здесь, чтобы избежать циклической зависимости при запуске
            from src.handlers.order_items import _get_order_items_by_order_id
            if _get_order_items_by_order_id(order_id): # Проверяем, есть ли позиции
                cur.execute("DELETE FROM sales.order_items WHERE orders_id = %s", (order_id,))
            # Потом сам заказ
            cur.execute("DELETE FROM sales.orders WHERE id = %s", (order_id,))
        console.print(f"[green]Заказ #{order_id} и все его позиции удалены[/green]")


@command("publish order", "опубликовать заказ (unpublished -> new)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def publish_order(_id: str) -> None:
    """Изменяет статус заказа с 'unpublished' на 'new'. После этого заказ нельзя редактировать или удалять"""
    try:
        order_id = int(_id)
    except ValueError:
        render_error(f"Неверный ID заказа: {_id}. Ожидается число.")
        return

    conn = get_conn()
    order = _get_order_by_id(order_id)
    if order is None:
        render_error(f"Заказ с ID {order_id} не найден")
        return

    if order.status != "unpublished":
        render_error(f"Невозможно опубликовать заказ со статусом '{order.status}'. Публикация возможна только для статуса 'unpublished'.")
        return

    from src.handlers.order_items import _get_order_items_by_order_id
    if not _get_order_items_by_order_id(order_id):
        render_error(f"Невозможно опубликовать заказ #{order_id}, так как в нём нет позиций.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales.orders SET status = 'new' WHERE id = %s",
            (order_id,),
        )
    console.print(f"[green]Заказ #{order_id} опубликован (статус изменён на 'new')[/green]")
