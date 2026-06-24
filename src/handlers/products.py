# src/handlers/products.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, PriceValidator
from commands import command, CATEGORY_PRODUCTS
from src.auth import ROLE_CATALOG_MANAGER
from src.helpers import get_category_choices
from typing import Optional


@dataclass
class Product:
    id: int
    sku: str
    name: str
    price: Decimal
    category_id: int
    category_name: str


def _render_product(product: Product) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")
    table.add_row("ID", str(product.id))
    table.add_row("SKU", product.sku)
    table.add_row("Название", product.name)
    table.add_row("Цена", f"{product.price:.2f}")
    table.add_row("Категория", product.category_name)
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Товар #{product.id}[/bold green]",
        border_style="green",
    )
    console.print(panel)


@command("list products", "список всех товаров", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def list_products() -> None:
    conn = get_conn()
    table = Table(title="Товары", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("SKU", style="blue", min_width=15)
    table.add_column("Название", style="green", min_width=20)
    table.add_column("Цена", style="yellow", min_width=10, justify="right")
    table.add_column("Категория", style="magenta", min_width=15)

    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            "SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name"
            "FROM catalog.products p"
            "JOIN catalog.product_categories pc ON p.category_id = pc.id"
            "ORDER BY p.name"
        )
        products: list[Product] = cur.fetchall()

    for p in products:
        table.add_row(
            str(p.id),
            p.sku,
            p.name,
            f"{p.price:.2f}",
            p.category_name,
        )
    console.print(table)


@command("show product", "информация о товаре", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def show_product(_id: str) -> None:
    try:
        pid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            "SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name"
            "FROM catalog.products p"
            "JOIN catalog.product_categories pc ON p.category_id = pc.id"
            "WHERE p.id = %s", (pid,)
        )
        p: Product | None = cur.fetchone()

    if not p:
        render_error(f"Товар с ID {pid} не найден")
        return

    _render_product(p)


@command("add product", "добавить товар (интерактивно)", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def add_product() -> None:
    sku: str = prompt("SKU (до 30 символов): ", validator=NonEmptyValidator()).strip()[:30]
    name: str = prompt("Название: ", validator=NonEmptyValidator()).strip()
    price_str: str = prompt("Цена: ", validator=PriceValidator()).strip()
    price: Decimal = Decimal(price_str)

    categories = get_category_choices()
    if not categories:
        render_error("Нет доступных категорий. Сначала создайте категорию.")
        return

    cat_choices = [(str(cid), cname) for cid, cname in categories]
    selected_cid_str: str = choice(
        message="Категория: ",
        options=cat_choices,
        default=cat_choices[0][0]
    )
    try:
        cat_id: int = int(selected_cid_str)
    except ValueError:
        render_error("Неверный выбор категории.")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO catalog.products (sku, name, price, category_id) VALUES (%s, %s, %s, %s) RETURNING id",
                (sku, name, price, cat_id),
            )
            new_id: int = cur.fetchone()[0]
        console.print(f"[green]Товар '{name}' (SKU: {sku}, ID: {new_id}) добавлен[/green]")
    except Exception as e:
        render_error(f"Ошибка добавления товара: {e}")


@command("edit product", "редактировать товар", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def edit_product(_id: str) -> None:
    try:
        pid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            "SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name"
            "FROM catalog.products p"
            "JOIN catalog.product_categories pc ON p.category_id = pc.id"
            "WHERE p.id = %s", (pid,)
        )
        p: Product | None = cur.fetchone()

    if not p:
        render_error(f"Товар с ID {pid} не найден")
        return

    sku: str = prompt("SKU (до 30 символов): ", default=p.sku, validator=NonEmptyValidator()).strip()[:30]
    name: str = prompt("Название: ", default=p.name, validator=NonEmptyValidator()).strip()
    price_str: str = prompt("Цена: ", default=str(p.price), validator=PriceValidator()).strip()
    price: Decimal = Decimal(price_str)

    categories = get_category_choices()
    cat_choices = [(str(cid), cname) for cid, cname in categories]
    selected_cid_str: str = choice(
        message="Категория: ",
        options=cat_choices,
        default=str(p.category_id)
    )
    try:
        cat_id: int = int(selected_cid_str)
    except ValueError:
        render_error("Неверный выбор категории.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE catalog.products
                   SET sku = %s, name = %s, price = %s, category_id = %s
                   WHERE id = %s""",
                (sku, name, price, cat_id, pid),
            )
        console.print(f"[green]Товар '{name}' (ID: {pid}) обновлён[/green]")
    except Exception as e:
        render_error(f"Ошибка редактирования товара: {e}")


@command("delete product", "удалить товар", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def delete_product(_id: str) -> None:
    try:
        pid = int(_id)
    except ValueError:
        render_error("ID должен быть числом.")
        return

    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            "SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name"
            "FROM catalog.products p"
            "JOIN catalog.product_categories pc ON p.category_id = pc.id"
            "WHERE p.id = %s", (pid,)
        )
        p: Product | None = cur.fetchone()

    if not p:
        render_error(f"Товар с ID {pid} не найден")
        return

    _render_product(p)

    answer: bool = yes_no_choice("Удалить товар?")
    if answer:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.products WHERE id = %s", (pid,))
        console.print(f"[green]Товар '{p.name}' (ID: {pid}) удалён[/green]")


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