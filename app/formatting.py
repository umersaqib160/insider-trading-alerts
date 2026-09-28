from datetime import date


def money(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.1f}M" if value < 1e7 else f"${value / 1e6:.0f}M"
    if value >= 1e3:
        return f"${value / 1e3:.0f}K"
    return f"${value:,.0f}"


def shares(value: float) -> str:
    return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def days_ago(day: date, today: date) -> str:
    n = (today - day).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"{n}d ago"
