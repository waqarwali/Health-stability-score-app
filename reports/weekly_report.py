import os
from datetime import date, timedelta
from typing import Optional
from engine.formatting import score_style

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.text import Text

from db.models import DailyLog, StabilityScore
from engine.pattern_detector import PatternDetector
from engine.score_engine import ScoreEngine

console = Console()

_HABIT_LABELS: dict[str, str] = {
    "sleep":       "Sleep",
    "meal_timing": "Meal Timing",
    "activity":    "Activity",
    "hydration":   "Hydration",
    "screen_time": "Screen Time",
}

_PALETTE = {
    "primary":    "#4F9CF9",
    "secondary":  "#F97316",
    "green":      "#22C55E",
    "red":        "#EF4444",
    "yellow":     "#EAB308",
    "bg":         "#0F172A",
    "surface":    "#1E293B",
    "text":       "#E2E8F0",
    "grid":       "#334155",
}

plt.rcParams.update({
    "figure.facecolor": _PALETTE["bg"],
    "axes.facecolor":   _PALETTE["surface"],
    "axes.edgecolor":   _PALETTE["grid"],
    "axes.labelcolor":  _PALETTE["text"],
    "xtick.color":      _PALETTE["text"],
    "ytick.color":      _PALETTE["text"],
    "text.color":       _PALETTE["text"],
    "grid.color":       _PALETTE["grid"],
    "grid.linewidth":   0.6,
    "font.family":      "DejaVu Sans",
    "font.size":        10,
    "legend.facecolor": _PALETTE["surface"],
    "legend.edgecolor": _PALETTE["grid"],
})


def _score_style(score: float) -> str:
    if score >= 75:
        return "bold green"
    if score >= 50:
        return "bold yellow"
    return "bold red"


