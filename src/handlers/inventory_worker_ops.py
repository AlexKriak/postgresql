# src/handlers/inventory_worker_ops.py
from decimal import Decimal
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row, Row
from rich.panel import Panel
from rich.table import Table
import psycopg.errors as pg_errors
import datetime
from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_INVENTORY_READ
from src.auth import ROLE_WORKER, auth_user
from src.helpers import get_warehouse_by_user, get_warehouse_choices, get_username_by_id, yes_no_choice
from typing import Optional, List, Dict, Tuple
from src.handlers.transfer_items import _get_transfer_items_by_transfer_id
from src.handlers.order_items import _get_order_items_by_order_id
from src.handlers.inventory_views import get_order_item_statuses


# Получает ID склада, к которому привязан worker
def get_warehouse_by_user(user_id: int) -> Optional[int]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT warehouse_id FROM auth.users WHERE id = %s", (user_id,))
        res = cur.fetchone()
        return res[0] if res else None

def _get_transfers_by_status_and_warehouse(status: str, warehouse_id: int) -> List[Dict]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        if status in ['shipping', 'in_transit']:
             cur.execute("""
                 SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status, t.created_at, t.started_at, t.arriving_at, t.received_at,
                        fw.city_name as from_city_name, fw.label as from_label,
                        tw.city_name as to_city_name, tw.label as to_label
                 FROM inventory.transfers t
                 JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                 JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                 WHERE t.status = %s AND t.from_warehouse_id = %s
                 ORDER BY t.created_at;
             """, (status, warehouse_id))
        elif status in ['arrived']:
             cur.execute("""
                 SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status, t.created_at, t.started_at, t.arriving_at, t.received_at,
                        fw.city_name as from_city_name, fw.label as from_label,
                        tw.city_name as to_city_name, tw.label as to_label
                 FROM inventory.transfers t
                 JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                 JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                 WHERE t.status = %s AND t.to_warehouse_id = %s
                 ORDER BY t.created_at;
             """, (status, warehouse_id))
        else:
             cur.execute("""
                 SELECT t.id, t.from_warehouse_id, t.to_warehouse_id, t.status, t.created_at, t.started_at, t.arriving_at, t.received_at,
                        fw.city_name as from_city_name, fw.label as from_label,
                        tw.city_name as to_city_name, tw.label as to_label
                 FROM inventory.transfers t
                 JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                 JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                 WHERE t.status = %s
                 ORDER BY t.created_at;
             """, (status,))
        return cur.fetchall()


# Получает доставки по статусу и складу назначения
def _get_deliveries_by_status_and_target_warehouse(status: str, warehouse_id: int) -> List[Dict]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT d.order_id, d.status, d.created_at, d.shipped_at,
                   o.warehouses_id as target_warehouse_id
            FROM inventory.deliveries d
            JOIN sales.orders o ON d.order_id = o.id
            WHERE d.status = %s AND o.warehouses_id = %s
            ORDER BY d.created_at;
        """, (status, warehouse_id))
        return cur.fetchall()


# Получает позиции трансфера по ID и статусу
def _get_transfer_items_by_transfer_id_and_status(tid: int, status: str) -> List[Dict]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT ti.id, ti.transfer_id, ti.product_id, ti.quantity, ti.requested_by, ti.reserve_id, ti.status, ti.created_at, ti.shipped_at, ti.received_at,
                   p.sku, p.name
            FROM inventory.transfer_items ti
            JOIN catalog.products p ON ti.product_id = p.id
            WHERE ti.transfer_id = %s AND ti.status = %s
            ORDER BY ti.id;
        """, (tid, status))
        return cur.fetchall()


# Получает позиции доставки по ID заказа и статусу
def _get_delivery_items_by_order_id_and_status(oid: int, status: str) -> List[Dict]:
    conn = get_conn()
    with conn.cursor(row_factory=Row) as cur:
        cur.execute("""
            SELECT di.order_id, di.product_id, di.quantity, di.status, di.created_at, di.shipped_at,
                   p.sku, p.name
            FROM inventory.delivery_items di
            JOIN catalog.products p ON di.product_id = p.id
            WHERE di.order_id = %s AND di.status = %s
            ORDER BY di.product_id;
        """, (oid, status))
        return cur.fetchall()


