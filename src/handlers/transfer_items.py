# src/handlers/transfer_items.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_INVENTORY_TRANSFER_ITEMS
from src.auth import ROLE_INVENTORY_MANAGER
from src.helpers import get_warehouse_choices, get_username_by_id, yes_no_choice
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
def add_transfer_item(_transfer_id: str) -> None:
    """Интерактивное добавление позиции в существующее перемещение со статусом planned"""
    try:
        tid = int(_transfer_id)
    except ValueError:
        render_error("ID перемещения должен быть числом.")
        return

    conn = get_conn()
    current_user_id = auth_user().id

    # Получим информацию о перемещении (и проверим его статус и склады)
    from src.handlers.transfers import _get_transfer_by_id # Импортируем из transfers
    transfer = _get_transfer_by_id(tid)
    if not transfer:
        render_error(f"Перемещение с ID {tid} не найдено.")
        return
    if transfer.status != 'planned':
        render_error(f"Нельзя добавить позицию в перемещение со статусом '{transfer.status}'. Ожидается 'planned'.")
        return

    from_warehouse_id = transfer.from_warehouse_id
    to_warehouse_id = transfer.to_warehouse_id

    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute(
                SELECT id, status, from_warehouse_id, to_warehouse_id FROM inventory.transfers
                WHERE id = %s AND status = 'planned' FOR UPDATE;", (tid,)
            )
            locked_transfer = cur.fetchone()
            if not locked_transfer or locked_transfer[1] != 'planned':
                 render_error(f"Перемещение #{tid} больше не в статусе 'planned'. Невозможно добавить позицию.")
                 cur.execute("ROLLBACK;")
                 return

            cur.execute(
                "SELECT s.product_id, p.name, p.sku, s.quantity"
                "FROM inventory.stock s"
                "JOIN catalog.products p ON s.product_id = p.id"
                "WHERE s.warehouse_id = %s AND s.quantity > 0"
                "ORDER BY p.name", (from_warehouse_id,)
            )
            stock_items = cur.fetchall()

            if not stock_items:
                console.print("[yellow]На складе отправления (ID: {from_warehouse_id}) нет доступных товаров.[/yellow]")
                cur.execute("ROLLBACK;")
                return

            choices = [(str(pid), f"{name} (SKU: {sku}, в наличии: {qty})") for pid, name, sku, qty in stock_items]
            choices.append(("done", "Завершить добавление"))
            selected_prod_or_done = choice(
                message="Выберите товар для добавления или 'Завершить': ",
                options=choices,
                default=choices[0][0]
            )

            if selected_prod_or_done == "done":
                 cur.execute("COMMIT;")
                 console.print("[green]Добавление позиций в перемещение #{tid} завершено.[/green]")
                 return

            try:
                selected_product_id = int(selected_prod_or_done)
                max_available_qty = next(qty for pid, name, sku, qty in stock_items if pid == selected_product_id)
            except (ValueError, StopIteration):
                render_error("Товар не выбран или ошибка данных.")
                cur.execute("ROLLBACK;")
                return

            max_qty_str = prompt(f"Введите количество (максимум {max_available_qty}): ", validator=NonEmptyValidator()).strip()
            try:
                qty_to_add = int(max_qty_str)
                if qty_to_add <= 0 or qty_to_add > max_available_qty:
                    raise ValueError
            except ValueError:
                render_error(f"Количество должно быть положительным целым числом не больше {max_available_qty}.")
                cur.execute("ROLLBACK;")
                return

            prod_name, prod_sku = next((name, sku) for pid, name, sku, qty in stock_items if pid == selected_product_id)
            console.print(f"Добавление: {qty_to_add} x {prod_name} (SKU: {prod_sku}) в перемещение #{tid} (ID: {from_warehouse_id} -> {to_warehouse_id})")
            confirm_add = yes_no_choice("Подтвердить?")
            if not confirm_add:
                console.print("[yellow]Добавление отменено.[/yellow]")
                cur.execute("COMMIT;")
                return

            cur.execute(
                "SELECT id, quantity FROM inventory.transfer_items"
                "WHERE transfer_id = %s AND product_id = %s AND requested_by = %s AND status = 'planned'"
                "LIMIT 1;", (tid, selected_product_id, current_user_id)
            )
            existing_item_for_user_prod = cur.fetchone()

            if existing_item_for_user_prod:
                existing_item_id, current_qty = existing_item_for_user_prod
                new_qty = current_qty + qty_to_add
                console.print(f"[yellow]Внимание: товар '{prod_name}' уже добавлен вами в перемещение. Количество будет увеличено с {current_qty} до {new_qty}.[/yellow]")
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

            add_more = yes_no_choice("Добавить ещё одну позицию в это же перемещение?")
            if add_more:
                 cur.execute("COMMIT;")
                 add_transfer_item(_transfer_id)
                 return
            else:
                 cur.execute("COMMIT;")
                 console.print(f"[green]Изменения в перемещении #{tid} сохранены.[/green]")
                 return

    except Exception as e:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK;")
        render_error(f"Ошибка при добавлении позиции в перемещение: {e}")


