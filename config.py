import os

# Database configuration
DATABASE_URL = "sqlite:///healthy_routine.db"

# List of tracked habits
HABITS = ["sleep", "meal_timing", "activity", "hydration", "screen_time"]

# Weightage for score calculation
WEIGHTS = {
    "sleep": 0.30,
    "meal_timing": 0.20,
    "activity": 0.20,
    "hydration": 0.15,
    "screen_time": 0.15
}

# Threshold for detecting significant disruptions
DISRUPTION_THRESHOLD = 2.0
