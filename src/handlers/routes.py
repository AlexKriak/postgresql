# src/handlers/routes.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table
import psycopg.errors as pg_errors

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, PriceValidator
from commands import command, CATEGORY_ROUTES
from src.auth import ROLE_INVENTORY_MANAGER
from src.helpers import get_city_id_name_choices, yes_no_choice
from typing import Optional, List, Tuple
import re

@dataclass
class Route:
    from_city_id: int
    to_city_id: int
    duration: str
    total_threshold: Decimal
    from_city_name: str
    to_city_name: str

# Для отображения информации о маршруте
def _render_route(route: Route) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=20)
    table.add_column("Значение", style="white")
    table.add_row("Город отправки", route.from_city_name)
    table.add_row("Город получения", route.to_city_name)
    table.add_row("Время доставки", route.duration)
    table.add_row("Мин. сумма для перемещения", f"{route.total_threshold:.2f}")

    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Маршрут: {route.from_city_name} -> {route.to_city_name}[/bold green]",
        border_style="green",
    )
    console.print(panel)

# Список всех маршрутов с городами
def _get_routes_list() -> List[Route]:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Route)) as cur:
        cur.execute(
            "SELECT r.from_city_id, r.to_city_id, r.duration, r.total_threshold,"
            "fc.name AS from_city_name, tc.name AS to_city_name"
            "FROM inventory.routes r"
            "JOIN catalog.cities fc ON r.from_city_id = fc.id"
            "JOIN catalog.cities tc ON r.to_city_id = tc.id"
            "ORDER BY fc.name, tc.name"
        )
        return cur.fetchall()