@command("remove transfer item", "удалить позицию из перемещения (только planned)", CATEGORY_INVENTORY_TRANSFER_ITEMS, [ROLE_INVENTORY_MANAGER])
def remove_transfer_item(_transfer_id: str) -> None:
    """Интерактивное удаление позиции со статусом planned"""
    try:
        tid = int(_transfer_id)
    except ValueError:
        render_error("ID перемещения должен быть числом.")
        return

    conn = get_conn()
    current_user_id = auth_user().id

    # Получим информацию о перемещении (и проверим его статус)
    from src.handlers.transfers import _get_transfer_by_id
    transfer = _get_transfer_by_id(tid)
    if not transfer:
        render_error(f"Перемещение с ID {tid} не найдено.")
        return
    if transfer.status != 'planned':
        render_error(f"Нельзя удалить позицию из перемещения со статусом '{transfer.status}'. Ожидается 'planned'.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute(
                "SELECT id, status FROM inventory.transfers"
                "WHERE id = %s AND status = 'planned' FOR UPDATE;", (tid,)
            )
            locked_transfer = cur.fetchone()
            if not locked_transfer or locked_transfer[1] != 'planned':
                 render_error(f"Перемещение #{tid} больше не в статусе 'planned'. Невозможно удалить позицию.")
                 cur.execute("ROLLBACK;")
                 return

            while True:
                items = _get_transfer_items_by_transfer_id(tid)
                user_items = [item for item in items if item.requested_by == current_user_id and item.status == 'planned']

                if not user_items:
                    console.print("[yellow]У вас больше нет позиций для удаления в этом перемещении.[/yellow]")
                    cur.execute("COMMIT;")
                    return

                choices = [(str(item.id), f"ID {item.id}: {item.product_name} (SKU: {item.product_sku}, кол-во: {item.quantity})") for item in user_items]
                choices.append(("done", "Завершить удаление"))
                selected_item_or_done = choice(
                    message="Выберите позицию для удаления или 'Завершить': ",
                    options=choices,
                    default=choices[0][0]
                )

                if selected_item_or_done == "done":
                    cur.execute("COMMIT;")
                    console.print(f"[green]Изменения в перемещении #{tid} сохранены.[/green]")
                    return

                try:
                    selected_item_id = int(selected_item_or_done)
                    item_to_remove = next((item for item in user_items if item.id == selected_item_id), None)
                    if not item_to_remove:
                         raise ValueError
                except ValueError:
                    render_error("Позиция не выбрана или не принадлежит вам.")
                    continue # Возврат к выбору позиции

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
                if qty_to_remove == max_removable_qty:
                    cur.execute("""
                        DELETE FROM inventory.transfer_items
                        WHERE id = %s AND transfer_id = %s AND requested_by = %s AND status = 'planned';
                    """, (item_to_remove.id, tid, current_user_id))
                    console.print(f"[green]Удалена позиция #{item_to_remove.id} из перемещения #{tid}[/green]")
                else:
                    new_qty = max_removable_qty - qty_to_remove
                    cur.execute("""
                        UPDATE inventory.transfer_items
                        SET quantity = %s
                        WHERE id = %s AND transfer_id = %s AND requested_by = %s AND status = 'planned';
                    """, (new_qty, item_to_remove.id, tid, current_user_id))
                    console.print(f"[green]Уменьшено количество позиции #{item_to_remove.id} на {qty_to_remove}, осталось {new_qty} в перемещении #{tid}[/green]")

    except Exception as e:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK;")
        render_error(f"Ошибка при удалении позиции из перемещения: {e}")


