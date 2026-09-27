import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from sqlalchemy.exc import IntegrityError

from db.models import DailyLog

console = Console()

class InputValidator:
    """Contains validation helpers for daily log input fields."""

    @staticmethod
    def validate_time_format(time_str: str) -> bool:
        """Check if time is in HH:MM format."""
        pattern = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
        return bool(re.match(pattern, (time_str or "").strip()))

    @staticmethod
    def validate_score(value: Any, min: int = 1, max: int = 10) -> bool:
        """Check if value is an integer between min and max."""
        try:
            return min <= int(value) <= max
        except (TypeError, ValueError):
            return False

    @staticmethod
    def validate_positive_int(value: Any) -> bool:
        """Check if value is a non-negative integer."""
        try:
            return int(value) >= 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def validate_log(log_dict: dict) -> tuple[bool, list[str]]:
        """Validate all fields in a daily log dictionary."""
        errors: list[str] = []
        v = InputValidator

        for field in ("sleep_start", "sleep_end", "wake_time"):
            val = log_dict.get(field, "")
            if not v.validate_time_format(val):
                errors.append(f"'{field}' must be in HH:MM format. Got: {val!r}")

        raw_meals = log_dict.get("meal_times", "[]")
        try:
            meals = json.loads(raw_meals)
            if not isinstance(meals, list):
                raise ValueError
            for mt in meals:
                if not v.validate_time_format(mt):
                    errors.append(f"Meal time {mt!r} is not in HH:MM format.")
        except (ValueError, json.JSONDecodeError):
            errors.append("'meal_times' must be a JSON array of HH:MM strings.")

        for field in ("steps", "water_ml", "screen_min"):
            val = log_dict.get(field)
            if not v.validate_positive_int(val):
                errors.append(f"'{field}' must be a non-negative integer. Got: {val!r}")

        for field in ("mood_score", "energy_score", "productivity_score"):
            val = log_dict.get(field)
            if not v.validate_score(val):
                errors.append(f"'{field}' must be an integer between 1 and 10. Got: {val!r}")

        return (len(errors) == 0), errors


