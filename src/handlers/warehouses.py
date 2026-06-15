# src/handlers/warehouses.py
from dataclasses import dataclass
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import PromptSession
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_WAREHOUSES
from src.auth import ROLE_CATALOG_MANAGER
from src.helpers import get_city_choices, get_warehouse_choices
from typing import Optional


@dataclass
class Warehouse:
    id: int
    city: str
    address: str
    label: str | None
    is_central: bool


def _render_warehouse(warehouse: Warehouse) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(warehouse.id))
    table.add_row("Город", warehouse.city)
    table.add_row("Адрес", warehouse.address)
    table.add_row("Метка", warehouse.label or "")
    table.add_row("Центральный", "Да" if warehouse.is_central else "Нет")

    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Склад #{warehouse.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


def _ensure_one_central_exists(conn, new_is_central: bool, new_id: Optional[int] = None) -> None:
    """Гарантирует, что существует ровно один центральный склад."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
        central_count = cur.fetchone()[0]

        if new_is_central:
            # Если делаем новый склад центральным — сбрасываем флаг у всех остальных
            if central_count > 0:
                cur.execute("UPDATE catalog.warehouses SET is_central = false WHERE is_central = true AND id != %s", (new_id,))
        else:
            # Если не делаем центральным — должен существовать хотя бы один
            if central_count == 0:
                raise ValueError("Должен существовать хотя бы один центральный склад.")


@command("list warehouses", "список всех складов", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def list_warehouses() -> None:
    conn = get_conn()
    table = Table(title="Склады", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Город", style="green", min_width=20)
    table.add_column("Адрес", style="yellow", min_width=30)
    table.add_column("Метка", style="magenta", min_width=15)
    table.add_column("Центральный", style="red", min_width=10)

    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses ORDER BY city")
        warehouses: list[Warehouse] = cur.fetchall()

    for w in warehouses:
        table.add_row(
            str(w.id),
            w.city,
            w.address,
            w.label or "",
            "Да" if w.is_central else "Нет",
        )
    console.print(table)


@command("show warehouse", "информация о складе", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def show_warehouse(_id: str) -> None:
    try:
        wid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (wid,))
        w: Optional[Warehouse] = cur.fetchone()

    if not w:
        render_error(f"Склад с ID {wid} не найден")
        return

    _render_warehouse(w)


@command("add warehouse", "добавить склад (интерактивно)", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def add_warehouse() -> None:
    conn = get_conn()

    # Выбор города через choices
    city = prompt(
        "Город: ",
        choices=get_city_choices(),
        default=get_city_choices()[0]
    ).strip()

    address = prompt("Адрес: ", validator=NonEmptyValidator()).strip()
    label = prompt("Метка (необязательно): ").strip() or None

    # Проверяем, есть ли уже центральный склад
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
        central_count = cur.fetchone()[0]

    is_central_default = "y" if central_count == 0 else "n"
    is_central_answer: str = prompt(
        f"Центральный склад? (y/n, д/н) [по умолчанию {'Да' if is_central_default == 'y' else 'Нет'}]: "
    ).strip().lower()

    is_central = is_central_default == "y" if not is_central_answer else YesNoValidator.is_yes(is_central_answer)

    try:
        _ensure_one_central_exists(conn, is_central)
    except ValueError as e:
        render_error(str(e))
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO catalog.warehouses (city, address, label, is_central) VALUES (%s, %s, %s, %s) RETURNING id",
            (city, address, label, is_central),
        )
        new_id = cur.fetchone()[0]

    console.print(f"[green]Склад в городе {city} {'(центральный) ' if is_central else ''}добавлен (ID: {new_id})[/green]")


@command("edit warehouse", "редактировать склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def edit_warehouse(_id: str) -> None:
    try:
        wid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (wid,))
        w: Optional[Warehouse] = cur.fetchone()

    if not w:
        render_error(f"Склад с ID {wid} не найден")
        return

    city = prompt(
        "Город: ",
        choices=get_city_choices(),
        default=w.city
    ).strip()
    address = prompt("Адрес: ", default=w.address, validator=NonEmptyValidator()).strip()
    label: str | None = (
        prompt("Метка (необязательно): ", default=w.label or "").strip() or None
    )

    # Логика is_central
    is_central_current_display = "Да" if w.is_central else "Нет"
    is_central_answer = prompt(
        f"Центральный склад? (y/n, д/н) [текущее: {is_central_current_display}]: "
    ).strip().lower()
    is_central = w.is_central if not is_central_answer else YesNoValidator.is_yes(is_central_answer)

    try:
        _ensure_one_central_exists(conn, is_central, wid)
    except ValueError as e:
        render_error(str(e))
        return

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE catalog.warehouses
               SET city = %s, address = %s, label = %s, is_central = %s
               WHERE id = %s""",
            (city, address, label, is_central, wid),
        )
    console.print(f"[green]Склад #{wid} обновлён[/green]")


@command("delete warehouse", "удалить склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def delete_warehouse(_id: str) -> None:
    try:
        wid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (wid,))
        w: Optional[Warehouse] = cur.fetchone()

    if not w:
        render_error(f"Склад с ID {wid} не найден")
        return

    if w.is_central:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
            central_count = cur.fetchone()[0]
        if central_count <= 1:
            render_error("Невозможно удалить единственный центральный склад.")
            return

    _render_warehouse(w)

    answer: str = prompt("Вы уверены? (y/n, д/н): ", validator=YesNoValidator())
    if YesNoValidator.is_yes(answer):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.warehouses WHERE id = %s", (wid,))
        console.print(f"[green]Склад #{wid} удалён[/green]")