class WeeklyReporter:
    def __init__(self) -> None:
        self._engine   = ScoreEngine()
        self._detector = PatternDetector()

    def print_weekly_report(self, user_id: int, week_start: date, session) -> None:
        """Print the weekly summary to the terminal."""
        week_end = week_start + timedelta(days=6)

        daily_rows: list[StabilityScore] = (
            session.query(StabilityScore)
            .filter(
                StabilityScore.user_id     == user_id,
                StabilityScore.period_type == "daily",
                StabilityScore.score_date  >= week_start,
                StabilityScore.score_date  <= week_end,
            )
            .order_by(StabilityScore.score_date.asc())
            .all()
        )

        weekly_row: Optional[StabilityScore] = (
            session.query(StabilityScore)
            .filter_by(user_id=user_id, score_date=week_start, period_type="weekly")
            .first()
        )

        prev_start = week_start - timedelta(days=7)
        prev_week: Optional[StabilityScore] = (
            session.query(StabilityScore)
            .filter_by(user_id=user_id, score_date=prev_start, period_type="weekly")
            .first()
        )

        console.rule()
        console.print(f"[bold cyan]Weekly Stability Report[/bold cyan]")
        console.print(
            f"[dim]{week_start.strftime('%d %b %Y')} - "
            f"{week_end.strftime('%d %b %Y')}[/dim]\n"
        )

        if daily_rows:
            avg_score  = np.mean([r.overall_score for r in daily_rows if r.overall_score])
            best_row   = max(daily_rows, key=lambda r: r.overall_score or 0)
            worst_row  = min(daily_rows, key=lambda r: r.overall_score or 0)

            console.print("[bold]Summary[/bold]")
            console.print(
                f"Weekly Average: [{_score_style(avg_score)}]"
                f"{avg_score:.1f}[/{_score_style(avg_score)}]"
            )
            console.print(
                f"Best Day: [green]{best_row.score_date.strftime('%A')} - "
                f"{best_row.overall_score:.1f}[/green]"
            )
            console.print(
                f"Worst Day: [red]{worst_row.score_date.strftime('%A')} - "
                f"{worst_row.overall_score:.1f}[/red]"
            )

            if prev_week and prev_week.overall_score:
                delta = avg_score - prev_week.overall_score
                direction = "improved" if delta >= 0 else "declined"
                col = "green" if delta >= 0 else "red"
                console.print(
                    f"vs Last Week: [{col}]{direction} by "
                    f"{abs(delta):.1f}%[/{col}]"
                )
        else:
            console.print("[dim]No daily scores found for this week.[/dim]")

        stable   = self._detector.get_stable_habits(user_id, session)
        unstable = self._detector.get_unstable_habits(user_id, session)

        habit_tbl = Table(
            title="\nHabit Stability This Week",
            header_style="bold magenta",
        )
        habit_tbl.add_column("Habit", style="white")
        habit_tbl.add_column("Status", justify="center")

        for h in stable:
            habit_tbl.add_row(
                _HABIT_LABELS.get(h, h),
                Text("Stable", style="green"),
            )
        for h in unstable:
            habit_tbl.add_row(
                _HABIT_LABELS.get(h, h),
                Text("Unstable", style="red"),
            )
        console.print(habit_tbl)

        corr = self._detector.calculate_mood_correlation(user_id, session)
        corr_tbl = Table(
            title="\nScore to Wellbeing Correlation (30 days)",
            header_style="bold magenta",
        )
        corr_tbl.add_column("Metric", style="white")
        corr_tbl.add_column("Correlation", justify="right")

        def _corr_text(val: float | None) -> Text:
            if val is None:
                return Text("N/A (insufficient data)", style="dim")
            col = (
                "green"
                if abs(val) >= 0.5
                else "yellow"
                if abs(val) >= 0.3
                else "dim"
            )
            return Text(str(val), style=col)

        corr_tbl.add_row("Mood", _corr_text(corr["mood_corr"]))
        corr_tbl.add_row("Energy", _corr_text(corr["energy_corr"]))
        corr_tbl.add_row(
            "Productivity",
            _corr_text(corr["productivity_corr"]),
        )
        console.print(corr_tbl)
        console.rule()

    def generate_charts(
        self,
        user_id: int,
        session,
        output_dir: str = "output/",
    ) -> dict[str, str]:
        """Generate and save the three analytical charts."""
        os.makedirs(output_dir, exist_ok=True)

        return {
            "daily_trend": self._generate_daily_trend(
                user_id,
                session,
                output_dir,
            ),
            "habit_breakdown": self._generate_habit_breakdown(
                user_id,
                session,
                output_dir,
            ),
            "mood_correlation": self._generate_mood_correlation(
                user_id,
                session,
                output_dir,
            ),
        }

    def _generate_daily_trend(
        self,
        user_id: int,
        session,
        output_dir: str,
    ) -> str:
        """Generate the daily stability trend chart."""
        hist_df = self._engine.get_score_history(
            user_id,
            days=14,
            session=session,
        )
        path1 = os.path.join(output_dir, "daily_trend.png")

        fig, ax = plt.subplots(figsize=(10, 4), dpi=130)

        if not hist_df.empty:
            x = hist_df["score_date"].astype(str)
            y = hist_df["overall_score"]

            ax.plot(
                x,
                y,
                color=_PALETTE["primary"],
                linewidth=2.2,
                marker="o",
                markersize=5,
            )
            ax.fill_between(
                range(len(x)),
                y,
                alpha=0.15,
                color=_PALETTE["primary"],
            )
            ax.axhline(
                75,
                color=_PALETTE["green"],
                linestyle="--",
                linewidth=0.9,
                label="Stable (75)",
            )
            ax.axhline(
                50,
                color=_PALETTE["yellow"],
                linestyle="--",
                linewidth=0.9,
                label="Moderate (50)",
            )
            ax.set_xticks(range(len(x)))
            ax.set_xticklabels(
                x,
                rotation=35,
                ha="right",
                fontsize=8,
            )
            ax.set_xlabel("Date")
            ax.set_ylabel("Stability Score")
            ax.set_ylim(0, 105)
            ax.legend(loc="lower right", fontsize=8)
        else:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        ax.set_title(
            "Daily Stability Score - Last 14 Days",
            pad=12,
        )
        ax.grid(True, axis="y")
        fig.tight_layout()
        fig.savefig(path1)
        plt.close(fig)

        console.print(f"[green]Saved:[/green] {path1}")
        return path1

    def _generate_habit_breakdown(
        self,
        user_id: int,
        session,
        output_dir: str,
    ) -> str:
        """Generate the per-habit stability breakdown chart."""
        path2 = os.path.join(
            output_dir,
            "habit_breakdown.png",
        )

        week_start = date.today() - timedelta(
            days=date.today().weekday()
        )

        weekly_ss: Optional[StabilityScore] = (
            session.query(StabilityScore)
            .filter_by(
                user_id=user_id,
                score_date=week_start,
                period_type="weekly",
            )
            .first()
        )

        fig2, ax2 = plt.subplots(
            figsize=(9, 4),
            dpi=130,
        )

        if weekly_ss:
            habits = [
                "Sleep",
                "Meal Timing",
                "Activity",
                "Hydration",
                "Screen Time",
            ]
            scores = [
                weekly_ss.sleep_score or 0,
                weekly_ss.meal_score or 0,
                weekly_ss.activity_score or 0,
                weekly_ss.hydration_score or 0,
                weekly_ss.screen_score or 0,
            ]

            bar_colors = [
                _PALETTE["green"]
                if s >= 75
                else _PALETTE["yellow"]
                if s >= 50
                else _PALETTE["red"]
                for s in scores
            ]

            bars = ax2.bar(
                habits,
                scores,
                color=bar_colors,
                width=0.55,
                zorder=2,
            )
            ax2.bar_label(
                bars,
                fmt="%.1f",
                padding=4,
                fontsize=9,
            )
            ax2.axhline(
                75,
                color=_PALETTE["green"],
                linestyle="--",
                linewidth=0.8,
            )
            ax2.axhline(
                50,
                color=_PALETTE["yellow"],
                linestyle="--",
                linewidth=0.8,
            )
            ax2.set_ylabel("Stability %")
            ax2.set_ylim(0, 115)
            ax2.grid(True, axis="y", zorder=0)
        else:
            ax2.text(
                0.5,
                0.5,
                "No weekly score available",
                ha="center",
                va="center",
                transform=ax2.transAxes,
            )

        ax2.set_title(
            f"Per-Habit Stability - Week of "
            f"{week_start.strftime('%d %b %Y')}",
            pad=12,
        )
        fig2.tight_layout()
        fig2.savefig(path2)
        plt.close(fig2)

        console.print(f"[green]Saved:[/green] {path2}")
        return path2

    def _generate_mood_correlation(
        self,
        user_id: int,
        session,
        output_dir: str,
    ) -> str:
        """Generate the stability score versus mood chart."""
        path3 = os.path.join(
            output_dir,
            "mood_correlation.png",
        )

        hist30 = self._engine.get_score_history(
            user_id,
            days=30,
            session=session,
        )
        cutoff = date.today() - timedelta(days=30)

        mood_logs: list[DailyLog] = (
            session.query(DailyLog)
            .filter(
                DailyLog.user_id == user_id,
                DailyLog.log_date >= cutoff,
            )
            .all()
        )

        ss_map = {
            r["score_date"]: r["overall_score"]
            for _, r in hist30.iterrows()
        }

        sc_x, sc_y = [], []

        for log in mood_logs:
            ov = ss_map.get(log.log_date)
            if ov is not None and log.mood_score is not None:
                sc_x.append(ov)
                sc_y.append(log.mood_score)

        fig3, ax3 = plt.subplots(
            figsize=(7, 5),
            dpi=130,
        )

        if sc_x:
            ax3.scatter(
                sc_x,
                sc_y,
                color=_PALETTE["secondary"],
                alpha=0.85,
                s=60,
                edgecolors=_PALETTE["bg"],
                linewidths=0.5,
            )

            if len(sc_x) >= 2:
                z = np.polyfit(sc_x, sc_y, 1)
                p = np.poly1d(z)
                xs = np.linspace(
                    min(sc_x),
                    max(sc_x),
                    100,
                )
                ax3.plot(
                    xs,
                    p(xs),
                    color=_PALETTE["primary"],
                    linewidth=1.5,
                    linestyle="--",
                    label="Trend",
                )
                ax3.legend(fontsize=8)

            ax3.set_xlabel("Stability Score")
            ax3.set_ylabel("Mood Score (1-10)")
            ax3.set_xlim(0, 105)
            ax3.set_ylim(0, 11)
            ax3.yaxis.set_major_locator(
                mticker.MultipleLocator(1)
            )
            ax3.grid(True)
        else:
            ax3.text(
                0.5,
                0.5,
                "Insufficient data for correlation",
                ha="center",
                va="center",
                transform=ax3.transAxes,
            )

        ax3.set_title(
            "Stability Score vs Mood Score - Last 30 Days",
            pad=12,
        )
        fig3.tight_layout()
        fig3.savefig(path3)
        plt.close(fig3)

        console.print(f"[green]Saved:[/green] {path3}")
        return path3