# src/handlers/orders.py
import datetime
from dataclasses import dataclass

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_ORDERS


@dataclass
class Order:
    id: int
    status: str
    total_amount: float
    created_at: datetime.datetime
    warehouses_id: int


STATUS_CHOICES = ["unpublished", "new", "processing", "pending", "packing", "shipped"]
status_validator = ChoiceValidator(STATUS_CHOICES,
                                   message="Статус должен быть одним из следующего списка: " + ", ".join(
                                       STATUS_CHOICES))


def _render_order(order: Order) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("ID", str(order.id))
    table.add_column("Статус", order.status)
    table.add_column("Сумма", f"{order.total_amount:.2f}")
    table.add_column("Дата создания", order.created_at.strftime("%Y-%m-%d %H:%M"))
    table.add_column("Склад", str(order.warehouses_id))
    return table

def _render_orders()
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Склад #{warehouse.id}[/bold green]",
        border_style="green",
    )

    console.print(panel)
