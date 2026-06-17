# src/users.py
from dataclasses import dataclass
from psycopg.rows import class_row
from db import get_conn
from typing import Optional


@dataclass
class User:
    id: int
    username: str
    role: str


def find_user_by_login_and_pass(username: str, password: str) -> Optional[User]:
    conn = get_conn()
    query = """
        SELECT u.id, u.username, u.role
        FROM auth.users u
        WHERE u.username = %s AND u.password = crypt(%s, u.password);
    """
    with conn.cursor(row_factory=class_row(User)) as cur:
        cur.execute(query, (username, password))
        return cur.fetchone()


def get_user(id_: int) -> User:
    conn = get_conn()
    query = "SELECT id, username, role FROM auth.users WHERE id = %s;"
    with conn.cursor(row_factory=class_row(User)) as cur:
        cur.execute(query, (id_,))
        user = cur.fetchone()
    if not user:
        raise ValueError(f"User with id {id_} not found")
    return user