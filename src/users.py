from dataclasses import dataclass


@dataclass
class User:
    id: int
    username: str
    role: str


def find_user_by_login_and_pass(username: str, password: str) -> User | None:
    """
    Надо реализовать
    """


def get_user(id_: int) -> User:
    """
    Надо реализовать
    """