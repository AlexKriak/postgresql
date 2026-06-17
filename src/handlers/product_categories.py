# src/handlers/product_categories.py
from dataclasses import dataclass
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator
from commands import command, CATEGORY_PRODUCT_CATEGORY
from src.auth import ROLE_CATALOG_MANAGER
from src.helpers import get_category_choices
from typing import Optional


@dataclass
class ProductCategory:
    id: int
    name: str


def _render_category(category: ProductCategory) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=10)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(category.id))
    table.add_row("Название", category.name)
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Категория #{category.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


@command("list product_categories", "список всех категорий", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def list_categories() -> None:
    conn = get_conn()
    table = Table(title="Категории", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Название", style="green", min_width=20)

    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories ORDER BY name")
        categories: list[ProductCategory] = cur.fetchall()

    for c in categories:
        table.add_row(str(c.id), c.name)
    console.print(table)


@command("show product_category", "информация о категории", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def show_category(_id: str) -> None:
    try:
        cid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (cid,))
        c: ProductCategory | None = cur.fetchone()

    if not c:
        render_error(f"Категория с ID {cid} не найдена")
        return

    _render_category(c)


@command("add product_category", "добавить категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def add_category() -> None:
    name: str = prompt("Название категории: ", validator=NonEmptyValidator()).strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO catalog.product_categories (name) VALUES (%s) RETURNING id",
                (name,),
            )
            new_id = cur.fetchone()[0]
        console.print(f"[green]Категория '{name}' добавлена (ID: {new_id})[/green]")
    except Exception as e:
        render_error(f"Ошибка добавления категории: {e}")


@command("edit product_category", "редактировать категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def edit_category(_id: str) -> None:
    try:
        cid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (cid,))
        c: ProductCategory | None = cur.fetchone()

    if not c:
        render_error(f"Категория с ID {cid} не найдена")
        return

    new_name: str = prompt("Новое название: ", default=c.name, validator=NonEmptyValidator()).strip()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE catalog.product_categories SET name = %s WHERE id = %s",
                (new_name, cid),
            )
        console.print(f"[green]Категория '#{cid}' обновлена[/green]")
    except Exception as e:
        render_error(f"Ошибка редактирования категории: {e}")


@command("delete product_category", "удалить категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def delete_category(_id: str) -> None:
    try:
        cid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (cid,))
        c: ProductCategory | None = cur.fetchone()

    if not c:
        render_error(f"Категория с ID {cid} не найдена")
        return

    _render_category(c)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.products WHERE category_id = %s", (cid,))
        count = cur.fetchone()[0]

    if count > 0:
        render_error(f"Невозможно удалить категорию '{c.name}', так как в ней находятся {count} товаров.")
        return

    answer = yes_no_choice("Удалить категорию?")
    if answer:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.product_categories WHERE id = %s", (cid,))
        console.print(f"[green]Категория '{c.name}' удалена[/green]")


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