@command("list transfers shipping", "список трансферов, ожидающих отгрузки из моего склада", CATEGORY_INVENTORY_READ, [ROLE_WORKER])
def list_transfers_shipping() -> None:
    worker_warehouse_id = get_warehouse_by_user(auth_user().id)
    if not worker_warehouse_id:
        render_error("Не удалось определить ваш склад.")
        return

    transfers = _get_transfers_by_status_and_warehouse('shipping', worker_warehouse_id)
    if not transfers:
        console.print("[yellow]Нет трансферов, ожидающих отгрузки из вашего склада.[/yellow]")
        return

    console.print("\n[yellow]Трансферы, ожидающие отгрузки:[/yellow]")
    for t in transfers:
        table = Table(title=f"Перемещение #{t[0]}", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=6, justify="right")
        table.add_column("Товар", style="green", min_width=25)
        table.add_column("Кол-во", style="magenta", min_width=6, justify="right")
        table.add_column("Статус", style="green", min_width=12)
        # Получаем позиции с нужным статусом для отображения
        items = _get_transfer_items_by_transfer_id_and_status(t[0], 'planned')
        for item in items:
            table.add_row(str(item[0]), f"{item[8]} (SKU: {item[7]})", str(item[3]), item[6]) # id, name, sku, quantity, status
        console.print(table)
        console.print("---")

@command("ship transfer", "отгрузка трансфера (изменение статуса позиций и трансфера)", CATEGORY_INVENTORY_READ, [ROLE_WORKER])
def ship_transfer(_id: str) -> None:
    try:
        tid = int(_id)
    except ValueError:
        render_error("ID трансфера должен быть числом.")
        return

    worker_warehouse_id = get_warehouse_by_user(auth_user().id)
    if not worker_warehouse_id:
        render_error("Не удалось определить ваш склад.")
        return

    conn = get_conn()
    try:
        with conn:
            with conn.transaction():
                with conn.cursor(row_factory=Row) as cur:
                    cur.execute("""
                        SELECT id, status, from_warehouse_id
                        FROM inventory.transfers
                        WHERE id = %s AND status = 'shipping' AND from_warehouse_id = %s
                        FOR UPDATE; -- Блокируем строку
                    """, (tid, worker_warehouse_id))
                    transfer_row = cur.fetchone()
                    if not transfer_row:
                        render_error(f"Трансфер #{tid} не найден, не в статусе 'shipping' или не с вашего склада.")
                        return

                    items = _get_transfer_items_by_transfer_id_and_status(tid, 'planned')
                    if not items:
                         console.print(f"[green]Все позиции в трансфере #{tid} уже отгружены.[/green]")
                         cur.execute("UPDATE inventory.transfers SET status = 'in_transit', started_at = COALESCE(started_at, NOW()) WHERE id = %s;", (tid,))
                         console.print(f"[green]Статус трансфера #{tid} изменен на 'in_transit'.[/green]")
                         return

                    console.print(f"Обработка отгрузки для трансфера #{tid}. Найдено {len(items)} позиций со статусом 'planned'.")

                    confirm_ship = yes_no_choice(f"Отгрузить все {len(items)} позиции из трансфера #{tid}?")
                    if not confirm_ship:
                        console.print("[yellow]Отгрузка отменена.[/yellow]")
                        return

                    item_ids = [item[0] for item in items]
                    placeholders = ','.join(['%s'] * len(item_ids))
                    cur.execute(f"""
                        UPDATE inventory.transfer_items
                        SET status = 'shipped', shipped_at = NOW()
                        WHERE id IN ({placeholders}) AND status = 'planned';
                    """, item_ids)

                    rows_affected = cur.rowcount
                    if rows_affected != len(item_ids):
                        render_error(f"Не все позиции удалось отгрузить. Возможно, другой работник уже обработал часть из них.")
                        return

                    cur.execute("SELECT COUNT(*) FROM inventory.transfer_items WHERE transfer_id = %s AND status IN ('shipped', 'received');", (tid,))
                    processed_items_count = cur.fetchone()[0]
                    total_items_count = len(_get_transfer_items_by_transfer_id(tid))

                    if processed_items_count == total_items_count:
                        cur.execute("""
                            SELECT r.duration
                            FROM inventory.transfers t
                            JOIN catalog.warehouses fw ON t.from_warehouse_id = fw.id
                            JOIN catalog.warehouses tw ON t.to_warehouse_id = tw.id
                            JOIN inventory.routes r ON fw.city_id = r.from_city_id AND tw.city_id = r.to_city_id
                            WHERE t.id = %s;
                        """, (tid,))
                        route_duration_row = cur.fetchone()
                        duration = route_duration_row[0] if route_duration_row else datetime.timedelta(hours=24)

                        arriving_at = datetime.datetime.now() + duration

                        cur.execute("""
                            UPDATE inventory.transfers
                            SET status = 'in_transit', arriving_at = %s, started_at = COALESCE(started_at, NOW())
                            WHERE id = %s;
                        """, (arriving_at, tid))
                        console.print(f"[green]Все позиции отгружены. Статус трансфера #{tid} изменен на 'in_transit'. Ожидаем прибытие {arriving_at}.[/green]")
                    else:
                        console.print(f"[green]Отгружено {rows_affected} позиций из {total_items_count} в трансфере #{tid}.[/green]")

    except Exception as e:
        render_error(f"Ошибка при отгрузке трансфера: {e}")

