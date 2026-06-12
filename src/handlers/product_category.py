# src/handlers/product_categories.py
from dataclasses import dataclass
from prompt_toolkit import prompt
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator
from commands import command, CATEGORY_PRODUCT_CATEGORY
from src.auth import ROLE_CATALOG_MANAGER

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

    for category in categories:
        table.add_row(str(category.id), category.name)
    console.print(table)


@command("show product_category", "информация о категории", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def show_category(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (_id,))
        category: ProductCategory | None = cur.fetchone()

    if category is None:
        render_error(f"Категория с ID {_id} не найдена")
        return

    _render_category(category)


@command("add product_category", "добавить категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def add_category() -> None:
    name = prompt("Название категории: ", validator=NonEmptyValidator()).strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO catalog.product_categories (name) VALUES (%s)",
                (name,),
            )
        console.print(f"[green]Категория '{name}' добавлена[/green]")
    except Exception as e: # Обработка дубликата или других ошибок
        render_error(f"Ошибка добавления категории: {e}")


@command("edit product_category", "редактировать категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def edit_category(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (_id,))
        category: ProductCategory | None = cur.fetchone()

    if category is None:
        render_error(f"Категория с ID {_id} не найдена")
        return

    new_name = prompt("Новое название: ", default=category.name, validator=NonEmptyValidator()).strip()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE catalog.product_categories SET name = %s WHERE id = %s",
                (new_name, _id),
            )
        console.print(f"[green]Категория '#{_id}' обновлена[/green]")
    except Exception as e: # Обработка дубликата или других ошибок
        render_error(f"Ошибка редактирования категории: {e}")


@command("delete product_category", "удалить категорию", CATEGORY_PRODUCT_CATEGORY, [ROLE_CATALOG_MANAGER])
def delete_category(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT * FROM catalog.product_categories WHERE id = %s", (_id,))
        category: ProductCategory | None = cur.fetchone()

    if category is None:
        render_error(f"Категория с ID {_id} не найдена")
        return

    _render_category(category)

    # Проверить, используются ли товары из этой категории
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.products WHERE category_id = %s", (_id,))
        count = cur.fetchone()[0]

    if count > 0:
        render_error(f"Невозможно удалить категорию '{category.name}', так как в ней находятся {count} товаров.")
        return

    answer = prompt("Вы уверены? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.product_categories WHERE id = %s", (_id,))
        console.print(f"[green]Категория '{category.name}' удалена[/green]")
