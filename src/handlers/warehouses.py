# src/handlers/warehouses.py
from dataclasses import dataclass

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_WAREHOUSES

from src.auth import ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER

cities = [
    "Москва",
    "Санкт-Петербург",
    "Новосибирск",
    "Екатеринбург",
    "Казань",
    "Нижний Новгород",
    "Челябинск",
    "Самара",
    "Омск",
    "Ростов-на-Дону",
    "Уфа",
    "Красноярск",
    "Воронеж",
    "Пермь",
    "Волгоград",
]

city_completer = WordCompleter(cities, ignore_case=True, sentence=True)
city_validator = ChoiceValidator(
    cities, message="Город должен быть из списка. Используйте Tab для автодополнения."
)


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


@command("list warehouses", "список всех складов", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER])
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

    for warehouse in warehouses:
        table.add_row(
            str(warehouse.id),
            warehouse.city,
            warehouse.address,
            warehouse.label or "",
            "Да" if warehouse.is_central else "Нет",
        )
    console.print(table)


@command("show warehouse", "информация о складе", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER])
def show_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    _render_warehouse(warehouse)


def _ensure_one_central_exists(conn, new_is_central: bool, new_id: int | None = None):
    """Проверяет и гарантирует, что существует только один центральный склад"""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
        central_count = cur.fetchone()[0]

        if central_count == 0:
            # Если нет центрального склада и мы добавляем/делаем центральным новый - ок
            if new_is_central:
                return
            else:
                # Мы не можем сбросить флаг с последнего центрального склада, если не устанавливаем его на новый
                if new_id:
                     # Проверим, был ли старый склад центральным
                     cur.execute("SELECT is_central FROM catalog.warehouses WHERE id = %s", (new_id,))
                     old_is_central = cur.fetchone()[0]
                     if old_is_central and not new_is_central:
                         raise ValueError("Должен существовать хотя бы один центральный склад. Невозможно сбросить флаг 'is_central' у единственного центрального склада.")
                # Если мы не в контексте редактирования (new_id None), и просто добавляем обычный склад, это ошибка
                elif not new_is_central:
                     raise ValueError("Должен существовать хотя бы один центральный склад.")

        elif central_count == 1:
            # Один центральный есть
            if new_is_central:
                # Хотим сделать центральным новый или текущий - сбросим старый
                cur.execute("SELECT id FROM catalog.warehouses WHERE is_central = true AND id != %s", (new_id,))
                old_central_id = cur.fetchone()
                if old_central_id:
                    cur.execute("UPDATE catalog.warehouses SET is_central = false WHERE id = %s", (old_central_id[0],))
        else:
            # Ошибка: больше одного центрального
            raise ValueError("Обнаружено больше одного центрального склада. Пожалуйста, исправьте данные.")


@command("add warehouse", "добавить склад (интерактивно)", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def add_warehouse() -> None:
    conn = get_conn()
    city = prompt("Город: ", validator=city_validator, completer=city_completer).strip()
    address = prompt("Адрес: ", validator=NonEmptyValidator()).strip()
    label = prompt("Метка (необязательно): ").strip() or None

    # Проверяем, есть ли уже центральный склад
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
        central_count = cur.fetchone()[0]

    is_central_default = "n"
    if central_count == 0:
        is_central_default = "y" # Если нет центрального, предлагаем сделать текущий

    is_central_answer = prompt(f"Центральный склад? (y/n, д/н) [по умолчанию {'Да' if is_central_default == 'y' else 'Нет'}]: ")
    is_central = YesNoValidator.is_yes(is_central_answer) if is_central_answer else (is_central_default == 'y')

    try:
        _ensure_one_central_exists(conn, is_central)
    except ValueError as e:
        render_error(str(e))
        return

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO catalog.warehouses (city, address, label, is_central) VALUES (%s, %s, %s, %s)",
            (city, address, label, is_central),
        )
    if label:
        console.print(f"[green]Склад в городе {city} ({label}) {'(центральный) ' if is_central else ''}добавлен [/green]")
    else:
        console.print(f"[green]Склад в городе {city} {'(центральный) ' if is_central else ''}добавлен [/green]")


@command("edit warehouse", "редактировать склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def edit_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    city = prompt(
        "Город: ",
        default=warehouse.city,
        validator=city_validator,
        completer=city_completer,
    ).strip()
    address = prompt(
        "Адрес: ", default=warehouse.address, validator=NonEmptyValidator()
    ).strip()
    label = (
        prompt("Метка (необязательно): ", default=warehouse.label or "").strip() or None
    )

    # Логика для is_central
    is_central_current_display = "Да" if warehouse.is_central else "Нет"
    is_central_answer = prompt(f"Центральный склад? (y/n, д/н) [текущее: {is_central_current_display}]: ")
    if is_central_answer:
        is_central = YesNoValidator.is_yes(is_central_answer)
    else:
        is_central = warehouse.is_central # Оставить как было

    try:
        _ensure_one_central_exists(conn, is_central, _id)
    except ValueError as e:
        render_error(str(e))
        return

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE catalog.warehouses SET city = %s, address = %s, label = %s, is_central = %s
            WHERE id = %s""",
            (city, address, label, is_central, _id),
        )
    if label:
        console.print(f"[green]Склад в городе {city} ({label}) {'(центральный) ' if is_central else ''}обновлен [/green]")
    else:
        console.print(f"[green]Склад в городе {city} {'(центральный) ' if is_central else ''}обновлен [/green]")


@command("delete warehouse", "удалить склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def delete_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    if warehouse.is_central:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true")
            central_count = cur.fetchone()[0]
        if central_count <= 1:
            render_error("Невозможно удалить единственный центральный склад.")
            return

    _render_warehouse(warehouse)

    answer = prompt("Вы уверены? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.warehouses WHERE id = %s", (_id,))
        if warehouse.label:
            console.print(
                f"[green]Склад в городе {warehouse.city} ({warehouse.label}) {'(центральный) ' if warehouse.is_central else ''}удален [/green]"
            )
        else:
            console.print(f"[green]Склад в городе {warehouse.city} {'(центральный) ' if warehouse.is_central else ''}удален [/green]")
