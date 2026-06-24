# src/handlers/transfers.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table
import psycopg.errors as pg_errors
import datetime # Для работы с датами

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_INVENTORY_TRANSFERS # Предполагаем, что добавим категорию
from src.auth import ROLE_INVENTORY_MANAGER, auth_user
from src.helpers import get_warehouse_choices, get_username_by_id, yes_no_choice
from typing import Optional, List, Tuple

from src.handlers.transfer_items import _get_transfer_items_by_transfer_id


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


def _render_transfer_summary(transfer: Transfer) -> None:
    """Отображает краткую информацию о перемещении"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=20)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(transfer.id))
    table.add_row("Статус", transfer.status)
    table.add_row("Откуда", f"{transfer.from_city_name} ({transfer.from_label or 'без метки'})")
    table.add_row("Куда", f"{transfer.to_city_name} ({transfer.to_label or 'без метки'})")
    table.add_row("Создано", transfer.created_at.strftime("%Y-%m-%d %H:%M"))
    if transfer.started_at:
        table.add_row("Начало отгрузки", transfer.started_at.strftime("%Y-%m-%d %H:%M"))
    if transfer.arriving_at:
        table.add_row("Ожидаемое прибытие", transfer.arriving_at.strftime("%Y-%m-%d %H:%M"))
    if transfer.received_at:
        table.add_row("Получено", transfer.received_at.strftime("%Y-%m-%d %H:%M"))

    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Перемещение #{transfer.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _render_transfer_detailed(transfer: Transfer, items: List) -> None:
    """Отображает подробную информацию о перемещении и его позициях"""
    _render_transfer_summary(transfer)

    if not items:
        console.print("[i]В перемещении нет позиций.[/i]")
        return

    # Используем логику из transfer_items для отображения списка
    from src.handlers.transfer_items import _render_transfer_item_list
    _render_transfer_item_list(items)


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


def _get_planned_transfers(current_user_only: bool = False) -> List[Tuple[Transfer, List]]:
    """Получает список планируемых перемещений (опционально только текущего пользователя)."""
    conn = get_conn()
    user_id_filter = ""
    user_params = ()
    if current_user_only:
        user_id = auth_user().id
        user_id_filter = " AND ti.requested_by = %s"
        user_params = (user_id,)

    # Получаем все planned transfers и их items за один запрос
    # Группируем результаты вручную
    transfers_map = {}
    with conn.cursor(row_factory=class_row(Transfer)) as cur_transfer: # Используем Transfer для получения основной инфы
        # Сначала получим основные данные transfer
        cur_transfer.execute(f"""
            SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status,
                   t.created_at, t.started_at, t.arriving_at, t.received_at,
                   fw.city_name as from_city_name, fw.label as from_label,
                   tw.city_name as to_city_name, tw.label as to_label
            FROM inventory.transfers t
            JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
            JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
            WHERE t.status = 'planned'{user_id_filter}
            ORDER BY t.id
        """, user_params)
        transfer_rows = cur_transfer.fetchall()

    results = []
    for transfer_row in transfer_rows:
        transfer_obj = Transfer(
            id=transfer_row.id, from_warehouse_id=transfer_row.from_warehouse_id, to_warehouse_id=transfer_row.to_warehouse_id,
            status=transfer_row.status, created_at=transfer_row.created_at, started_at=transfer_row.started_at,
            arriving_at=transfer_row.arriving_at, received_at=transfer_row.received_at,
            from_city_name=transfer_row.from_city_name, from_label=transfer_row.from_label,
            to_city_name=transfer_row.to_city_name, to_label=transfer_row.to_label
        )
        items = _get_transfer_items_by_transfer_id(transfer_obj.id)
        results.append((transfer_obj, items))

    return results


@command("list transfers planned all", "список всех планируемых перемещений", CATEGORY_INVENTORY_TRANSFERS, [ROLE_INVENTORY_MANAGER])
def list_planned_transfers_all() -> None:
    transfers_with_items = _get_planned_transfers(current_user_only=False)

    if not transfers_with_items:
        console.print("[yellow]Нет планируемых перемещений.[/yellow]")
        return

    console.print("\n[yellow]Планируемые перемещения:[/yellow]")
    for transfer, items in transfers_with_items:
        _render_transfer_detailed(transfer, items)
        console.print("---")


@command("list transfers planned my", "список моих планируемых перемещений", CATEGORY_INVENTORY_TRANSFERS, [ROLE_INVENTORY_MANAGER])
def list_planned_transfers_my() -> None:
    transfers_with_items = _get_planned_transfers(current_user_only=True)

    if not transfers_with_items:
        console.print("[yellow]Нет ваших планируемых перемещений.[/yellow]")
        return

    console.print("\n[yellow]Ваши планируемые перемещения:[/yellow]")
    for transfer, items in transfers_with_items:
        _render_transfer_detailed(transfer, items)
        console.print("---")


@command("show transfer", "показать информацию о перемещении", CATEGORY_INVENTORY_TRANSFERS, [ROLE_INVENTORY_MANAGER])
def show_transfer(_id: str) -> None:
    try:
        tid = int(_id)
    except ValueError:
        render_error("ID перемещения должен быть числом.")
        return

    transfer = _get_transfer_by_id(tid)
    if not transfer:
        render_error(f"Перемещение с ID {tid} не найдено.")
        return

    items = _get_transfer_items_by_transfer_id(tid)
    _render_transfer_detailed(transfer, items)


@command("start shipping", "начать отгрузку перемещения", CATEGORY_INVENTORY_TRANSFERS, [ROLE_INVENTORY_MANAGER])
def start_shipping(_id: str) -> None:
    """Меняет статус перемещения с planned на shipping"""
    try:
        tid: int = int(_id)
    except ValueError:
        render_error("ID перемещения должен быть числом.")
        return

    current_user_id = auth_user().id
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN;")

            # Читаем перемещение С БЛОКИРОВКОЙ строки
            cur.execute("""
                SELECT status, from_warehouse_id, to_warehouse_id
                FROM inventory.transfers
                WHERE id = %s FOR UPDATE;
            """, (tid,))
            transfer_row = cur.fetchone()

            if not transfer_row:
                render_error(f"Перемещение с ID {tid} не найдено")
                cur.execute("ROLLBACK;")
                return

            current_status, from_wid, to_wid = transfer_row

            if current_status != "planned":
                render_error(f"Невозможно начать отгрузку перемещения со статусом '{current_status}'. Ожидается 'planned'.")
                cur.execute("ROLLBACK;")
                return

            console.print(f"Перемещение #{tid} (ID: {from_wid} -> {to_wid}, статус: {current_status})")
            answer: bool = yes_no_choice(f"Начать отгрузку перемещения #{tid}?")
            if not answer:
                cur.execute("ROLLBACK;") # Откатываем транзакцию, если пользователь отказался
                console.print("[yellow]Действие отменено.[/yellow]")
                return

            now = datetime.datetime.now()
            cur.execute("""
                UPDATE inventory.transfers
                SET status = 'shipping', started_at = %s
                WHERE id = %s AND status = 'planned'
            """, (now, tid))

            rows_affected = cur.rowcount
            if rows_affected == 0:
                # Это означает, что между SELECT FOR UPDATE и UPDATE статус изменился
                render_error(f"Не удалось начать отгрузку перемещения #{tid}. Его статус мог измениться.")
                cur.execute("ROLLBACK;")
            else:
                cur.execute("COMMIT;")
                console.print(f"[green]Отгрузка перемещения #{tid} начата (статус: shipping).[/green]")

    except Exception as e:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK;")
        render_error(f"Ошибка при начале отгрузки перемещения: {e}")
