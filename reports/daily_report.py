from datetime import date
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from db.models import DailyLog, Disruption, HabitScore, StabilityScore
from engine.pattern_detector import PatternDetector
from engine.score_engine import ScoreEngine

console = Console()

_HABIT_LABELS: dict[str, str] = {
    "sleep":       "Sleep",
    "meal_timing": "Meal Timing",
    "activity":    "Activity (Steps)",
    "hydration":   "Hydration (ml)",
    "screen_time": "Screen Time (min)",
}

_SEVERITY_STYLE: dict[str, str] = {
    "low":    "bold yellow",
    "medium": "bold orange3",
    "high":   "bold red",
}

def _score_color(score: float) -> str:
    if score >= 75:
        return "bold green"
    if score >= 50:
        return "bold yellow"
    return "bold red"

def _stability_badge(pct: float) -> Text:
    """Format the stability percentage as colored text."""
    if pct >= 75:
        return Text("Stable", style="green")
    if pct >= 50:
        return Text("Moderate", style="yellow")
    return Text("Unstable", style="red")

class DailyReporter:
    def __init__(self) -> None:
        self._engine   = ScoreEngine()
        self._detector = PatternDetector()

    def print_daily_report(self, user_id: int, log_date: date, session) -> None:
        """Print the daily report to the terminal."""

        today_log: Optional[DailyLog] = (
            session.query(DailyLog)
            .filter_by(user_id=user_id, log_date=log_date)
            .first()
        )
        if today_log is None:
            console.print(f"[bold red]No daily log found for user {user_id} on {log_date}.[/bold red]")
            return

        ss: Optional[StabilityScore] = (
            session.query(StabilityScore)
            .filter_by(user_id=user_id, score_date=log_date, period_type="daily")
            .first()
        )

        console.rule()
        console.print(f"[bold cyan]Daily Stability Report - {log_date.strftime('%A, %d %B %Y')}[/bold cyan]")

        if ss and ss.overall_score is not None:
            score_val = ss.overall_score
            col = _score_color(score_val)
            console.print(f"[bold]Overall Stability Score:[/bold] [{col}]{score_val:.1f} / 100[/{col}]")
        else:
            console.print("[dim]Overall score not yet computed for this day.[/dim]")

        habit_scores: list[HabitScore] = (
            session.query(HabitScore)
            .filter_by(log_id=today_log.log_id, user_id=user_id)
            .all()
        )

        if habit_scores:
            tbl = Table(title="Habit Breakdown", show_header=True, header_style="bold magenta")
            tbl.add_column("Habit", style="white")
            tbl.add_column("Today's Value", style="cyan", justify="right")
            tbl.add_column("7-Day Average", style="blue", justify="right")
            tbl.add_column("Stability %", style="white", justify="right")
            tbl.add_column("Status", justify="center")

            for hs in habit_scores:
                label   = _HABIT_LABELS.get(hs.habit_type, hs.habit_type)
                raw     = f"{hs.raw_value:.2f}" if hs.raw_value is not None else "-"
                mean    = f"{hs.seven_day_mean:.2f}" if hs.seven_day_mean is not None else "-"
                pct     = hs.stability_pct or 0.0
                pct_str = f"{pct:.1f}%"
                badge   = _stability_badge(pct)
                tbl.add_row(label, raw, mean, pct_str, badge)

            console.print(tbl)
        else:
            console.print("[dim]No habit scores found. Run the score engine first.[/dim]")

        disruptions: list[Disruption] = (
            session.query(Disruption)
            .filter_by(log_id=today_log.log_id, user_id=user_id)
            .all()
        )
        console.print()
        if disruptions:
            console.print("[bold red]Disruptions Detected[/bold red]")
            for d in disruptions:
                badge_style = _SEVERITY_STYLE.get(d.severity, "white")
                console.print(f"  [{badge_style}]{d.severity.upper()}[/{badge_style}] {d.description}")
        else:
            console.print("[green]No disruptions detected today.[/green]")

        console.print("\n[bold]Wellbeing Check-in[/bold]")
        wt = Table(show_header=False, box=None)
        wt.add_column(style="dim")
        wt.add_column(style="white")
        wt.add_row("Mood:", str(today_log.mood_score or "-"))
        wt.add_row("Energy:", str(today_log.energy_score or "-"))
        wt.add_row("Productivity:", str(today_log.productivity_score or "-"))
        if today_log.notes:
            wt.add_row("Notes:", today_log.notes)
        console.print(wt)

        suggestions = self._detector.generate_suggestions(user_id, session)
        console.print()
        if suggestions:
            console.print("[bold cyan]Top Suggestions[/bold cyan]")
            for i, s in enumerate(suggestions, 1):
                habit_label = _HABIT_LABELS.get(s["habit_type"], s["habit_type"])
                console.print(f"  [bold]{i}.[/bold] [dim]({habit_label})[/dim] {s['suggestion_text']}")
        else:
            console.print("[green]Great work — no suggestions needed today![/green]")

        console.rule()
