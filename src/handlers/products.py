# src/handlers/products.py
from dataclasses import dataclass
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, PriceValidator
from commands import command, CATEGORY_PRODUCTS
from src.auth import ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER

@dataclass
class Product:
    id: int
    sku: str
    name: str
    price: Decimal
    category_id: int
    category_name: str # Добавляем имя категории для отображения


def _render_product(product: Product) -> None:
    """Отображает информацию о продукте в виде таблицы внутри панели"""
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


def _get_category_choices() -> list[str]:
    """Получает список названий категорий из БД"""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM catalog.product_categories ORDER BY name")
        rows = cur.fetchall()
    return [row[0] for row in rows]


@command("list products", "список всех товаров", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER])
def list_products() -> None:
    """Выводит список всех продуктов из таблицы catalog.products"""
    conn = get_conn()
    table = Table(title="Товары", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("SKU", style="blue", min_width=15)
    table.add_column("Название", style="green", min_width=20)
    table.add_column("Цена", style="yellow", min_width=10, justify="right")
    table.add_column("Категория", style="magenta", min_width=15)

    with conn.cursor(row_factory=class_row(Product)) as cur:
        # Используем JOIN для получения имени категории
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name
            FROM catalog.products p
            JOIN catalog.product_categories pc ON p.category_id = pc.id
            ORDER BY p.name
        """)
        products: list[Product] = cur.fetchall()

    for product in products:
        table.add_row(
            str(product.id),
            product.sku,
            product.name,
            f"{product.price:.2f}",
            product.category_name,
        )
    console.print(table)


@command("show product", "информация о товаре", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER])
def show_product(_id: str) -> None:
    """Показывает детальную информацию о продукте по его ID"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name
            FROM catalog.products p
            JOIN catalog.product_categories pc ON p.category_id = pc.id
            WHERE p.id = %s
        """, (_id,))
        product: Product | None = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return

    _render_product(product)


@command("add product", "добавить товар (интерактивно)", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def add_product() -> None:
    """Добавляет новый продукт в базу данных"""
    sku = prompt("SKU (до 30 символов): ", validator=NonEmptyValidator()).strip()[:30]
    name = prompt("Название: ", validator=NonEmptyValidator()).strip()
    price_str = prompt("Цена: ", validator=PriceValidator()).strip()
    price = Decimal(price_str)

    categories = _get_category_choices()
    if not categories:
        render_error("Нет доступных категорий. Сначала создайте категорию.")
        return

    category_completer = WordCompleter(categories, ignore_case=True)
    category_name = prompt(
        "Категория (выберите из списка): ",
        completer=category_completer,
        validator=ChoiceValidator(categories, "Выберите категорию из списка. Используйте Tab для автодополнения.")
    ).strip()

    conn = get_conn()
    with conn.cursor() as cur:
        # Получаем ID выбранной категории
        cur.execute("SELECT id FROM catalog.product_categories WHERE name = %s", (category_name,))
        category_row = cur.fetchone()
        if not category_row:
             render_error(f"Категория '{category_name}' не найдена в базе данных.")
             return
        category_id = category_row[0]

        cur.execute(
            "INSERT INTO catalog.products (sku, name, price, category_id) VALUES (%s, %s, %s, %s)",
            (sku, name, price, category_id),
        )
    console.print(f"[green]Товар '{name}' (SKU: {sku}) добавлен[/green]")


@command("edit product", "редактировать товар", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def edit_product(_id: str) -> None:
    """Редактирует существующий продукт"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name
            FROM catalog.products p
            JOIN catalog.product_categories pc ON p.category_id = pc.id
            WHERE p.id = %s
        """, (_id,))
        product: Product | None = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return

    sku = prompt("SKU (до 30 символов): ", default=product.sku, validator=NonEmptyValidator()).strip()[:30]
    name = prompt("Название: ", default=product.name, validator=NonEmptyValidator()).strip()
    price_str = prompt("Цена: ", default=str(product.price), validator=PriceValidator()).strip()
    price = Decimal(price_str)

    categories = _get_category_choices()
    if not categories:
        render_error("Нет доступных категорий для изменения.")
        return

    category_completer = WordCompleter(categories, ignore_case=True)
    category_name = prompt(
        "Категория (выберите из списка): ",
        default=product.category_name,
        completer=category_completer,
        validator=ChoiceValidator(categories, "Выберите категорию из списка. Используйте Tab для автодополнения.")
    ).strip()

    with conn.cursor() as cur:
        # Получаем ID выбранной категории
        cur.execute("SELECT id FROM catalog.product_categories WHERE name = %s", (category_name,))
        category_row = cur.fetchone()
        if not category_row:
             render_error(f"Категория '{category_name}' не найдена в базе данных.")
             return
        category_id = category_row[0]

        cur.execute(
            """UPDATE catalog.products SET sku = %s, name = %s, price = %s, category_id = %s
            WHERE id = %s""",
            (sku, name, price, category_id, _id),
        )
    console.print(f"[green]Товар '{name}' (ID: {_id}) обновлен[/green]")


@command("delete product", "удалить товар", CATEGORY_PRODUCTS, [ROLE_CATALOG_MANAGER])
def delete_product(_id: str) -> None:
    """Удаляет продукт из базы данных"""
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, p.category_id, pc.name as category_name
            FROM catalog.products p
            JOIN catalog.product_categories pc ON p.category_id = pc.id
            WHERE p.id = %s
        """, (_id,))
        product: Product | None = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return

    _render_product(product)

    answer = prompt("Вы уверены? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog.products WHERE id = %s", (_id,))
        console.print(f"[green]Товар '{product.name}' (ID: {_id}) удален[/green]")
