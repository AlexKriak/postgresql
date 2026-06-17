# src/handlers/warehouses.py
from dataclasses import dataclass
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_WAREHOUSES
from src.auth import ROLE_CATALOG_MANAGER
from src.helpers import get_city_id_name_choices, get_warehouse_choices
from typing import Optional
from src.helpers import yes_no_choice


@dataclass
class Warehouse:
    id: int
    city_id: str
    city_name: str
    address: str
    label: str | None
    is_central: bool


def _render_warehouse(warehouse: Warehouse) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(warehouse.id))
    table.add_row("Город", warehouse.city_name)
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


def _get_warehouse_count() -> int:
    """Возвращает количество складов"""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses")
        return cur.fetchone()[0]


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
            cur.execute("""
                SELECT w.id, w.city_id, c.name as city_name, w.address, w.label, w.is_central
                FROM catalog.warehouses w
                JOIN catalog.cities c ON w.city_id = c.id
                ORDER BY c.name
            """)
            warehouses: list[Warehouse] = cur.fetchall()

    for w in warehouses:
        table.add_row(
            str(w.id),
            w.city_name,
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
        cur.execute("""
                    SELECT w.id, w.city_id, c.name as city_name, w.address, w.label, w.is_central
                    FROM catalog.warehouses w
                    JOIN catalog.cities c ON w.city_id = c.id
                    WHERE w.id = %s
                """, (wid,))
        w: Optional[Warehouse] = cur.fetchone()

    if not w:
        render_error(f"Склад с ID {wid} не найден")
        return

    _render_warehouse(w)


@command("add warehouse", "добавить склад (интерактивно)", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def add_warehouse() -> None:

    conn = get_conn()

    # Выбор города через choice() - теперь из БД
    city_choices = get_city_id_name_choices()
    if not city_choices:
        render_error("Нет доступных городов. Сначала добавьте город в таблицу catalog.cities.")
        return

    choice_options = [(str(city_id), name) for city_id, name in city_choices]
    selected_city_id_str: str = choice(
        message="Город: ",
        options=choice_options,
        default=choice_options[0][0]
    )
    try:
        city_id = int(selected_city_id_str)
    except ValueError:
        render_error("Город не выбран.")
        return

    address = prompt("Адрес: ", validator=NonEmptyValidator()).strip()
    label: str | None = prompt("Метка (необязательно): ").strip() or None

    warehouse_count: int = _get_warehouse_count()
    if warehouse_count == 0:
        is_central = True
        console.print("[i]Это первый склад, он автоматически сделан центральным.[/i]")
    else:
        # Спрашиваем только если не первый склад
        is_central = yes_no_choice("Сделать центральным?")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO catalog.warehouses (city_id, address, label, is_central) VALUES (%s, %s, %s, %s) RETURNING id",
            (city_id, address, label, is_central),
        )
        new_id = cur.fetchone()[0]

    city_name = next((name for cid, name in city_choices if cid == city_id), "Unknown City")
    console.print(f"[green]Склад в городе {city_name} {'(центральный) ' if is_central else ''}добавлен (ID: {new_id})[/green]")


@command("edit warehouse", "редактировать склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def edit_warehouse(_id: str) -> None:
    try:
        wid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("""
            SELECT w.id, w.city_id, c.name as city_name, w.address, w.label, w.is_central
            FROM catalog.warehouses w
            JOIN catalog.cities c ON w.city_id = c.id
            WHERE w.id = %s
        """, (wid,))
        w: Optional[Warehouse] = cur.fetchone()

    if not w:
        render_error(f"Склад с ID {wid} не найден")
        return

    city_choices = get_city_id_name_choices()
    choice_options = [(str(city_id), name) for city_id, name in city_choices]
    selected_city_id_str: str = choice(
        message="Город: ",
        options=choice_options,
        default=str(w.city_id)
    )
    try:
        city_id = int(selected_city_id_str)
    except ValueError:
        render_error("Город не выбран.")
        return

    address = prompt("Адрес: ", default=w.address, validator=NonEmptyValidator()).strip()
    label: str | None = (
        prompt("Метка (необязательно): ", default=w.label or "").strip() or None
    )

    # Логика: если текущий склад центральный — не спрашиваем; иначе — спрашиваем
    if w.is_central:
        is_central = True
        console.print("[i]Текущий склад уже центральный, флаг сохранён.[/i]")
    else:
        is_central = yes_no_choice("Сделать центральным?")

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE catalog.warehouses
               SET city_id = %s, address = %s, label = %s, is_central = %s
               WHERE id = %s""",
            (city_id, address, label, is_central, wid),
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
        cur.execute("""
            SELECT w.id, w.city_id, c.name as city_name, w.address, w.label, w.is_central
            FROM catalog.warehouses w
            JOIN catalog.cities c ON w.city_id = c.id
            WHERE w.id = %s
        """, (wid,))
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

    answer = yes_no_choice("Удалить склад?")
    if answer:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.warehouses WHERE id = %s", (wid,))
        console.print(f"[green]Склад #{wid} удалён[/green]")
