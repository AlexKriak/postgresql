# src/main.py
import argparse
import logging
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

from console import console, render_error
from commands import find_command, get_args, get_completer
from setup import setup_logging
from auth import login, auth_user

def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Inventory Management System")
    parser.add_argument("-u", "--username", help="Username for authentication")
    parser.add_argument("-p", "--password", help="Password for authentication")
    cli_args = parser.parse_args()

    login(username=cli_args.username, password=cli_args.password)

    session = PromptSession(history=FileHistory(".warehouse_cli_history"))

    user = auth_user()
    prompt_style = Style.from_dict({
        'username': '#ansigreen bold',
        'role': '#ansimagenta',
        'at': '#ansiblue',
        'colon': '#ansiyellow',
        'pound': '#ansicyan',
    })

    # Вывод заголовка через rich
    console.print("\n[bold cyan]═══════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   Inventory Management System[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════[/bold cyan]")
    console.print(f"[dim]Подключено к БД: warehouse_db (user: {user.username}, role: {user.role})[/dim]\n")

    while True:
        try:
            user_info = f"{user.username}@{user.role}"
            text = session.prompt(
                f"{user_info}> ",
                completer=get_completer(),
                auto_suggest=AutoSuggestFromHistory(),
                style=prompt_style
            )
            if not text.strip():
                continue

            cmd = find_command(text)
            if cmd:
                try:
                    args = get_args(text, cmd)
                    # Вызов обработчика с аргументами
                    cmd.handler(**args)
                except Exception as e:
                    render_error(f"Ошибка выполнения команды: {e}")
            else:
                console.print(f"[red]Неизвестная команда: {text}[/red]")

        except KeyboardInterrupt:
            continue
        except EOFError:
            break

    console.print("\n[green]До свидания![/green]")

if __name__ == "__main__":
    main()