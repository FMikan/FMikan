from render import stats, wrap, width


def days(*counts):
    return [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "contributionCount": c} for i, c in enumerate(counts)]


s = stats(days(1, 2, 0, 3, 4, 5, 0, 1))
assert (s["current"], s["longest"], s["active"]) == (1, 3, 6), s
assert stats(days(1, 0, 0))["current"] == 0
assert stats(days(2, 2, 0))["current"] == 2  # today still empty: streak counts up to yesterday
assert s["busiest"]["contributionCount"] == 5
assert stats(days(*[1] * 400))["months"][-1][1] == 8 and len(stats(days(*[1] * 400))["months"]) == 12
assert all(width(line, 17) <= 300 for line in wrap("a few words " * 30, 17, 300))
print("ok")