@command("list routes", "список всех маршрутов", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def list_routes() -> None:
    routes = _get_routes_list()

    if not routes:
        console.print("[yellow]Маршрутов пока нет.[/yellow]")
        return

    table = Table(title="Маршруты", show_header=True, header_style="bold cyan")
    table.add_column("Город отправки", style="green", min_width=15)
    table.add_column("Город получения", style="green", min_width=15)
    table.add_column("Время доставки", style="yellow", min_width=15)
    table.add_column("Мин. сумма", style="magenta", min_width=12, justify="right")

    for r in routes:
        table.add_row(r.from_city_name, r.to_city_name, r.duration, f"{r.total_threshold:.2f}")

    console.print(table)

# Список существующих маршрутов на вход from_id, to_id, from_name, to_name
def _get_existing_routes_for_selection() -> List[Tuple[int, int, str, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.from_city_id, r.to_city_id, fc.name, tc.name"
            "FROM inventory.routes r"
            "JOIN catalog.cities fc ON r.from_city_id = fc.id"
            "JOIN catalog.cities tc ON r.to_city_id = tc.id"
            "ORDER BY fc.name, tc.name"
        )
        return cur.fetchall()

# Список всех возможных пар городов, не используемых в других роутах
def _get_available_city_pairs_for_add() -> List[Tuple[int, int, str, str]]:
    conn = get_conn()
    with conn.cursor() as cur:
        # Запрос: получить все возможные пары (c1, c2), где c1 != c2 и пара не в routes
        cur.execute(
            "SELECT c1.id, c2.id, c1.name, c2.name"
            "FROM catalog.cities c1"
            "CROSS JOIN catalog.cities c2"
            "WHERE c1.id != c2.id"
            "AND NOT EXISTS ("
            "SELECT 1 FROM inventory.routes r"
            "WHERE r.from_city_id = c1.id AND r.to_city_id = c2.id"
            ")"
            "ORDER BY c1.name, c2.name"
        )
        return cur.fetchall()


def _validate_duration_format(duration_str: str) -> bool:
    if re.match(r'^\d{2}:\d{2}:\d{2}$', duration_str):
        return True
    return False


@command("add route", "добавить маршрут (интерактивно)", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def add_route() -> None:
    conn = get_conn()

    available_pairs = _get_available_city_pairs_for_add()

    if not available_pairs:
        console.print("[yellow]Нет доступных пар городов для добавления маршрута.[/yellow]")
        return

    choices = [(f"{from_id}-{to_id}", f"{f_name} -> {t_name}") for from_id, to_id, f_name, t_name in available_pairs]

    if not choices:
        console.print("[yellow]Нет доступных пар городов для добавления маршрута.[/yellow]")
        return

    selected_key = choice(
        message="Выберите пару городов (Откуда -> Куда): ",
        options=choices,
        default=choices[0][0]
    )

    try:
        from_id_str, to_id_str = selected_key.split('-', 1)
        from_city_id = int(from_id_str)
        to_city_id = int(to_id_str)
    except (ValueError, IndexError):
        render_error("Ошибка при разборе выбранной пары городов.")
        return

    _, _, from_city_name, to_city_name = next((f_id, t_id, f_name, t_name) for f_id, t_id, f_name, t_name in available_pairs if f_id == from_city_id and t_id == to_city_id)

    duration_str = prompt("Время доставки (в формате HH:MM:SS или 'D days HH:MM:SS'): ", validator=NonEmptyValidator()).strip()
    if not _validate_duration_format(duration_str):
        render_error(f"Неверный формат времени: '{duration_str}'. Ожидается HH:MM:SS или 'D days HH:MM:SS'.")
        return

    threshold_str = prompt("Минимальная сумма для перемещения: ", validator=PriceValidator()).strip()
    try:
        threshold = Decimal(threshold_str)
        if threshold < 0:
             raise ValueError # Не отрицательная сумма
    except ValueError:
        render_error(f"Неверная сумма: '{threshold_str}'. Должно быть неотрицательное число.")
        return

    console.print(f"\n[bold]Подтверждаете добавление маршрута?[/bold]")
    console.print(f"  {from_city_name} -> {to_city_name}")
    console.print(f"  Время: {duration_str}")
    console.print(f"  Мин. сумма: {threshold:.2f}")
    if not yes_no_choice("Продолжить?"):
        console.print("[yellow]Добавление маршрута отменено.[/yellow]")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO inventory.routes (from_city_id, to_city_id, duration, total_threshold)"
                "VALUES (%s, %s, %s::interval, %s)", (from_city_id, to_city_id, duration_str, threshold)
            )
        console.print(f"[green]Маршрут {from_city_name} -> {to_city_name} добавлен.[/green]")
    except pg_errors.UniqueViolation:
        render_error(f"Маршрут {from_city_name} -> {to_city_name} уже существует.")
    except Exception as e:
        render_error(f"Ошибка при добавлении маршрута: {e}")


@command("show route", "показать информацию о маршруте", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def show_route() -> None:
    routes = _get_existing_routes_for_selection()

    if not routes:
        console.print("[yellow]Нет существующих маршрутов для просмотра.[/yellow]")
        return

    choices = [(f"{from_id}-{to_id}", f"{f_name} -> {t_name}") for from_id, to_id, f_name, t_name in routes]

    selected_key = choice(
        message="Выберите маршрут (Откуда -> Куда): ",
        options=choices,
        default=choices[0][0]
    )

    try:
        from_id_str, to_id_str = selected_key.split('-', 1)
        from_city_id = int(from_id_str)
        to_city_id = int(to_id_str)
    except (ValueError, IndexError):
        render_error("Ошибка при разборе выбранного маршрута.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Route)) as cur:
        cur.execute(
            "SELECT r.from_city_id, r.to_city_id, r.duration, r.total_threshold,"
            "fc.name AS from_city_name, tc.name AS to_city_name"
            "FROM inventory.routes r"
            "JOIN catalog.cities fc ON r.from_city_id = fc.id"
            "JOIN catalog.cities tc ON r.to_city_id = tc.id"
            "WHERE r.from_city_id = %s AND r.to_city_id = %s", (from_city_id, to_city_id)
        )
        route = cur.fetchone()

    if not route:
        render_error(f"Маршрут {from_city_id} -> {to_city_id} не найден.")
        return

    _render_route(route)


@command("edit route", "редактировать маршрут", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def edit_route() -> None:
    routes = _get_existing_routes_for_selection()

    if not routes:
        console.print("[yellow]Нет существующих маршрутов для редактирования.[/yellow]")
        return

    choices = [(f"{from_id}-{to_id}", f"{f_name} -> {t_name}") for from_id, to_id, f_name, t_name in routes]

    selected_key = choice(
        message="Выберите маршрут (Откуда -> Куда) для редактирования: ",
        options=choices,
        default=choices[0][0]
    )

    try:
        from_id_str, to_id_str = selected_key.split('-', 1)
        from_city_id = int(from_id_str)
        to_city_id = int(to_id_str)
    except (ValueError, IndexError):
        render_error("Ошибка при разборе выбранного маршрута.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Route)) as cur:
        cur.execute(
            "SELECT r.from_city_id, r.to_city_id, r.duration, r.total_threshold,"
            "fc.name AS from_city_name, tc.name AS to_city_name"
            "FROM inventory.routes r"
            "JOIN catalog.cities fc ON r.from_city_id = fc.id"
            "JOIN catalog.cities tc ON r.to_city_id = tc.id"
            "WHERE r.from_city_id = %s AND r.to_city_id = %s", (from_city_id, to_city_id)
        )
        route = cur.fetchone()

    if not route:
        render_error(f"Маршрут {from_city_id} -> {to_city_id} не найден.")
        return

    _render_route(route)

    duration_str = prompt(f"Время доставки (текущее: {route.duration}): ", default=route.duration, validator=NonEmptyValidator()).strip()
    if not _validate_duration_format(duration_str):
        render_error(f"Неверный формат времени: '{duration_str}'. Ожидается HH:MM'.")
        return

    threshold_str = prompt(f"Минимальная сумма (текущая: {route.total_threshold:.2f}): ", default=str(route.total_threshold), validator=PriceValidator()).strip()
    try:
        threshold = Decimal(threshold_str)
        if threshold < 0:
             raise ValueError
    except ValueError:
        render_error(f"Неверная сумма: '{threshold_str}'. Должно быть неотрицательное число.")
        return

    console.print(f"\n[bold]Подтверждаете обновление маршрута?[/bold]")
    console.print(f"  {route.from_city_name} -> {route.to_city_name}")
    console.print(f"  Новое время: {duration_str}")
    console.print(f"  Новая мин. сумма: {threshold:.2f}")
    if not yes_no_choice("Продолжить?"):
        console.print("[yellow]Редактирование маршрута отменено.[/yellow]")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory.routes"
                "SET duration = %s::interval, total_threshold = %s"
                "WHERE from_city_id = %s AND to_city_id = %s", (duration_str, threshold, from_city_id, to_city_id)
            )
        console.print(f"[green]Маршрут {route.from_city_name} -> {route.to_city_name} обновлён.[/green]")
    except Exception as e:
        render_error(f"Ошибка при обновлении маршрута: {e}")


@command("delete route", "удалить маршрут", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def delete_route() -> None:
    routes = _get_existing_routes_for_selection()

    if not routes:
        console.print("[yellow]Нет существующих маршрутов для удаления.[/yellow]")
        return

    choices = [(f"{from_id}-{to_id}", f"{f_name} -> {t_name}") for from_id, to_id, f_name, t_name in routes]

    selected_key = choice(
        message="Выберите маршрут (Откуда -> Куда) для удаления: ",
        options=choices,
        default=choices[0][0]
    )

    try:
        from_id_str, to_id_str = selected_key.split('-', 1)
        from_city_id = int(from_id_str)
        to_city_id = int(to_id_str)
    except (ValueError, IndexError):
        render_error("Ошибка при разборе выбранного маршрута.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Route)) as cur:
        cur.execute(
            "SELECT r.from_city_id, r.to_city_id, r.duration, r.total_threshold,"
            "fc.name AS from_city_name, tc.name AS to_city_name"
            "FROM inventory.routes r"
            "JOIN catalog.cities fc ON r.from_city_id = fc.id"
            "JOIN catalog.cities tc ON r.to_city_id = tc.id"
            "WHERE r.from_city_id = %s AND r.to_city_id = %s", (from_city_id, to_city_id)
        )
        route = cur.fetchone()

    if not route:
        render_error(f"Маршрут {from_city_id} -> {to_city_id} не найден.")
        return

    _render_route(route)

    if not yes_no_choice("Удалить этот маршрут?"):
        console.print("[yellow]Удаление маршрута отменено.[/yellow]")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM inventory.routes"
                "WHERE from_city_id = %s AND to_city_id = %s", (from_city_id, to_city_id)
            )
        console.print(f"[green]Маршрут {route.from_city_name} -> {route.to_city_name} удалён.[/green]")
    except Exception as e:
        render_error(f"Ошибка при удалении маршрута: {e}")

