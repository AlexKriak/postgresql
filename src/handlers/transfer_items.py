# src/handlers/transfer_items.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import CompleteStyle, choice
from prompt_toolkit.completion import FuzzyWordCompleter
from psycopg.rows import class_row, Row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_INVENTORY_TRANSFER_ITEMS
from src.auth import ROLE_INVENTORY_MANAGER
from src.helpers import get_warehouse_choices, get_username_by_id, yes_no_choice, Transfer, _get_transfer_by_id, _get_or_create_planned_transfer
from typing import Optional, List
import datetime


@dataclass
class TransferItem:
    id: int
    transfer_id: int
    product_id: int
    quantity: int
    requested_by: Optional[int]
    reserve_id: Optional[int]
    status: str
    created_at: datetime.datetime
    shipped_at: Optional[datetime.datetime]
    received_at: Optional[datetime.datetime]
    # Поля для удобства отображения
    product_sku: str
    product_name: str
    requested_by_username: Optional[str]
    order_id_related: Optional[int]


def _render_transfer_item(item: TransferItem) -> None:
    """Отображает информацию о позиции перемещения"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=20)
    table.add_column("Значение", style="white")
    table.add_row("ID позиции", str(item.id))
    table.add_row("Товар", f"{item.product_name} (SKU: {item.product_sku})")
    table.add_row("Количество", str(item.quantity))
    table.add_row("Запрошено", item.requested_by_username or "N/A")
    table.add_row("Статус", item.status)
    table.add_row("ID заказа (из резерва)", str(item.order_id_related) if item.order_id_related else "N/A")
    if item.shipped_at:
        table.add_row("Отгружено", item.shipped_at.strftime("%Y-%m-%d %H:%M"))
    if item.received_at:
        table.add_row("Получено", item.received_at.strftime("%Y-%m-%d %H:%M"))

    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Позиция перемещения #{item.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_transfer_item_list(items: list[TransferItem]) -> None:
    """Отображает список позиций перемещения"""
    table = Table(title="Позиции перемещения", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=8, justify="right")
    table.add_column("Товар", style="blue", min_width=25)
    table.add_column("Кол-во", style="magenta", min_width=6, justify="right")
    table.add_column("Запрошено", style="cyan", min_width=15)
    table.add_column("Статус", style="green", min_width=12)
    table.add_column("ID заказа (из резерва)", style="yellow", min_width=10, justify="right")

    for i in items:
        table.add_row(
            str(i.id),
            f"{i.product_name} (SKU: {i.product_sku})",
            str(i.quantity),
            i.requested_by_username or "N/A",
            i.status,
            str(i.order_id_related) if i.order_id_related else "N/A",
        )
    console.print(table)


def _get_transfer_items_by_transfer_id(tid: int) -> List[TransferItem]:
    """Получает позиции перемещения по ID перемещения"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(TransferItem)) as cur:
        cur.execute("""
            SELECT ti.id, ti.transfer_id, ti.product_id, ti.quantity,
                   ti.requested_by, ti.reserve_id, ti.status,
                   ti.created_at, ti.shipped_at, ti.received_at,
                   p.sku as product_sku, p.name as product_name,
                   u.username as requested_by_username,
                   r.order_id as order_id_related
            FROM inventory.transfer_items ti
            JOIN catalog.products p ON ti.product_id = p.id
            LEFT JOIN auth.users u ON ti.requested_by = u.id
            LEFT JOIN inventory.reserves r ON ti.reserve_id = r.id
            WHERE ti.transfer_id = %s
            ORDER BY ti.id
        """, (tid,))
        return cur.fetchall()