class InputCollector:
    """Prompts the user for log entries, validates them, and saves to the database."""

    @staticmethod
    def parse_meal_times(raw: str) -> str:
        """Convert a comma-separated HH:MM string to a JSON array."""
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
        bad = [t for t in tokens if not InputValidator.validate_time_format(t)]
        if bad:
            raise ValueError(f"Invalid meal time(s): {bad}")
        return json.dumps(tokens)

    @staticmethod
    def _calc_sleep_duration(sleep_start: str, sleep_end: str) -> float:
        """Compute sleep duration accounting for midnight crossover."""
        fmt = "%H:%M"
        start_dt = datetime.strptime(sleep_start, fmt)
        end_dt   = datetime.strptime(sleep_end,   fmt)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        delta = end_dt - start_dt
        return round(delta.total_seconds() / 3600, 2)

    @staticmethod
    def _prompt_time(label: str) -> str:
        """Prompt for a valid HH:MM time."""
        while True:
            val = Prompt.ask(f"  [cyan]{label}[/cyan] [dim](HH:MM)[/dim]").strip()
            if InputValidator.validate_time_format(val):
                return val
            console.print(f"    [red]Invalid time. Try again.[/red]")

    @staticmethod
    def _prompt_score(label: str) -> int:
        """Prompt for a 1-10 validation score."""
        while True:
            val = Prompt.ask(f"  [cyan]{label}[/cyan] [dim](1-10)[/dim]").strip()
            if InputValidator.validate_score(val):
                return int(val)
            console.print("    [red]Must be a whole number between 1 and 10.[/red]")

    @staticmethod
    def _prompt_positive_int(label: str, unit: str = "") -> int:
        """Prompt for a positive integer value."""
        suffix = f" [dim]({unit})[/dim]" if unit else ""
        while True:
            val = Prompt.ask(f"  [cyan]{label}[/cyan]{suffix}").strip()
            if InputValidator.validate_positive_int(val):
                return int(val)
            console.print("    [red]Must be a non-negative whole number.[/red]")

    def collect_daily_log(self, user_id: int, session) -> dict:
        """Ask user for daily habits using terminal inputs."""
        console.print(f"\n[bold green]Daily Log Entry[/bold green] (User: {user_id} | Date: {date.today()})")

        console.print("\n[bold]Sleep[/bold]")
        sleep_start = self._prompt_time("Sleep start")
        sleep_end   = self._prompt_time("Sleep end")
        wake_time   = self._prompt_time("Wake time")
        sleep_duration_hr = self._calc_sleep_duration(sleep_start, sleep_end)
        console.print(f"    [dim]Calculated sleep duration:[/dim] [bold]{sleep_duration_hr}[/bold] hrs")

        console.print("\n[bold]Meals[/bold]")
        while True:
            raw_meals = Prompt.ask("  [cyan]Meal times[/cyan] [dim](comma-separated HH:MM)[/dim]").strip()
            try:
                meal_times_json = self.parse_meal_times(raw_meals)
                break
            except ValueError as exc:
                console.print(f"    [red]{exc}. Please try again.[/red]")

        console.print("\n[bold]Activity & Hydration[/bold]")
        steps     = self._prompt_positive_int("Steps taken today", "steps")
        water_ml  = self._prompt_positive_int("Water consumed", "ml")
        screen_min = self._prompt_positive_int("Screen time", "minutes")

        console.print("\n[bold]Wellbeing (1 = very poor, 10 = excellent)[/bold]")
        mood_score         = self._prompt_score("Mood score")
        energy_score       = self._prompt_score("Energy score")
        productivity_score = self._prompt_score("Productivity score")

        notes = Prompt.ask("\n  [cyan]Notes[/cyan] [dim](optional)[/dim]", default="").strip() or None

        log_data = {
            "user_id":            user_id,
            "log_date":           date.today(),
            "sleep_start":        sleep_start,
            "sleep_end":          sleep_end,
            "wake_time":          wake_time,
            "sleep_duration_hr":  sleep_duration_hr,
            "meal_times":         meal_times_json,
            "steps":              steps,
            "water_ml":           water_ml,
            "screen_min":         screen_min,
            "mood_score":         mood_score,
            "energy_score":       energy_score,
            "productivity_score": productivity_score,
            "notes":              notes,
        }

        is_valid, errors = InputValidator.validate_log(log_data)
        if not is_valid:
            console.print("\n[bold red]Validation errors:[/bold red]")
            for err in errors:
                console.print(err)
            raise ValueError("Log validation failed.")

        self._print_preview(log_data)
        return log_data

    @staticmethod
    def _print_preview(log_data: dict) -> None:
        """Show a table of the recorded input data."""
        table = Table(title="Log Preview", show_header=True, header_style="bold magenta")
        table.add_column("Field", style="dim")
        table.add_column("Value", style="white")

        fields = [
            ("Date", str(log_data["log_date"])),
            ("Sleep start", log_data["sleep_start"]),
            ("Sleep end", log_data["sleep_end"]),
            ("Wake time", log_data["wake_time"]),
            ("Sleep duration (hr)", str(log_data["sleep_duration_hr"])),
            ("Meal times", log_data["meal_times"]),
            ("Steps", str(log_data["steps"])),
            ("Water (ml)", str(log_data["water_ml"])),
            ("Screen time (min)", str(log_data["screen_min"])),
            ("Mood", str(log_data["mood_score"])),
            ("Energy", str(log_data["energy_score"])),
            ("Productivity", str(log_data["productivity_score"])),
            ("Notes", log_data["notes"] or "-"),
        ]
        for label, value in fields:
            table.add_row(label, value)

        console.print()
        console.print(table)

    @staticmethod
    def save_log(log_data: dict, session) -> int:
        """Insert the user log into the Database."""
        try:
            log = DailyLog(
                user_id            = log_data["user_id"],
                log_date           = log_data["log_date"],
                sleep_start        = log_data["sleep_start"],
                sleep_end          = log_data["sleep_end"],
                wake_time          = log_data["wake_time"],
                sleep_duration_hr  = log_data["sleep_duration_hr"],
                meal_times         = log_data["meal_times"],
                steps              = log_data["steps"],
                water_ml           = log_data["water_ml"],
                screen_min         = log_data["screen_min"],
                mood_score         = log_data["mood_score"],
                energy_score       = log_data["energy_score"],
                productivity_score = log_data["productivity_score"],
                notes              = log_data.get("notes"),
            )
            session.add(log)
            session.commit()
            session.refresh(log)

        except IntegrityError as exc:
            session.rollback()
            detail = str(exc.orig)
            if "UNIQUE" in detail.upper():
                raise ValueError(
                    f"A log already exists for user {log_data['user_id']} on {log_data['log_date']}."
                ) from exc
            raise ValueError(f"Database error: {detail}") from exc
        except Exception as exc:
            session.rollback()
            raise ValueError(f"Unexpected error: {exc}") from exc

        console.print(f"\n[bold green]Log saved![/bold green] log_id={log.log_id} | date={log.log_date.isoformat()}")
        return log.log_id
