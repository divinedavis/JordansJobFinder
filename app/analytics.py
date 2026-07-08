"""Year-in-review analytics + market salary research.

Two pure-ish helpers that the Analytics and Research tabs render:

- :func:`build_application_analytics` turns a user's durable AppliedJob history
  (see app/applications.py) into weekly / monthly counts and a year-in-review
  summary. It takes plain rows + an injectable ``now`` so it's trivial to test.
- :func:`build_market_research` aggregates real salary figures off the Job table
  per market (city) so the user can see what each market pays and what to ask
  for given their experience level.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import ceil, floor

from sqlalchemy import select

from .models import AppliedJob, Job
from .parsing import parse_salary

# City slug (as stored on Job.city / AppliedJob.city) -> human label. Mirrors
# the maps in results.py / sync.py; kept local so this module stays standalone.
CITY_LABELS = {
    "nyc": "New York, NY",
    "atlanta": "Atlanta, GA",
    "miami": "Miami, FL",
    "dallas": "Dallas, TX",
    "houston": "Houston, TX",
    "dc": "Washington, DC",
    "la": "Los Angeles, CA",
    "york-pa": "York, PA",
    "lancaster-pa": "Lancaster, PA",
    "philadelphia-pa": "Philadelphia, PA",
    "harrisburg-pa": "Harrisburg, PA",
    "baltimore-md": "Baltimore, MD",
    "tampa-fl": "Tampa, FL",
    "orlando-fl": "Orlando, FL",
    "jacksonville-fl": "Jacksonville, FL",
    "florida-other": "Florida (other)",
    "charleston-sc": "Charleston, SC",
    "columbia-sc": "Columbia, SC",
    "greenville-sc": "Greenville, SC",
    "rock-hill-sc": "Rock Hill, SC",
}
_LABEL_TO_SLUG = {label: slug for slug, label in CITY_LABELS.items()}

VERTICAL_LABELS = {
    "pm": "Product / Program / IT Manager",
    "finance": "Corporate Finance",
    "sales": "Corporate Sales",
    "it": "IT Project/Program Manager",
    "hr": "HR Coordinator+",
    "scm": "Supply Chain (SC)",
}

# Drop obviously-bogus salaries before averaging (scraper occasionally pulls a
# stray number out of page HTML). Below the floor / above the ceiling = noise.
SANE_SALARY_MIN = 40_000
SANE_SALARY_MAX = 1_000_000

# Experience bucket -> (low, high) percentile band to target when negotiating.
# More experience => aim higher in the observed market range.
EXPERIENCE_BANDS = {
    "0-2": (0.25, 0.50),
    "3-6": (0.50, 0.75),
    "7-9": (0.65, 0.90),
    "10+": (0.75, 1.00),
}
EXPERIENCE_LABELS = {
    "0-2": "0-2 years",
    "3-6": "3-6 years",
    "7-9": "7-9 years",
    "10+": "10+ years",
}


def _naive(dt):
    """Coerce to naive UTC. SQLite stores naive datetimes; normalize both sides
    before any comparison or grouping."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _monday(d: datetime):
    """Midnight on the Monday of d's week (ISO week anchor)."""
    return (d - timedelta(days=d.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _usd_k(value) -> str:
    """Compact money label, e.g. 185000 -> '$185K'."""
    if value is None:
        return "—"
    return f"${round(value / 1000):,}K"


def _percentile(sorted_vals, p):
    """Linear-interpolation percentile (p in 0..1) over a pre-sorted list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    lo, hi = floor(k), ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _with_pct(series):
    """Attach a 0-100 bar percentage (relative to the series max) to each row."""
    top = max((row["count"] for row in series), default=0)
    for row in series:
        row["pct"] = round(row["count"] / top * 100) if top else 0
    return series


def _trim_leading_zeros(series):
    """Drop zero rows before the first period with activity. The 12-period
    window is a ceiling, not a quota — a user whose history starts in June
    shouldn't stare at ten empty months above it. Once real history fills the
    window this is a no-op, so the chart stays a rolling last-12."""
    first = next((i for i, row in enumerate(series) if row["count"]), None)
    return series if first is None else series[first:]


# ── Analytics (year in review) ────────────────────────────────────────────────


def build_application_analytics(applications, now=None, months=12, weeks=12):
    """Weekly + monthly application counts and a year-in-review summary.

    ``applications`` is a list of AppliedJob rows (only ``applied_at``,
    ``vertical`` and ``city`` are read). ``now`` is injectable for tests.
    """
    now = _naive(now) or datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [a for a in applications if a.applied_at is not None]
    dates = sorted(_naive(a.applied_at) for a in rows)
    total = len(dates)

    # Monthly series — contiguous, oldest -> newest, zero-filled.
    month_counts = Counter((d.year, d.month) for d in dates)
    seq, y, m = [], now.year, now.month
    for _ in range(months):
        seq.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    monthly = [
        {
            "key": f"{yy}-{mm:02d}",
            "label": datetime(yy, mm, 1).strftime("%b %Y"),
            "short": datetime(yy, mm, 1).strftime("%b"),
            "count": month_counts.get((yy, mm), 0),
        }
        for yy, mm in reversed(seq)
    ]
    monthly = _trim_leading_zeros(monthly)
    _with_pct(monthly)

    # Weekly series — Monday anchored, contiguous, zero-filled.
    week_counts = Counter(_monday(d).date() for d in dates)
    cur_monday = _monday(now).date()
    weekly = [
        {
            "key": wk.isoformat(),
            "label": f"Week of {wk.strftime('%b %-d')}",
            "short": wk.strftime("%-m/%-d"),
            "count": week_counts.get(wk, 0),
        }
        for wk in reversed([cur_monday - timedelta(weeks=i) for i in range(weeks)])
    ]
    weekly = _trim_leading_zeros(weekly)
    _with_pct(weekly)

    # Breakdowns.
    vert_counts = Counter(a.vertical or "pm" for a in rows)
    by_vertical = [
        {"key": k, "label": VERTICAL_LABELS.get(k, k.title()), "count": c}
        for k, c in vert_counts.most_common()
    ]
    city_counts = Counter((a.city or "") for a in rows if a.city)
    by_city = [
        {"key": k, "label": CITY_LABELS.get(k, k), "count": c}
        for k, c in city_counts.most_common()
    ]

    busiest_month = max(monthly, key=lambda r: r["count"]) if total else None
    busiest_week = max(weekly, key=lambda r: r["count"]) if total else None

    active_weeks = max(1, sum(1 for w in weekly if w["count"] > 0))
    summary = {
        "total": total,
        "this_week": week_counts.get(cur_monday, 0),
        "this_month": month_counts.get((now.year, now.month), 0),
        "this_year": sum(1 for d in dates if d.year == now.year),
        "last_30_days": sum(1 for d in dates if d >= now - timedelta(days=30)),
        "first_applied": dates[0] if dates else None,
        "avg_per_active_week": round(total / active_weeks, 1) if total else 0,
        "busiest_month": busiest_month,
        "busiest_week": busiest_week,
    }

    return {
        "summary": summary,
        "monthly": monthly,
        "weekly": weekly,
        "by_vertical": by_vertical,
        "by_city": by_city,
    }


# ── Leaderboard (all users) ───────────────────────────────────────────────────


def _display_name(email) -> str:
    """Leaderboard display name — the part before the @, so full addresses stay
    off a page every signed-in user can see."""
    return (email or "").split("@")[0] or "user"


def build_application_leaderboard(rows, now=None, current_user_id=None):
    """Per-user application counts for the leaderboard on the Analytics tab.

    ``rows`` is ``(user_id, email, applied_at-or-None)`` — one row per
    application, plus a single ``applied_at=None`` row for users with no
    applications (produced by an outer join). That way EVERY user appears on
    the board, even with a zero week / month / year. ``now`` is injectable
    for tests. Sorted by total descending, then name.

    Privacy: only the viewer (``current_user_id``) sees their own name; every
    other member is shown anonymously as "Member". Otherwise the board would
    disclose every user's identity (email local part) and activity to anyone
    signed in.
    """
    now = _naive(now) or datetime.now(timezone.utc).replace(tzinfo=None)
    cur_monday = _monday(now)
    users = {}
    for user_id, email, applied_at in rows:
        is_self = current_user_id is not None and user_id == current_user_id
        entry = users.setdefault(
            user_id,
            {
                "user_id": user_id,
                # Never render other members' email-derived names.
                "name": _display_name(email) if is_self else "Member",
                "total": 0,
                "this_week": 0,
                "this_month": 0,
                "this_year": 0,
            },
        )
        d = _naive(applied_at)
        if d is None:
            continue
        entry["total"] += 1
        if d.year == now.year:
            entry["this_year"] += 1
            if d.month == now.month:
                entry["this_month"] += 1
        if d >= cur_monday:
            entry["this_week"] += 1
    board = sorted(users.values(), key=lambda u: (-u["total"], u["name"].lower()))
    for rank, entry in enumerate(board, start=1):
        entry["rank"] = rank
    return board


# ── Research (market value) ───────────────────────────────────────────────────


def _salary_points_for(jobs):
    """Representative salary per job (midpoint of min/max when both exist),
    filtered to sane values and returned sorted ascending."""
    points = []
    for j in jobs:
        vals = [
            v
            for v in (j.salary_min, j.salary_max)
            if v and SANE_SALARY_MIN <= v <= SANE_SALARY_MAX
        ]
        if vals:
            points.append(sum(vals) / len(vals))
    return sorted(points)


def _market_stats(points, experience_bucket):
    """Distribution + a suggested-ask band for one market's salary points."""
    p25 = _percentile(points, 0.25)
    p50 = _percentile(points, 0.50)
    p75 = _percentile(points, 0.75)
    lo_pct, hi_pct = EXPERIENCE_BANDS.get(experience_bucket, (0.50, 0.75))
    ask_low = _percentile(points, lo_pct)
    ask_high = _percentile(points, hi_pct)
    return {
        "count": len(points),
        "min": points[0],
        "p25": p25,
        "median": p50,
        "p75": p75,
        "max": points[-1],
        "ask_low": ask_low,
        "ask_high": ask_high,
        "min_fmt": _usd_k(points[0]),
        "p25_fmt": _usd_k(p25),
        "median_fmt": _usd_k(p50),
        "p75_fmt": _usd_k(p75),
        "max_fmt": _usd_k(points[-1]),
        "ask_low_fmt": _usd_k(ask_low),
        "ask_high_fmt": _usd_k(ask_high),
    }


def _applied_point(applied_row, job):
    """Numeric salary for one application. Prefers the linked Job's real
    min/max; falls back to parsing the snapshot salary_label string."""
    vals = []
    if job is not None:
        vals = [
            v
            for v in (job.salary_min, job.salary_max)
            if v and SANE_SALARY_MIN <= v <= SANE_SALARY_MAX
        ]
    if not vals and applied_row.salary_label:
        parsed = parse_salary(applied_row.salary_label)
        if parsed:
            vals = [v for v in parsed if SANE_SALARY_MIN <= v <= SANE_SALARY_MAX]
    if vals:
        return sum(vals) / len(vals)
    return None


def _applied_salary_by_market(db, user_id, vertical):
    """Map city slug -> {count, points} for the user's applications in this
    vertical. ``points`` are the salaries of jobs they actually applied to."""
    rows = db.execute(
        select(AppliedJob, Job)
        .outerjoin(Job, Job.id == AppliedJob.job_id)
        .where(AppliedJob.user_id == user_id, AppliedJob.vertical == vertical)
    ).all()
    by_slug = {}
    for applied_row, job in rows:
        slug = applied_row.city or ""
        bucket = by_slug.setdefault(slug, {"count": 0, "points": []})
        bucket["count"] += 1
        point = _applied_point(applied_row, job)
        if point is not None:
            bucket["points"].append(point)
    for bucket in by_slug.values():
        bucket["points"].sort()
    return by_slug


def _applied_stats(bucket):
    """Salary range + a 'potential' target from the jobs the user applied to.

    ``potential`` is the 75th-percentile of what they applied to — the realistic
    upper end of the offers their actual applications could land."""
    points = bucket["points"]
    if not points:
        return {
            "count": bucket["count"],
            "with_salary": 0,
            "has_salary": False,
        }
    potential = _percentile(points, 0.75)
    median = _percentile(points, 0.50)
    return {
        "count": bucket["count"],
        "with_salary": len(points),
        "has_salary": True,
        "min": points[0],
        "median": median,
        "max": points[-1],
        "potential": potential,
        "min_fmt": _usd_k(points[0]),
        "median_fmt": _usd_k(median),
        "max_fmt": _usd_k(points[-1]),
        "potential_fmt": _usd_k(potential),
    }


def build_market_research(db, cities, vertical="pm", experience_bucket=None, user_id=None):
    """Per-market salary aggregates for the cities on a saved search.

    For each city we pull every Job in that vertical/market that carries a real
    salary, summarize the distribution, and recommend an ask band scaled to the
    user's experience bucket. Markets with no salary data are still listed (so
    the user knows we cover them) but flagged as thin.

    When ``user_id`` is given, each market also carries an ``applied`` block:
    the salary range + a 'potential' target derived from the jobs the user has
    actually applied to in that market.
    """
    applied_by_slug = (
        _applied_salary_by_market(db, user_id, vertical) if user_id else {}
    )

    markets = []
    all_points = []
    applied_all_points = []
    applied_total = 0
    for label in cities:
        slug = _LABEL_TO_SLUG.get(label)
        conditions = [Job.vertical == vertical]
        if slug:
            conditions.append((Job.city == slug) | (Job.location == label))
        else:
            conditions.append(Job.location == label)
        jobs = db.execute(select(Job).where(*conditions)).scalars().all()
        points = _salary_points_for(jobs)
        entry = {
            "city": label,
            "total_postings": len(jobs),
            "has_data": bool(points),
        }
        if points:
            entry.update(_market_stats(points, experience_bucket))
            all_points.extend(points)

        bucket = applied_by_slug.get(slug) if slug else None
        if bucket and bucket["count"]:
            entry["applied"] = _applied_stats(bucket)
            applied_total += bucket["count"]
            applied_all_points.extend(bucket["points"])
        else:
            entry["applied"] = None
        markets.append(entry)

    with_data = [m for m in markets if m["has_data"]]
    top_market = max(with_data, key=lambda m: m["median"]) if with_data else None
    overall = None
    if all_points:
        all_points.sort()
        overall = {
            "count": len(all_points),
            "median": _percentile(all_points, 0.50),
            "median_fmt": _usd_k(_percentile(all_points, 0.50)),
            "p75_fmt": _usd_k(_percentile(all_points, 0.75)),
            "max_fmt": _usd_k(all_points[-1]),
            "top_market": top_market["city"] if top_market else None,
            "top_market_median_fmt": top_market["median_fmt"] if top_market else None,
        }

    applied_overall = None
    if applied_total:
        applied_all_points.sort()
        best_applied = max(
            (m for m in markets if m["applied"] and m["applied"]["has_salary"]),
            key=lambda m: m["applied"]["median"],
            default=None,
        )
        applied_overall = {
            "count": applied_total,
            "with_salary": len(applied_all_points),
            "median_fmt": _usd_k(_percentile(applied_all_points, 0.50))
            if applied_all_points
            else "—",
            "potential_fmt": _usd_k(_percentile(applied_all_points, 0.75))
            if applied_all_points
            else "—",
            "max_fmt": _usd_k(applied_all_points[-1]) if applied_all_points else "—",
            "top_market": best_applied["city"] if best_applied else None,
            "top_market_median_fmt": best_applied["applied"]["median_fmt"]
            if best_applied
            else None,
        }

    return {
        "vertical": vertical,
        "experience_bucket": experience_bucket,
        "experience_label": EXPERIENCE_LABELS.get(experience_bucket, "your level"),
        "markets": markets,
        "overall": overall,
        "applied_overall": applied_overall,
    }
