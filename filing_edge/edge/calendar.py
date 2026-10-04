"""NYSE full-session calendar for the challenge years, including Carter closure.

Daily-bar study only: early-close times are not modeled. Dates are US/Eastern.
"""
from bisect import bisect_left, bisect_right
from datetime import date, timedelta


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19*a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2*e + 2*i - h - k) % 7
    m = (a + 11*h + 22*l) // 451
    return date(y, (h+l-7*m+114)//31, (h+l-7*m+114)%31 + 1)


def nth(y, month, weekday, n):
    day = date(y, month, 1)
    return day + timedelta(days=(weekday-day.weekday()) % 7 + 7*(n-1))


def observed(day):
    return day + timedelta(days=-1 if day.weekday() == 5 else 1 if day.weekday() == 6 else 0)


def closures(y):
    ny = date(y, 1, 1)
    memorial = date(y, 5, 31)
    memorial -= timedelta(days=memorial.weekday())
    result = {ny + timedelta(days=1) if ny.weekday() == 6 else ny,
              nth(y, 1, 0, 3), nth(y, 2, 0, 3), easter(y)-timedelta(days=2),
              memorial, observed(date(y, 7, 4)), nth(y, 9, 0, 1),
              nth(y, 11, 3, 4), observed(date(y, 12, 25))}
    if y >= 2022:
        result.add(observed(date(y, 6, 19)))
    if y == 2025:
        result.add(date(2025, 1, 9))
    return result


def sessions(start, end):
    a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if a.year < 2022 or b.year > 2027:
        raise ValueError('Calendar supports 2022–2027 only; extend and verify before other dates.')
    holidays = set().union(*(closures(y) for y in range(a.year, b.year+1)))
    out = []
    while a <= b:
        if a.weekday() < 5 and a not in holidays:
            out.append(a.isoformat())
        a += timedelta(days=1)
    return out


CAL = sessions('2022-01-01', '2027-12-31')


def on_or_after(day):
    i = bisect_left(CAL, str(day))
    if i == len(CAL):
        raise ValueError('Date outside calendar.')
    return CAL[i]


def on_or_before(day):
    i = bisect_right(CAL, str(day))-1
    if i < 0:
        raise ValueError('Date outside calendar.')
    return CAL[i]


def shift(day, n):
    i = bisect_left(CAL, str(day))
    if i == len(CAL) or CAL[i] != str(day) or not 0 <= i+n < len(CAL):
        raise ValueError('Session shift outside calendar or from a non-session.')
    return CAL[i+n]
