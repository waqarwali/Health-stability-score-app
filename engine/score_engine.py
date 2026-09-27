import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import WEIGHTS
from db.models import DailyLog, HabitScore, StabilityScore

class ScoreEngine:

    def get_seven_day_data(self, user_id: int, reference_date: date, session) -> pd.DataFrame:
        """Fetch the previous 7 days data"""
        rows = (
            session.query(DailyLog)
            .filter(DailyLog.user_id == user_id, DailyLog.log_date < reference_date)
            .order_by(DailyLog.log_date.desc())
            .limit(7)
            .all()
        )
        if not rows:
            return pd.DataFrame(columns=[
                "log_id", "log_date", "sleep_duration_hr",
                "steps", "water_ml", "screen_min", "meal_times",
            ])
        records = [{
            "log_id":           r.log_id,
            "log_date":         r.log_date,
            "sleep_duration_hr": r.sleep_duration_hr or 0.0,
            "steps":            r.steps or 0,
            "water_ml":         r.water_ml or 0,
            "screen_min":       r.screen_min or 0,
            "meal_times":       r.meal_times or "[]",
        } for r in rows]
        return pd.DataFrame(records).sort_values("log_date").reset_index(drop=True)

    @staticmethod
    def compute_habit_stability(values: list[float]) -> dict[str, float]:
        """Convert a list of values to a stability percentage via standard deviation/mean."""
        arr = np.array([v for v in values if v is not None], dtype=float)
        if len(arr) == 0:
            return {"mean": 0.0, "std_dev": 0.0, "cv": 0.0, "stability_pct": 0.0}
        mean    = float(np.mean(arr))
        std_dev = float(np.std(arr, ddof=0))
        cv      = (std_dev / mean * 100) if mean != 0 else 0.0
        return {
            "mean":          round(mean, 4),
            "std_dev":       round(std_dev, 4),
            "cv":            round(cv, 4),
            "stability_pct": round(max(0.0, 100.0 - cv), 4),
        }

    @staticmethod
    def _meal_regularity(meal_times_series: pd.Series) -> list[float]:
        """Determine consistency of the first meal of the day."""
        first_hours: list[float] = []
        for raw in meal_times_series:
            try:
                meals = json.loads(raw or "[]")
                if meals:
                    h, m = map(int, meals[0].split(":"))
                    first_hours.append(h + m / 60.0)
            except Exception:
                continue
        return first_hours

    @staticmethod
    def _save_habit_score(session, log_id: int, user_id: int, habit: str,
                          raw_value: float, stats: dict, today_val: float) -> None:
        """Write a parsed single habit's stability data to the database."""
        existing = session.query(HabitScore).filter_by(log_id=log_id, habit_type=habit).first()
        if existing:
            session.delete(existing)
            session.flush()
        deviation = abs(today_val - stats["mean"]) if stats["mean"] else 0.0
        session.add(HabitScore(
            log_id        = log_id,
            user_id       = user_id,
            habit_type    = habit,
            raw_value     = raw_value,
            seven_day_mean= stats["mean"],
            seven_day_std = stats["std_dev"],
            deviation     = round(deviation, 4),
            stability_pct = stats["stability_pct"],
            is_disrupted  = 0,
        ))

    def compute_daily_score(self, log_id: int, user_id: int, session) -> float:
        """Score each inputted habit over the window, create a composite daily score, and persist it."""
        today_log = session.query(DailyLog).filter_by(log_id=log_id).first()
        if today_log is None:
            raise ValueError(f"No DailyLog found for log_id={log_id}.")

        ref_date = today_log.log_date
        hist_df  = self.get_seven_day_data(user_id, ref_date, session)

        def window(col: str, today_val: float) -> list[float]:
            past = list(hist_df[col]) if col in hist_df.columns else []
            return past + [today_val]

        sleep_val   = today_log.sleep_duration_hr or 0.0
        sleep_stats = self.compute_habit_stability(window("sleep_duration_hr", sleep_val))
        self._save_habit_score(session, log_id, user_id, "sleep", sleep_val, sleep_stats, sleep_val)

        act_val   = float(today_log.steps or 0)
        act_stats = self.compute_habit_stability(window("steps", act_val))
        self._save_habit_score(session, log_id, user_id, "activity", act_val, act_stats, act_val)

        hyd_val   = float(today_log.water_ml or 0)
        hyd_stats = self.compute_habit_stability(window("water_ml", hyd_val))
        self._save_habit_score(session, log_id, user_id, "hydration", hyd_val, hyd_stats, hyd_val)

        scr_val   = float(today_log.screen_min or 0)
        scr_stats = self.compute_habit_stability(window("screen_min", scr_val))
        self._save_habit_score(session, log_id, user_id, "screen_time", scr_val, scr_stats, scr_val)

        past_meals = self._meal_regularity(hist_df["meal_times"]) if "meal_times" in hist_df.columns else []
        today_meals = json.loads(today_log.meal_times or "[]")
        meal_today_val = 0.0
        if today_meals:
            h, m = map(int, today_meals[0].split(":"))
            meal_today_val = h + m / 60.0
        meal_stats = self.compute_habit_stability(past_meals + [meal_today_val])
        self._save_habit_score(session, log_id, user_id, "meal_timing",
                               meal_today_val, meal_stats, meal_today_val)

        session.flush()

        overall_score = round(
            sleep_stats["stability_pct"] * WEIGHTS["sleep"]
            + meal_stats["stability_pct"]  * WEIGHTS["meal_timing"]
            + act_stats["stability_pct"]   * WEIGHTS["activity"]
            + hyd_stats["stability_pct"]   * WEIGHTS["hydration"]
            + scr_stats["stability_pct"]   * WEIGHTS["screen_time"],
            2,
        )

        existing_ss = (
            session.query(StabilityScore)
            .filter_by(user_id=user_id, score_date=ref_date, period_type="daily")
            .first()
        )
        if existing_ss:
            session.delete(existing_ss)
            session.flush()

        session.add(StabilityScore(
            user_id         = user_id,
            score_date      = ref_date,
            period_type     = "daily",
            overall_score   = overall_score,
            sleep_score     = sleep_stats["stability_pct"],
            meal_score      = meal_stats["stability_pct"],
            activity_score  = act_stats["stability_pct"],
            hydration_score = hyd_stats["stability_pct"],
            screen_score    = scr_stats["stability_pct"],
        ))
        session.commit()
        return overall_score

    def compute_weekly_score(self, user_id: int, week_start_date: date, session) -> float:
        """Combine 7 daily StabilityScores into an aggregated weekly row."""
        week_end = week_start_date + timedelta(days=6)
        daily_scores = (
            session.query(StabilityScore)
            .filter(
                StabilityScore.user_id     == user_id,
                StabilityScore.period_type == "daily",
                StabilityScore.score_date  >= week_start_date,
                StabilityScore.score_date  <= week_end,
            ).all()
        )
        if not daily_scores:
            return 0.0

        def avg(vals): return round(float(np.mean(vals)), 2)

        weekly_score = avg([s.overall_score for s in daily_scores if s.overall_score])
        existing = (
            session.query(StabilityScore)
            .filter_by(user_id=user_id, score_date=week_start_date, period_type="weekly")
            .first()
        )
        if existing:
            session.delete(existing)
            session.flush()

        session.add(StabilityScore(
            user_id         = user_id,
            score_date      = week_start_date,
            period_type     = "weekly",
            overall_score   = weekly_score,
            sleep_score     = avg([s.sleep_score     or 0 for s in daily_scores]),
            meal_score      = avg([s.meal_score      or 0 for s in daily_scores]),
            activity_score  = avg([s.activity_score  or 0 for s in daily_scores]),
            hydration_score = avg([s.hydration_score or 0 for s in daily_scores]),
            screen_score    = avg([s.screen_score    or 0 for s in daily_scores]),
        ))
        session.commit()
        return weekly_score

    def get_score_history(self, user_id: int, days: int = 30, session=None) -> pd.DataFrame:
        """Return table data containing the last `days` count of overall scoring."""
        cutoff = date.today() - timedelta(days=days)
        rows = (
            session.query(StabilityScore)
            .filter(
                StabilityScore.user_id     == user_id,
                StabilityScore.period_type == "daily",
                StabilityScore.score_date  >= cutoff,
            )
            .order_by(StabilityScore.score_date.asc())
            .all()
        )
        if not rows:
            return pd.DataFrame(columns=[
                "score_date", "overall_score", "sleep_score", "meal_score",
                "activity_score", "hydration_score", "screen_score",
            ])
        return pd.DataFrame([{
            "score_date":      r.score_date,
            "overall_score":   r.overall_score,
            "sleep_score":     r.sleep_score,
            "meal_score":      r.meal_score,
            "activity_score":  r.activity_score,
            "hydration_score": r.hydration_score,
            "screen_score":    r.screen_score,
        } for r in rows])
