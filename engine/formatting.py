def score_style(score: float) -> str:
    if score >= 75:
        return "bold green"
    if score >= 50:
        return "bold yellow"
    return "bold red"