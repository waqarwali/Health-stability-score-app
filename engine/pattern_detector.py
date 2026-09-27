from datetime import date, timedelta
from collections import defaultdict

import numpy as np

from config import DISRUPTION_THRESHOLD
from db.models import DailyLog, Disruption, HabitScore, StabilityScore, Suggestion

_SUGGESTIONS: dict[str, list[tuple[int, str]]] = {
    "sleep": [
        (1, "Try to go to bed within 30 minutes of your usual bedtime every night."),
        (2, "Avoid screens for at least 1 hour before your target sleep time."),
        (3, "Set a consistent morning alarm to anchor your rhythm."),
    ],
    "meal_timing": [
        (1, "Aim to eat your first meal within 1 hour of waking up each day."),
        (2, "Space your main meals roughly 5-6 hours apart to stabilise energy."),
        (3, "Prep meals in advance for busy days so timing stays consistent."),
    ],
    "activity": [
        (1, "Schedule a short 20-minute walk at the same time each day."),
        (2, "Break long sitting sessions with a movement break every hour."),
        (3, "Track your daily steps and try to slowly increase them."),
    ],
    "hydration": [
        (1, "Keep a water bottle on your desk and refill it at set intervals."),
        (2, "Drink a full glass of water immediately after waking up."),
        (3, "Set phone reminders to drink water during the day."),
    ],
    "screen_time": [
        (1, "Set a firm screen cut-off time 1 hour before bed."),
        (2, "Use app timers to reduce unplanned screen use."),
        (3, "Replace evening screen time with reading or a walk."),
    ],
}


class PatternDetector:
    """Analyzes habit patterns, logs disruptions, and provides recommendations."""

    def detect_disruptions(self, log_id: int, user_id: int, session) -> list[dict]:
        """Detect habits that drift too far from the 7-day average baseline."""
        habit_scores: list[HabitScore] = (
            session.query(HabitScore).filter_by(log_id=log_id, user_id=user_id).all()
        )
        results: list[dict] = []
        for hs in habit_scores:
            std  = hs.seven_day_std  or 0.0
            dev  = hs.deviation      or 0.0
            mean = hs.seven_day_mean or 0.0
            if std == 0 or mean == 0:
                continue
            threshold = DISRUPTION_THRESHOLD * std
            if dev <= threshold:
                continue
            multiples = dev / std
            severity  = "high" if multiples >= 4.0 else ("medium" if multiples >= 3.0 else "low")
            
            description = (
                f"{hs.habit_type.replace('_', ' ').title()} deviated "
                f"{dev:.2f} units from the 7-day mean of {mean:.2f}."
            )
            hs.is_disrupted = 1
            existing = session.query(Disruption).filter_by(log_id=log_id, habit_type=hs.habit_type).first()
            if existing:
                existing.severity    = severity
                existing.description = description
            else:
                session.add(Disruption(
                    log_id=log_id, user_id=user_id,
                    habit_type=hs.habit_type,
                    severity=severity, description=description,
                ))
            results.append({
                "habit_type":  hs.habit_type,
                "severity":    severity,
                "deviation":   round(dev, 4),
                "std":         round(std, 4),
                "multiples":   round(multiples, 2),
                "description": description,
            })
        session.commit()
        return results

    def get_stable_habits(self, user_id: int, session) -> list[str]:
        """Find habits with a stability percentage above 75% for the last 7 days."""
        cutoff = date.today() - timedelta(days=7)
        rows = (
            session.query(HabitScore)
            .join(DailyLog, HabitScore.log_id == DailyLog.log_id)
            .filter(HabitScore.user_id == user_id, DailyLog.log_date >= cutoff)
            .all()
        )
        return self._filter_by_stability(rows, lambda avg: avg >= 75.0, sort_ascending=False)

    def get_unstable_habits(self, user_id: int, session) -> list[str]:
        """Find habits with an average stability percentage below 60%."""
        cutoff = date.today() - timedelta(days=7)
        rows = (
            session.query(HabitScore)
            .join(DailyLog, HabitScore.log_id == DailyLog.log_id)
            .filter(HabitScore.user_id == user_id, DailyLog.log_date >= cutoff)
            .all()
        )
        return self._filter_by_stability(rows, lambda avg: avg < 60.0, sort_ascending=True)

    @staticmethod
    def _filter_by_stability(rows: list[HabitScore], predicate, sort_ascending: bool = False) -> list[str]:
        """Group scores, apply the check condition, and return sorted habit types."""
        bucket: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            if r.stability_pct is not None:
                bucket[r.habit_type].append(r.stability_pct)
        averages = {h: float(np.mean(v)) for h, v in bucket.items() if v}
        filtered = {h: v for h, v in averages.items() if predicate(v)}
        return sorted(filtered, key=filtered.__getitem__, reverse=not sort_ascending)

    def calculate_mood_correlation(self, user_id: int, session) -> dict[str, float | None]:
        """Measure if higher stability scores lead to higher wellbeing."""
        cutoff = date.today() - timedelta(days=30)
        logs = (
            session.query(DailyLog)
            .filter(DailyLog.user_id == user_id, DailyLog.log_date >= cutoff)
            .order_by(DailyLog.log_date.asc())
            .all()
        )
        if not logs:
            return {"mood_corr": None, "energy_corr": None, "productivity_corr": None}

        ss_map = {
            ss.score_date: ss.overall_score
            for ss in session.query(StabilityScore).filter(
                StabilityScore.user_id     == user_id,
                StabilityScore.period_type == "daily",
                StabilityScore.score_date  >= cutoff,
            ).all()
            if ss.overall_score is not None
        }

        overall_scores, moods, energies, productivities = [], [], [], []
        for log in logs:
            ov = ss_map.get(log.log_date)
            if ov is None or None in (log.mood_score, log.energy_score, log.productivity_score):
                continue
            overall_scores.append(ov)
            moods.append(log.mood_score)
            energies.append(log.energy_score)
            productivities.append(log.productivity_score)

        def safe_corr(x, y):
            if len(x) < 3:
                return None
            return round(float(np.corrcoef(np.array(x), np.array(y))[0, 1]), 2)

        return {
            "mood_corr":         safe_corr(overall_scores, moods),
            "energy_corr":       safe_corr(overall_scores, energies),
            "productivity_corr": safe_corr(overall_scores, productivities),
        }

    def generate_suggestions(self, user_id: int, session) -> list[dict]:
        """Generate tips for any unstable habits tracked."""
        unstable = self.get_unstable_habits(user_id, session)
        if not unstable:
            return []

        today   = date.today()
        week_of = today - timedelta(days=today.weekday())
        inserted: list[Suggestion] = []

        for habit in unstable:
            for prio, text in _SUGGESTIONS.get(habit, []):
                exists = (
                    session.query(Suggestion)
                    .filter_by(user_id=user_id, week_of=week_of,
                               habit_type=habit, suggestion_text=text)
                    .first()
                )
                if exists:
                    inserted.append(exists)
                    continue
                sug = Suggestion(
                    user_id=user_id, week_of=week_of,
                    habit_type=habit, suggestion_text=text,
                    priority=prio, is_shown=0,
                )
                session.add(sug)
                inserted.append(sug)

        session.commit()
        for s in inserted:
            if s.id is None:
                continue
            session.refresh(s)

        top3 = sorted(inserted, key=lambda s: s.priority)[:3]
        return [{
            "id":              s.id,
            "habit_type":      s.habit_type,
            "suggestion_text": s.suggestion_text,
            "priority":        s.priority,
            "week_of":         str(s.week_of),
        } for s in top3]