@command("check transfers", "проверяет, нет ли прибывших трансферов", CATEGORY_INVENTORY_READ, [ROLE_WORKER])
def check_transfers() -> None:
    worker_warehouse_id = get_warehouse_by_user(auth_user().id)
    if not worker_warehouse_id:
        render_error("Не удалось определить ваш склад.")
        return

    conn = get_conn()
    try:
        with conn:
            with conn.transaction():
                with conn.cursor(row_factory=Row) as cur:
                    now = datetime.datetime.now()
                    cur.execute("""
                        SELECT id, status, to_warehouse_id
                        FROM inventory.transfers
                        WHERE status = 'in_transit' AND arriving_at <= %s AND to_warehouse_id = %s
                        FOR UPDATE;
                    """, (now, worker_warehouse_id))
                    pending_arrivals = cur.fetchall()

                    updated_count = 0
                    for transfer_row in pending_arrivals:
                        tid = transfer_row[0]
                        cur.execute("UPDATE inventory.transfers SET status = 'arrived' WHERE id = %s;", (tid,))
                        updated_count += 1
                        console.print(f"[green]Статус трансфера #{tid} изменен на 'arrived'.[/green]")

                    if updated_count == 0:
                        console.print("[yellow]Нет трансферов, готовых к прибытию на ваш склад.[/yellow]")
                    else:
                        console.print(f"[green]Обновлено статусов: {updated_count}.[/green]")

    except Exception as e:
        render_error(f"Ошибка при проверке трансферов: {e}")

