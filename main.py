import os

import sys
from datetime import date, timedelta

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback
from sqlalchemy.exc import SQLAlchemyError

install_rich_traceback(show_locals=False)

console = Console()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db.models import User, init_db
from engine.data_loader import InputCollector
from engine.formatting import score_style
from engine.pattern_detector import PatternDetector
from engine.score_engine import ScoreEngine
from reports.daily_report import DailyReporter
from reports.weekly_report import WeeklyReporter


def _print_banner() -> None:
    console.print("[bold cyan]Healthy Routine Stability Score System[/bold cyan]")
    console.print()


def _print_menu() -> str:
    console.print("[bold cyan]Main Menu[/bold cyan]")
    console.print("  [bold]1.[/bold] Log today's habits")
    console.print("  [bold]2.[/bold] View today's report")
    console.print("  [bold]3.[/bold] View weekly report + charts")
    console.print("  [bold]4.[/bold] View score history (30 days)")
    console.print("  [bold]5.[/bold] Exit")
    console.print()
    return Prompt.ask("  Select an option", choices=["1", "2", "3", "4", "5"])


def _ensure_user_exists(session) -> User:
    """Guide the user through creating a profile if none exists."""
    user = session.query(User).first()
    if user:
        return user

    console.print("[bold yellow]No users found. Create your profile.[/bold yellow]")

    while True:
        name  = Prompt.ask("  [cyan]Your name[/cyan]").strip()
        email = Prompt.ask("  [cyan]Email[/cyan]").strip()
        tz    = Prompt.ask("  [cyan]Timezone[/cyan]", default="UTC").strip()

        console.print("\n  [bold]Daily Targets[/bold] [dim](press Enter for defaults)[/dim]")
        target_sleep = float(Prompt.ask("  [cyan]Target sleep hours[/cyan]", default="8.0"))
        target_water = int(Prompt.ask("  [cyan]Target water (ml)[/cyan]", default="2500"))
        target_steps = int(Prompt.ask("  [cyan]Target steps[/cyan]", default="8000"))

        try:
            user = User(
                name=name,
                email=email,
                timezone=tz,
                target_sleep_hr=target_sleep,
                target_water_ml=target_water,
                target_steps=target_steps,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            console.print(
                f"\n[bold green]Profile created![/bold green] Welcome, "
                f"[bold]{user.name}[/bold].\n"
            )
            return user
        except SQLAlchemyError as exc:
            session.rollback()
            console.print(
                f"\n[bold red]Error:[/bold red] {exc}\n  Please try again.\n"
            )


def _option_1_log(user: User, session) -> None:
    """Log habits, score them, and detect disruptions."""
    collector = InputCollector()
    engine    = ScoreEngine()
    detector  = PatternDetector()

    log_data = collector.collect_daily_log(user.user_id, session)
    log_id   = collector.save_log(log_data, session)

    console.print("\n[dim]Computing stability score...[/dim]")
    overall = engine.compute_daily_score(log_id, user.user_id, session)

    console.print(
        f"\n[bold]Today's Stability Score:[/bold] "
        f"[{score_style(overall)}]{overall:.1f} / 100[/{score_style(overall)}]"
    )

    disruptions = detector.detect_disruptions(log_id, user.user_id, session)
    if disruptions:
        console.print("\n[bold red]Disruptions Detected[/bold red]")
        for d in disruptions:
            sev   = d["severity"].upper()
            color = "yellow" if sev == "LOW" else ("orange3" if sev == "MEDIUM" else "red")
            console.print(f"  [{color}]{sev}[/{color}]  {d['description']}")
    else:
        console.print("\n[green]No disruptions detected — great consistency![/green]")


def _option_2_today_report(user: User, session) -> None:
    """Show today's log report."""
    reporter = DailyReporter()
    reporter.print_daily_report(user.user_id, date.today(), session)


def _option_3_weekly_report(user: User, session) -> None:
    """Print the weekly report and generate charts."""
    reporter   = WeeklyReporter()
    week_start = date.today() - timedelta(days=date.today().weekday())

    engine = ScoreEngine()
    try:
        engine.compute_weekly_score(user.user_id, week_start, session)
    except Exception:
        pass

    reporter.print_weekly_report(user.user_id, week_start, session)

    console.print()
    if Confirm.ask("  Generate / refresh charts?", default=True):
        output_dir = os.path.join(PROJECT_ROOT, "output")
        reporter.generate_charts(user.user_id, session, output_dir=output_dir)


def _option_4_history(user: User, session) -> None:
    """Show history table for the last 30 days."""
    engine = ScoreEngine()
    df     = engine.get_score_history(user.user_id, days=30, session=session)

    if df.empty:
        console.print("[dim]No score history found. Log some days first![/dim]")
        return

    tbl = Table(
        title="Stability Score History - Last 30 Days",
        header_style="bold magenta"
    )
    tbl.add_column("Date", style="white")
    tbl.add_column("Overall", justify="right")
    tbl.add_column("Sleep", justify="right")
    tbl.add_column("Meal", justify="right")
    tbl.add_column("Activity", justify="right")
    tbl.add_column("Hydration", justify="right")
    tbl.add_column("Screen", justify="right")

    for _, row in df.iterrows():
        ov  = row["overall_score"]
        tbl.add_row(
            str(row["score_date"]),
            Text(f"{ov:.1f}", style=score_style(ov)),
            f"{row['sleep_score']:.1f}",
            f"{row['meal_score']:.1f}",
            f"{row['activity_score']:.1f}",
            f"{row['hydration_score']:.1f}",
            f"{row['screen_score']:.1f}",
        )

    console.print(tbl)


def main() -> None:
    db_path = os.path.join(PROJECT_ROOT, "routine.db")
    try:
        session = init_db(db_path)
    except Exception as exc:
        console.print(
            f"[bold red]Failed to initialise database:[/bold red] {exc}"
        )
        sys.exit(1)

    _print_banner()

    try:
        user = _ensure_user_exists(session)
    except KeyboardInterrupt:
        console.print("\n[dim]Setup cancelled.[/dim]")
        sys.exit(0)

    console.print(
        f"[dim]Logged in as:[/dim] [bold]{user.name}[/bold] ({user.email})\n"
    )

    dispatch = {
        "1": ("Log today's habits",   _option_1_log),
        "2": ("View today's report",  _option_2_today_report),
        "3": ("View weekly report",   _option_3_weekly_report),
        "4": ("View score history",   _option_4_history),
    }

    while True:
        try:
            choice = _print_menu()

            if choice == "5":
                console.print("\n[bold cyan]Goodbye! Stay consistent.[/bold cyan]\n")
                break

            label, handler = dispatch[choice]
            console.rule(f"[bold]{label}[/bold]")
            handler(user, session)
            console.print()

        except KeyboardInterrupt:
            console.print("\n\n[dim]Use option 5 to exit.[/dim]\n")
        except ValueError as exc:
            console.print(f"\n[bold red]Input Error:[/bold red] {exc}\n")
        except Exception as exc:
            console.print(f"\n[bold red]Unexpected Error:[/bold red] {exc}\n")

        try:
            Prompt.ask("[dim]Press Enter to continue[/dim]", default="")
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()