@command("add transfer item", "добавить позицию в перемещение (только planned)", CATEGORY_INVENTORY_TRANSFER_ITEMS, [ROLE_INVENTORY_MANAGER])
def add_transfer_item() -> None:
    conn = get_conn()
    current_user_id = auth_user().id

    # Выбор склада отправления
    from_warehouse_choices = get_warehouse_choices()
    if not from_warehouse_choices:
        console.print("[yellow]Нет доступных складов отправления.[/yellow]")
        return
    from_choices = [(str(wid), disp) for wid, disp in from_warehouse_choices]
    selected_from_id_str: str = choice(
        message="Выберите склад отправления: ",
        options=from_choices,
        default=from_choices[0][0]
    )
    try:
        from_warehouse_id = int(selected_from_id_str)
    except ValueError:
        render_error("Склад отправления не выбран.")
        return

    # Выбор склада получения
    to_warehouse_choices = [(wid, disp) for wid, disp in get_warehouse_choices() if wid != from_warehouse_id]
    if not to_warehouse_choices:
        console.print("[yellow]Нет доступных складов получения (кроме отправления).[/yellow]")
        return
    to_choices = [(str(wid), disp) for wid, disp in to_warehouse_choices]
    selected_to_id_str: str = choice(
        message="Выберите склад получения: ",
        options=to_choices,
        default=to_choices[0][0]
    )
    try:
        to_warehouse_id = int(selected_to_id_str)
    except ValueError:
        render_error("Склад получения не выбран.")
        return

    # Цикл выбора продукта и количества
    while True:
        try:
            with conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM inventory.stock WHERE warehouse_id = %s FOR UPDATE;", (from_warehouse_id,))
                        cur.execute("SELECT 1 FROM inventory.transfers WHERE from_warehouse_id = %s AND to_warehouse_id = %s AND status = 'planned' FOR UPDATE;", (from_warehouse_id, to_warehouse_id))

                        cur.execute(
                            "SELECT s.product_id, p.name, p.sku, s.quantity"
                            "FROM inventory.stock s"
                            "JOIN catalog.products p ON s.product_id = p.id"
                            "WHERE s.warehouse_id = %s AND s.quantity > 0"
                            "ORDER BY p.name"
                        )
                        stock_items = cur.fetchall()

                        if not stock_items:
                             console.print(f"[yellow]На складе отправления (ID: {from_warehouse_id}) нет доступных товаров.[/yellow]")
                             return

                        choices = [(str(product_id), f"{name} (SKU: {sku}, в наличии: {qty})") for product_id, name, sku, qty in stock_items]
                        choices.append(("done", "Завершить добавление"))
                        selected_prod_or_done = choice(
                            message="Выберите товар для добавления или 'Завершить': ",
                            options=choices,
                            default=choices[0][0]
                        )

                        if selected_prod_or_done == "done":
                            console.print("[green]Добавление позиций в перемещение завершено.[/green]")
                            return

                        try:
                            selected_product_id = int(selected_prod_or_done)
                            max_available_qty = next(qty for pid, name, sku, qty in stock_items if pid == selected_product_id)
                        except (ValueError, StopIteration):
                            render_error("Товар не выбран или ошибка данных.")
                            continue

                        max_qty_str = prompt(f"Введите количество (максимум {max_available_qty}): ", validator=NonEmptyValidator()).strip()
                        try:
                            qty_to_add = int(max_qty_str)
                            if qty_to_add <= 0 or qty_to_add > max_available_qty:
                                raise ValueError
                        except ValueError:
                            render_error(f"Количество должно быть положительным целым числом не больше {max_available_qty}.")
                            continue

                        # Получение или создание planned трансфера
                        transfer = _get_or_create_planned_transfer(from_warehouse_id, to_warehouse_id)
                        if not transfer:
                            render_error("Не удалось получить или создать перемещение.")
                            return
                        tid = transfer.id

                        prod_name, prod_sku = next((name, sku) for pid, name, sku, qty in stock_items if pid == selected_product_id)
                        console.print(f"Добавление: {qty_to_add} x {prod_name} (SKU: {prod_sku}) в перемещение #{tid} (ID: {from_warehouse_id} -> {to_warehouse_id})")
                        confirm_add = yes_no_choice("Подтвердить?")
                        if not confirm_add:
                            console.print("[yellow]Добавление отменено.[/yellow]")
                            continue

                        # Обновление или создание transfer_item
                        cur.execute(
                            "SELECT id, quantity FROM inventory.transfer_items"
                            "WHERE transfer_id = %s AND product_id = %s AND requested_by = %s AND status = 'planned'"
                            "LIMIT 1;"
                        , (tid, selected_product_id, current_user_id))
                        existing_item_for_user_prod = cur.fetchone()

                        if existing_item_for_user_prod:
                            existing_item_id, current_qty = existing_item_for_user_prod
                            new_qty = current_qty + qty_to_add
                            cur.execute("""
                                UPDATE inventory.transfer_items
                                SET quantity = %s
                                WHERE id = %s AND transfer_id = %s AND product_id = %s AND requested_by = %s AND status = 'planned';
                            """, (new_qty, existing_item_id, tid, selected_product_id, current_user_id))
                            console.print(f"[green]Обновлена позиция #{existing_item_id}: {new_qty} x {prod_name} (SKU: {prod_sku}) в перемещении #{tid}[/green]")
                        else:
                            cur.execute("""
                                INSERT INTO inventory.transfer_items (transfer_id, product_id, quantity, requested_by, status)
                                VALUES (%s, %s, %s, %s, 'planned');
                            """, (tid, selected_product_id, qty_to_add, current_user_id))
                            console.print(f"[green]Добавлено: {qty_to_add} x {prod_name} (SKU: {prod_sku}) в перемещение #{tid}[/green]")

                        # Вычитание из стока
                        cur.execute(
                            "SELECT quantity FROM inventory.stock WHERE warehouse_id = %s AND product_id = %s FOR UPDATE;",
                            (from_warehouse_id, selected_product_id)
                        )
                        stock_row = cur.fetchone()
                        if not stock_row or stock_row[0] < qty_to_add: # stock_row[0] - распаковка tuple
                            render_error(f"Недостаточно товара '{prod_name}' на складе отправления. Попытка вычесть {qty_to_add}, доступно {stock_row[0] if stock_row else 0}.")
                            return

                        cur.execute(
                            "UPDATE inventory.stock SET quantity = quantity - %s WHERE warehouse_id = %s AND product_id = %s;",
                            (qty_to_add, from_warehouse_id, selected_product_id)
                        )
                        console.print(f"[blue]Вычтено {qty_to_add} x {prod_name} (SKU: {prod_sku}) со склада #{from_warehouse_id}.[/blue]")

                        add_more = yes_no_choice("Добавить ещё одну позицию в это же перемещение?")
                        if not add_more:
                             console.print(f"[green]Изменения в перемещении сохранены.[/green]")
                             return

        except Exception as e:
            render_error(f"Ошибка при добавлении позиции в перемещение: {e}")
            return