@command("receive transfer", "разгрузка трансфера (изменение статуса позиций и трансфера)", CATEGORY_INVENTORY_READ, [ROLE_WORKER])
def receive_transfer(_id: str) -> None:
    try:
        tid = int(_id)
    except ValueError:
        render_error("ID трансфера должен быть числом.")
        return

    worker_warehouse_id = get_warehouse_by_user(auth_user().id)
    if not worker_warehouse_id:
        render_error("Не удалось определить ваш склад.")
        return

    conn = get_conn()
    try:
        with conn:
            with conn.transaction():
                with conn.cursor(row_factory=Row) as cur:
                    cur.execute("""
                        SELECT id, status, to_warehouse_id
                        FROM inventory.transfers
                        WHERE id = %s AND status = 'arrived' AND to_warehouse_id = %s
                        FOR UPDATE; -- Блокируем строку
                    """, (tid, worker_warehouse_id))
                    transfer_row = cur.fetchone()
                    if not transfer_row:
                        render_error(f"Трансфер #{tid} не найден, не в статусе 'arrived' или не на ваш склад.")
                        return

                    items = _get_transfer_items_by_transfer_id_and_status(tid, 'shipped')
                    if not items:
                         console.print(f"[green]Все позиции в трансфере #{tid} уже разгружены.[/green]")
                         cur.execute("UPDATE inventory.transfers SET status = 'received', received_at = NOW() WHERE id = %s;", (tid,))
                         console.print(f"[green]Статус трансфера #{tid} изменен на 'received'.[/green]")
                         return

                    console.print(f"Обработка разгрузки для трансфера #{tid}. Найдено {len(items)} позиций со статусом 'shipped'.")

                    confirm_receive = yes_no_choice(f"Разгрузить все {len(items)} позиции из трансфера #{tid}?")
                    if not confirm_receive:
                        console.print("[yellow]Разгрузка отменена.[/yellow]")
                        return

                    item_ids_to_receive = []
                    for item in items:
                        item_id = item[0]
                        product_id = item[2]
                        quantity = item[3]
                        reserve_id = item[5]

                        cur.execute("""
                            UPDATE inventory.transfer_items
                            SET status = 'received', received_at = NOW()
                            WHERE id = %s AND status = 'shipped';
                        """, (item_id,))
                        rows_affected_ti = cur.rowcount
                        if rows_affected_ti != 1:
                            render_error(f"Не удалось разгрузить позицию #{item_id}. Возможно, другой работник уже обработал её.")
                            return
                        item_ids_to_receive.append(item_id)

                        if reserve_id:
                            cur.execute("SELECT order_id, product_id, quantity, warehouse_id FROM inventory.reserves WHERE id = %s;", (reserve_id,))
                            reserve_row = cur.fetchone()
                            if reserve_row:
                                res_order_id, res_product_id, res_quantity, res_warehouse_id = reserve_row
                                target_warehouse_for_reserve_item = res_warehouse_id
                                cur.execute("""
                                    INSERT INTO inventory.stock (warehouse_id, product_id, quantity)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (warehouse_id, product_id) DO UPDATE SET quantity = inventory.stock.quantity + %s;
                                """, (target_warehouse_for_reserve_item, product_id, quantity, quantity))
                                console.print(f"[blue]Товар из позиции #{item_id} (резерв #{reserve_id}) добавлен в stock склада #{target_warehouse_for_reserve_item}.[/blue]")
                            else:
                                cur.execute("""
                                    INSERT INTO inventory.stock (warehouse_id, product_id, quantity)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (warehouse_id, product_id) DO UPDATE SET quantity = inventory.stock.quantity + %s;
                                """, (worker_warehouse_id, product_id, quantity, quantity))
                                console.print(f"[blue]Товар из позиции #{item_id} (без резерва) добавлен в stock склада #{worker_warehouse_id}.[/blue]")
                        else:
                            cur.execute("""
                                INSERT INTO inventory.stock (warehouse_id, product_id, quantity)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (warehouse_id, product_id) DO UPDATE SET quantity = inventory.stock.quantity + %s;
                            """, (worker_warehouse_id, product_id, quantity, quantity))
                            console.print(f"[blue]Товар из позиции #{item_id} (без резерва) добавлен в stock склада #{worker_warehouse_id}.[/blue]")

                    cur.execute("SELECT COUNT(*) FROM inventory.transfer_items WHERE transfer_id = %s AND status = 'received';", (tid,))
                    received_items_count = cur.fetchone()[0]
                    total_items_count = len(_get_transfer_items_by_transfer_id(tid))

                    if received_items_count == total_items_count:
                        cur.execute("UPDATE inventory.transfers SET status = 'received', received_at = NOW() WHERE id = %s;", (tid,))
                        console.print(f"[green]Все позиции разгружены. Статус трансфера #{tid} изменен на 'received'.[/green]")
                    else:
                        console.print(f"[green]Разгружено {len(item_ids_to_receive)} позиций из {total_items_count} в трансфере #{tid}.[/green]")

    except Exception as e:
        render_error(f"Ошибка при разгрузке трансфера: {e}")

