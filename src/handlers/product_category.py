from dataclasses import dataclass

from prompt_toolkit.completion import WordCompleter

from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_PRODUCT_CATEGORY

@dataclass
class Product_category:
    id: int
    name: str

category = [
    "Техника",
    "Продукты",
    "Одежда",
    "Мебель",
    "Строительные товары",
]

category_completer = WordCompleter(category, ignore_case=True, sentence=True)
category_validator = ChoiceValidator(
    category, message="Город должен быть из списка. Используйте Tab для автодополнения."
)

def _render_product_category(product: Product_category):  # pylint: disable=unused-argument
    """
    Отображает информацию о категории в виде таблицы внутри панели.
    Используйте rich.table.Table и rich.panel.Panel для форматирования.
    """


@command("list product_categories", "список всех категорий", CATEGORY_PRODUCT_CATEGORY)
def list_product_categories() -> None:
    """
    Выводит список всех категорий из таблицы catalog.product_categories.
    Используйте rich.table.Table для отображения данных.
    Колонки: ID, product_id, category_id
    """


@command("show product_category", "информация о категории", CATEGORY_PRODUCT_CATEGORY)
def show_product_category(_id: str) -> None:
    """
    Показывает детальную информацию о категории по его ID.
    Если категория не найдена, выводит ошибку через _render_error.
    Используйте _render_product для отображения найденной категории.
    """


@command("add product_category", "добавить категорию (интерактивно)", CATEGORY_PRODUCT_CATEGORY)
def add_product_category() -> None:
    """
    Добавляет новую категорию в базу данных.
    Запрашивает у пользователя: название.
    Используйте prompt с валидаторами для ввода данных.
    """


@command("edit product_category", "редактировать категорию", CATEGORY_PRODUCT_CATEGORY)
def edit_product_category(_id: str) -> None:
    """
    Редактирует существующую категорию.
    Сначала проверяет существование категории по ID.
    Предлагает текущие значения как default при вводе новых данных.
    """


@command("delete product_category", "удалить категорию", CATEGORY_PRODUCT_CATEGORY)
def delete_pproduct_category(_id: str) -> None:
    """
    Удаляет категорию из базы данных.
    Сначала показывает информацию о категории.
    Запрашивает подтверждение перед удалением.
    """