@command("remove transfer item", "удалить позицию из перемещения (только planned)", CATEGORY_INVENTORY_TRANSFER_ITEMS, [ROLE_INVENTORY_MANAGER])
def remove_transfer_item() -> None:
    current_user_id = auth_user().id

    # Выбор склада отправления (from)
    from_warehouse_choices = get_warehouse_choices()
    if not from_warehouse_choices:
        console.print("[yellow]Нет доступных складов отправления.[/yellow]")
        return
    from_choices = [(str(wid), disp) for wid, disp in from_warehouse_choices]
    selected_from_id_str: str = choice(
        message="Выберите склад отправления (from_warehouse_id): ",
        options=from_choices,
        default=from_choices[0][0]
    )
    try:
        from_warehouse_id = int(selected_from_id_str)
    except ValueError:
        render_error("Склад отправления не выбран.")
        return

    # Выбор склада получения (to)
    to_warehouse_choices = [(wid, disp) for wid, disp in get_warehouse_choices() if wid != from_warehouse_id]
    if not to_warehouse_choices:
        console.print("[yellow]Нет доступных складов получения (кроме отправления).[/yellow]")
        return
    to_choices = [(str(wid), disp) for wid, disp in to_warehouse_choices]
    selected_to_id_str: str = choice(
        message="Выберите склад получения (to_warehouse_id): ",
        options=to_choices,
        default=to_choices[0][0]
    )
    try:
        to_warehouse_id = int(selected_to_id_str)
    except ValueError:
        render_error("Склад получения не выбран.")
        return

    # Цикл выбора позиции и количества
    while True:
        try:
            conn = get_conn()
            with conn:
                with conn.transaction():
                    with conn.cursor(row_factory=Row) as cur:
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
                        transfer_row = cur.fetchone()

                    if not transfer_row:
                        console.print(f"[yellow]Нет запланированных перемещений между складами {from_warehouse_id} и {to_warehouse_id}.[/yellow]")
                        return

                    tid = transfer_row[0]
                    with conn.cursor() as cur_lock:
                         cur_lock.execute("SELECT 1 FROM inventory.transfers WHERE id = %s FOR UPDATE;", (tid,))
                         cur_lock.execute("SELECT 1 FROM inventory.transfer_items WHERE transfer_id = %s FOR UPDATE;", (tid,))
                         cur_lock.execute("SELECT 1 FROM inventory.stock WHERE warehouse_id = %s FOR UPDATE;", (from_warehouse_id,))

                    items = _get_transfer_items_by_transfer_id(tid)
                    user_items = [item for item in items if item.requested_by == current_user_id and item.status == 'planned']

                    if not user_items:
                        console.print("[yellow]У вас нет позиций для удаления в этом перемещении.[/yellow]")
                        return

                    choices = [(str(item.id), f"ID {item.id}: {item.product_name} (SKU: {item.product_sku}, кол-во: {item.quantity})") for item in user_items]
                    choices.append(("done", "Завершить удаление"))
                    selected_item_or_done = choice(
                        message="Выберите позицию для удаления или 'Завершить': ",
                        options=choices,
                        default=choices[0][0]
                    )

                    if selected_item_or_done == "done":
                        console.print(f"[green]Изменения в перемещении #{tid} сохранены.[/green]")
                        return

                    try:
                        selected_item_id = int(selected_item_or_done)
                        item_to_remove = next((item for item in user_items if item.id == selected_item_id), None)
                        if not item_to_remove:
                             raise ValueError
                    except ValueError:
                        render_error("Позиция не выбрана или не принадлежит вам.")
                        continue

                    max_removable_qty = item_to_remove.quantity
                    if max_removable_qty <= 0:
                        console.print(f"[yellow]Количество для позиции #{item_to_remove.id} равно 0, пропуск.[/yellow]")
                        continue

                    qty_to_remove_str = prompt(f"Введите количество для удаления (максимум {max_removable_qty}): ", validator=NonEmptyValidator()).strip()
                    try:
                        qty_to_remove = int(qty_to_remove_str)
                        if qty_to_remove <= 0 or qty_to_remove > max_removable_qty:
                            raise ValueError
                    except ValueError:
                        render_error(f"Количество должно быть положительным целым числом не больше {max_removable_qty}.")
                        continue

                    console.print(f"Удаление: {qty_to_remove} x {item_to_remove.product_name} (SKU: {item_to_remove.product_sku}) из перемещения #{tid}")
                    confirm_remove = yes_no_choice("Подтвердить?")
                    if not confirm_remove:
                        console.print("[yellow]Удаление отменено.[/yellow]")
                        continue

                    # Обновление transfer_item и возврат в сток
                    with conn.cursor() as cur_update:
                         if qty_to_remove == max_removable_qty:
                             cur_update.execute("""
                                 DELETE FROM inventory.transfer_items
                                 WHERE id = %s AND transfer_id = %s AND requested_by = %s AND status = 'planned';
                             """, (item_to_remove.id, tid, current_user_id))
                             console.print(f"[green]Удалена позиция #{item_to_remove.id} из перемещения #{tid}[/green]")
                         else:
                             new_qty = max_removable_qty - qty_to_remove
                             cur_update.execute("""
                                 UPDATE inventory.transfer_items
                                 SET quantity = %s
                                 WHERE id = %s AND transfer_id = %s AND requested_by = %s AND status = 'planned';
                             """, (new_qty, item_to_remove.id, tid, current_user_id))
                             console.print(f"[green]Уменьшено количество позиции #{item_to_remove.id} на {qty_to_remove}, осталось {new_qty} в перемещении #{tid}[/green]")

                         cur_update.execute(
                             "UPDATE inventory.stock SET quantity = quantity + %s WHERE warehouse_id = %s AND product_id = %s;",
                             (qty_to_remove, from_warehouse_id, item_to_remove.product_id)
                         )
                         console.print(f"[blue]Возвращено {qty_to_remove} x {item_to_remove.product_name} (SKU: {item_to_remove.product_sku}) на склад #{from_warehouse_id}.[/blue]")

        except Exception as e:
            render_error(f"Ошибка при удалении позиции из перемещения: {e}")
            return