@command("ship delivery", "отгрузка доставки заказа", CATEGORY_INVENTORY_READ, [ROLE_WORKER])
def ship_delivery(_order_id: str) -> None:
    try:
        oid = int(_order_id)
    except ValueError:
        render_error("ID заказа должен быть числом.")
        return

    worker_warehouse_id = get_warehouse_by_user(auth_user().id)
    if not worker_warehouse_id:
        render_error("Не удалось определить ваш склад.")
        return

    conn = get_conn()
    try:
        with conn:
            with conn.transaction():
                with conn.cursor(row_factory=Row) as cur:
                    cur.execute("""
                        SELECT dv.order_id, d.status
                        FROM inventory.deliveries d
                        JOIN inventory.worker_sales_view dv ON d.order_id = dv.order_id
                        WHERE d.order_id = %s AND d.status = 'planned' AND dv.target_warehouse_id = %s
                        FOR UPDATE;
                    """, (oid, worker_warehouse_id))
                    delivery_row = cur.fetchone()
                    if not delivery_row:
                        render_error(f"Доставка для заказа #{oid} не найдена, не в статусе 'planned' или заказ не связан с вашим складом.")
                        return

                    items = _get_delivery_items_by_order_id_and_status(oid, 'planned')
                    if not items:
                         console.print(f"[green]Все позиции в доставке заказа #{oid} уже отгружены.[/green]")
                         cur.execute("UPDATE inventory.deliveries SET status = 'shipped', shipped_at = NOW() WHERE order_id = %s;", (oid,))
                         console.print(f"[green]Статус доставки для заказа #{oid} изменен на 'shipped'.[/green]")
                         return

                    console.print(f"Обработка отгрузки доставки для заказа #{oid}. Найдено {len(items)} позиций со статусом 'planned'.")

                    confirm_ship = yes_no_choice(f"Отгрузить все {len(items)} позиции из доставки заказа #{oid}?")
                    if not confirm_ship:
                        console.print("[yellow]Отгрузка доставки отменена.[/yellow]")
                        return

                    item_pids = [item[1] for item in items]
                    placeholders = ','.join(['%s'] * len(item_pids))
                    cur.execute(f"""
                        UPDATE inventory.delivery_items
                        SET status = 'shipped', shipped_at = NOW()
                        WHERE order_id = %s AND product_id IN ({placeholders}) AND status = 'planned';
                    """, [oid] + item_pids)

                    rows_affected_di = cur.rowcount
                    if rows_affected_di != len(item_pids):
                        render_error(f"Не все позиции доставки удалось отгрузить. Возможно, другой работник уже обработал часть из них.")
                        return

                    cur.execute("SELECT COUNT(*) FROM inventory.delivery_items WHERE order_id = %s AND status = 'shipped';", (oid,))
                    shipped_items_count = cur.fetchone()[0]
                    total_delivery_items_count = len(_get_delivery_items_by_order_id_and_status(oid, 'planned')) + len(_get_delivery_items_by_order_id_and_status(oid, 'shipped'))

                    if shipped_items_count == total_delivery_items_count:
                        cur.execute("UPDATE inventory.deliveries SET status = 'shipped', shipped_at = NOW() WHERE order_id = %s;", (oid,))
                        console.print(f"[green]Все позиции доставки отгружены. Статус доставки для заказа #{oid} изменен на 'shipped'.[/green]")
                    else:
                        console.print(f"[green]Отгружено {rows_affected_di} позиций из {total_delivery_items_count} в доставке заказа #{oid}.[/green]")

    except Exception as e:
        render_error(f"Ошибка при отгрузке доставки: {e}")
