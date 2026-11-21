import json
from collections import defaultdict
from datetime import timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from . import auth, crop_lists, market_overview, services
from .market_overview import REGION_NAMES, region_id
from .alerts import check_alerts, describe_alert
from .crop_browse import catalog, group_summaries
from .forms import LoginForm, PriceAlertForm, ProfileForm, SignupForm
from .models import CropPrice, DeviceToken, Market, Notification, PriceAlert, SavedCrop, User
from .templatetags.ani_tags import peso


# --- Helpers ----------------------------------------------------------------

def _location_for(request, locations, require_specific=False):
    """
    The location the user is looking at. A choice made in a filter is
    remembered for the session; otherwise the user's own province is used.
    """
    value = request.GET.get("location")
    if value is not None:
        if value in ("", "all"):
            request.session["location"] = ""
        elif value in locations:
            request.session["location"] = value

    chosen = request.session.get("location")
    user = request.ani_user
    if chosen is None:
        chosen = user.location if user and user.location in locations else ""
    if chosen not in locations:
        chosen = ""
    if require_specific and not chosen:
        if user and user.location in locations:
            chosen = user.location
        elif locations:
            chosen = locations[0]
    return chosen


def _safe_next(request, default):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return default


def _headlines_by_crop(db, location, crop_ids=None):
    rows = services.latest_prices(db, location=location or None, crop_ids=crop_ids)
    return {s.crop.id: s for s in services.summarize_by_crop(rows)}


def _owned_alert(request, alert_id):
    alert = request.db.get(PriceAlert, alert_id)
    if alert is None or alert.user_id != request.ani_user.id:
        raise Http404
    return alert


# --- Main pages -------------------------------------------------------------

def landing(request):
    """Public page that explains Ani. Signed-in users go straight to their dashboard from "/"."""
    db, user = request.db, request.ani_user
    if user is not None and request.resolver_match.url_name == "landing":
        return redirect("home")

    locations = services.list_locations(db)
    location = _location_for(request, locations, require_specific=True)
    summaries = services.summarize_by_crop(services.latest_prices(db, location=location or None))
    listings = catalog(db)
    grouped = group_summaries(summaries, listings)
    best = None
    if summaries:
        compare_rows = services.compare_markets(db, summaries[0].crop, location)
        best = compare_rows[0] if compare_rows else None

    return render(
        request,
        "core/landing.html",
        {
            "location": location,
            "preview": grouped[:4],
            "today": grouped[:6],
            "best": best,
            "stats": {
                "crop_count": len({item.family.slug for item in listings.values()}),
                "market_count": db.scalar(select(func.count(Market.id))),
                "location_count": len(locations),
                "source_count": len(services.list_sources(db)),
            },
            "last_update": services.last_price_date(db),
        },
    )


def home(request):
    """Market prices: retail, wholesale and farmgate prices for each crop, side by side."""
    db, user = request.db, request.ani_user
    listings = catalog(db)

    region = market_overview.remembered_region(request)

    show = request.GET.get("show", "")
    sort = request.GET.get("sort", "")
    search = request.GET.get("q", "").strip()
    if show not in dict(market_overview.SHOW_CHOICES) or (show == "mine" and not user):
        show = ""
    if sort not in dict(market_overview.SORT_CHOICES):
        sort = ""
    include_psa = not settings.ANI_SAMPLE_DATA_NOTICE
    offered = market_overview.TYPE_KEYS if include_psa else ("retail",)
    types = tuple(kind for kind in offered if kind in request.GET.getlist("types")) or offered

    saved_ids = set(services.saved_crop_ids(db, user))
    saved_families = {listing.family.slug for listing in listings.values() if listing.crop.id in saved_ids}
    cards = market_overview.build_cards(db, listings, region, saved_families, include_psa, types)
    cards = market_overview.filter_and_sort(cards, search, show, sort)

    # Trend: the chosen crop, otherwise the first result that has monthly history.
    chart_options = market_overview.chart_families(cards, region, types) if include_psa else []
    chart_slug = request.GET.get("chart", "")
    chart_card = next((card for card in cards if card.slug == chart_slug), None) or (chart_options[0] if chart_options else (cards[0] if cards else None))
    ranges = {key: months for key, _label, months in market_overview.RANGES}
    span = request.GET.get("range", "12")
    if span not in ranges:
        span = "12"
    chart = None
    if chart_card and include_psa:
        chart = market_overview.price_history(chart_card.slug, region, types, ranges[span], chart_card.lines)
        if chart and len(chart["labels"]) < 2:
            chart = None
    summary_lines = list(reversed(chart_card.lines)) if chart_card else []
    chart_crop = None
    if chart_card:
        chart_crop = next((item.crop for item in listings.values() if item.family.slug == chart_card.slug), None)
    retail_line = chart_card.any_line("retail") if chart_card else None
    chart_price = retail_line.value if retail_line else None

    query = request.GET.copy()
    query.pop("page", None)
    keep = {key: query.getlist(key) for key in ("q", "region", "types", "show", "sort", "chart", "range") if key in query}
    page = Paginator(cards, 10).get_page(request.GET.get("page"))
    newest = max((line.day for card in cards for line in card.lines if line.kind == "retail" and line.day), default=None)

    def link(**changes):
        params = request.GET.copy()
        params.pop("page", None)
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            elif isinstance(value, list):
                params.setlist(key, value)
            else:
                params[key] = value
        return "?" + params.urlencode()

    for card in page.object_list:
        card.chart_link = link(chart=card.slug) + "#trend"

    return render(request, "core/home.html", {
        "page": page,
        "page_numbers": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "page_link": link(),
        "keep": keep,
        "regions": market_overview.REGIONS,
        "region": region,
        "region_name": REGION_NAMES.get(region, "the Philippines"),
        "show": show, "sort": sort, "search": search,
        "types": types,
        "type_choices": [choice for choice in market_overview.PRICE_TYPES if choice[0] in offered],
        "sort_choices": market_overview.SORT_CHOICES,
        "show_links": [("", "All crops", link(show=None))] + ([("mine", "My crops", link(show="mine"))] if user else []),
        "range_links": [(key, label, link(range=key) + "#trend") for key, label, _m in market_overview.RANGES],
        "span": span,
        "chart": chart, "chart_card": chart_card, "summary_lines": summary_lines,
        "insight": market_overview.summary_insight(chart_card) if chart_card else "",
        "chart_crop": chart_crop, "chart_price": chart_price,
        # Shown whatever types are ticked: it always compares retail with farmgate.
        "show_spread": include_psa,
        "newest": newest,
        "include_psa": include_psa,
        "legend": market_overview.legend(include_psa, types),
    })


def market_prices(request):
    db = request.db
    listings = catalog(db)
    families = defaultdict(list)
    for item in listings.values():
        families[item.family.slug].append(item)
    locations = services.list_locations(db)
    location = _location_for(request, locations)

    crop_slug = request.GET.get("crop", "")
    if crop_slug not in families:
        crop_slug = next((item.family.slug for item in listings.values() if item.crop.slug == crop_slug), "")
    when = request.GET.get("when", "today")
    if when not in {key for key, _l, _d in services.WHEN_CHOICES}:
        when = "today"
    category = request.GET.get("category", "")
    source = request.GET.get("source", "")
    sort = request.GET.get("sort", "")
    search = request.GET.get("q", "").strip()
    as_of = services.as_of_for(when)

    rows = services.latest_prices(
        db,
        as_of=as_of,
        location=location or None,
        crop_ids=[item.crop.id for item in families[crop_slug]] if crop_slug else None,
        category=category or None,
        source=source or None,
    )
    summaries = services.sort_summaries(services.summarize_by_crop(rows), sort)

    groups = {group["family"].slug: group for group in group_summaries(summaries, listings)}
    results = []
    for slug, items in families.items():
        if crop_slug and slug != crop_slug:
            continue
        if category and not any(item.crop.category == category for item in items):
            continue
        if slug not in groups and (location or source or when != "today"):
            continue
        family = items[0].family
        searchable = " ".join([family.name, *family.aliases] + [
            f"{item.product} {item.variety} {item.crop.name} {item.specification}" for item in items
        ]).casefold()
        if not all(term in searchable for term in search.casefold().split()):
            continue
        result = groups.get(slug, {"family": family, "listing": items[0]})
        result["varieties"] = sorted({item.variety for item in items})
        results.append(result)

    if sort == "name":
        results.sort(key=lambda group: group["family"].name)
    elif sort in {"price_high", "price_low", "change"}:
        positions = {slug: i for i, slug in enumerate(groups)}
        results.sort(key=lambda group: positions.get(group["family"].slug, len(positions)))

    link_query = {key: value for key, value in {"location": location, "source": source}.items() if value}
    if when != "today":
        link_query["date_to"] = as_of.isoformat()
    return render(
        request,
        "core/prices.html",
        {
            "crops": sorted((items[0].family for items in families.values()), key=lambda family: family.name),
            "locations": locations,
            "location": location,
            "selected_crop": crop_slug,
            "when": when,
            "when_choices": services.WHEN_CHOICES,
            "categories": services.list_categories(db),
            "sources": list(db.scalars(select(CropPrice.source).distinct().order_by(CropPrice.source))),
            "category": category,
            "source": source,
            "sort": sort,
            "more_filters_open": bool(category or source or sort),
            "groups": results,
            "search": search,
            "link_query": urlencode(link_query),
        },
    )


def crop_detail(request, slug):
    db, user = request.db, request.ani_user
    crop = services.get_crop(db, slug)
    if crop is None:
        raise Http404("Crop not found")
    locations = services.list_locations(db, crop.id)
    location = _location_for(request, locations, require_specific=True)
    try:
        days = int(request.GET.get("range", 7))
    except ValueError:
        days = 7
    if days not in {d for d, _ in services.RANGE_CHOICES}:
        days = 7

    rows = services.latest_prices(db, location=location, crop_ids=[crop.id])
    rows.sort(key=lambda r: -r.price)
    headline = services.pick_headline(rows) if rows else None

    histories = services.market_price_history(db, crop, days)
    requested = set(request.GET.getlist("trend_market"))
    if "trend_market" in request.GET:
        selected = [market_id for market_id in histories if market_id in requested]
    else:
        preferred = ([headline] if headline else []) + rows
        selected = list(dict.fromkeys(str(row.market.id) for row in preferred if str(row.market.id) in histories))[:2]
        if not selected:
            selected = list(histories)[:2]

    dates = sorted({day for market_id in selected for day in histories[market_id]["points"]})
    series = [
        {"label": histories[market_id]["label"],
         "values": [histories[market_id]["points"].get(day) for day in dates]}
        for market_id in selected
    ]
    trend_chart = {"labels": [day.isoformat() for day in dates], "series": series, "unit": crop.unit} if series else None

    return render(
        request,
        "core/crop_detail.html",
        {
            "crop": crop,
            "locations": locations,
            "location": location,
            "rows": rows,
            "headline": headline,
            "trend_chart": trend_chart,
            "trend_markets": histories,
            "selected_markets": selected,
            "days": days,
            "range_choices": services.RANGE_CHOICES,
            "range_label": dict(services.RANGE_CHOICES)[days],
            "stats": services.price_stats(db, crop, location, days) if rows else None,
            "is_saved": crop.id in services.saved_crop_ids(db, user),
        },
    )


def compare(request):
    from .models import RegionalQuote
    from .regional_views import regional_report
    if request.db.scalar(select(RegionalQuote.id).limit(1)):
        return regional_report(request)
    db, user = request.db, request.ani_user
    crops = services.list_crops(db)
    locations = services.list_locations(db)
    location = _location_for(request, locations, require_specific=True)

    crop_slug = request.GET.get("crop")
    crop = next((c for c in crops if c.slug == crop_slug), None)
    if crop is None:
        saved_ids = services.saved_crop_ids(db, user)
        crop = next((c for c in crops if c.id in saved_ids[:1]), crops[0] if crops else None)

    when = request.GET.get("when", "today")
    if when not in {key for key, _l, _d in services.WHEN_CHOICES}:
        when = "today"

    rows, best, chart = [], None, None
    if crop is not None:
        rows = services.compare_markets(db, crop, location, as_of=services.as_of_for(when))
    if rows:
        best = rows[0]
        # The chart keeps markets in a fixed order (and colour) so it reads the same every time;
        # the list below is sorted by price.
        chart_rows = sorted(rows, key=lambda r: (services.market_color_index(r.market.name), r.market.name))
        chart = {
            "title": f"{crop.name} Price by Market",
            "labels": [r.market.name for r in chart_rows],
            "values": [float(r.price) for r in chart_rows],
            "colors": [services.MARKET_COLORS[services.market_color_index(r.market.name)] for r in chart_rows],
            "bestIndex": chart_rows.index(best),
        }
    comparisons = [
        {
            "row": r,
            "difference": best.price - r.price,
            "is_best": r.price == best.price,
            "color_index": services.market_color_index(r.market.name),
        }
        for r in rows
    ]

    return render(
        request,
        "core/compare.html",
        {
            "crops": crops,
            "crop": crop,
            "locations": locations,
            "location": location,
            "comparisons": comparisons,
            "best": best,
            "chart": chart,
            "when": when,
            "when_choices": services.WHEN_CHOICES,
        },
    )


# --- Price alerts -----------------------------------------------------------

def _alert_dialog_context(db, user, current=None):
    """Choices for the new-alert dialog (every product, My Crops first)."""
    saved_ids = set(services.saved_crop_ids(db, user))
    current = current if current is not None else _headlines_by_crop(db, user.location)
    return crop_lists.alert_choices(db, current, saved_ids, crop_lists.short_region(user.location))


def _alert_progress(alert, summary):
    """Where today's price sits against the target, for the bar on each alert."""
    if summary is None or str(alert.target_price) == crop_lists.REPORT_TARGET:
        return None
    head = summary.headline
    low = head.quote.low if head.quote else head.price
    high = head.quote.high if head.quote else head.price
    target = alert.target_price
    above = alert.condition == PriceAlert.ABOVE
    reached = high > target if above else low < target
    to_go = 0 if reached else (target - high if above else low - target)
    bottom = min(target, low) * Decimal("0.85")
    top = max(target, high) * Decimal("1.1")
    span = (top - bottom) or 1
    place = lambda v: float(round((v - bottom) / span * 100, 1))
    return {"reached": reached, "to_go": to_go, "target_pos": place(target), "low_pos": place(low),
            "width": max(2.0, place(high) - place(low)), "now": head.display_price}


@auth.login_required
def alerts(request):
    db, user = request.db, request.ani_user
    user_alerts = list(
        db.scalars(
            select(PriceAlert)
            .where(PriceAlert.user_id == user.id)
            .options(selectinload(PriceAlert.crop))
            .order_by(PriceAlert.created_at)
        )
    )
    listings = catalog(db)
    current = _headlines_by_crop(db, user.location)
    items = []
    for a in user_alerts:
        summary = current.get(a.crop_id)
        listing = listings.get(a.crop_id)
        items.append({
            "alert": a, "summary": summary, "progress": _alert_progress(a, summary),
            "title": crop_lists.title(listing) if listing else a.crop.name,
            "label": crop_lists.variety_label(listing) if listing else "",
            "report_only": str(a.target_price) == crop_lists.REPORT_TARGET,
            "detail_link": reverse("crop_family", args=[listing.family.slug]) if listing else "",
        })
    alerted = {a.crop_id for a in user_alerts}
    region_short = crop_lists.short_region(user.location)
    waiting = []
    for crop_id in services.saved_crop_ids(db, user):
        listing = listings.get(crop_id)
        if crop_id in alerted or listing is None:
            continue
        summary = current.get(crop_id)
        waiting.append({"listing": listing, "title": crop_lists.title(listing), "label": crop_lists.variety_label(listing),
                        "summary": summary, "low": summary and (summary.headline.quote.low if summary.headline.quote else summary.headline.price),
                        "high": summary and (summary.headline.quote.high if summary.headline.quote else summary.headline.price)})
    return render(request, "core/alerts.html", {
        "items": items, "waiting": waiting, "active_count": sum(1 for a in user_alerts if a.active),
        "push_on": bool(user.push_enabled and user.devices), "region_short": region_short,
        "alert_choices": _alert_dialog_context(db, user, current),
    })


@auth.login_required
def notifications(request):
    """Messages sent by price alerts, newest first."""
    db, user = request.db, request.ani_user
    if request.method == "POST":
        db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
                   .values(is_read=True))
        db.commit()
        messages.success(request, "All notifications are marked as read.")
        return redirect("notifications")
    items = list(db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)
    ))
    today = timezone.localdate()
    groups = defaultdict(list)
    for n in items:
        stamp = n.created_at if timezone.is_aware(n.created_at) else timezone.make_aware(n.created_at, dt_timezone.utc)
        day = timezone.localtime(stamp).date()
        groups["Today" if day == today else "Yesterday" if (today - day).days == 1 else "Earlier"].append(n)
    unread = sum(1 for n in items if not n.is_read)
    response = render(request, "core/notifications.html", {
        "groups": [(label, groups[label]) for label in ("Today", "Yesterday", "Earlier") if groups[label]],
        "unread": unread, "total": len(items),
        "alert_count": db.scalar(select(func.count(PriceAlert.id)).where(PriceAlert.user_id == user.id, PriceAlert.active.is_(True))),
    })
    # They count as read once they have been shown here.
    if unread:
        db.execute(update(Notification).where(Notification.id.in_([n.id for n in items if not n.is_read])).values(is_read=True))
        db.commit()
    return response


@auth.login_required
def alert_new(request):
    db, user = request.db, request.ani_user
    crops = services.list_crops(db)
    initial = {"crop": request.GET.get("crop", ""), "condition": PriceAlert.ABOVE}
    form = PriceAlertForm(request.POST or None, crops=crops, initial=initial)

    if request.method == "POST" and form.is_valid():
        crop = next(c for c in crops if c.slug == form.cleaned_data["crop"])
        alert = PriceAlert(
            user_id=user.id,
            crop_id=crop.id,
            target_price=form.cleaned_data["target_price"],
            condition=form.cleaned_data["condition"],
            active=True,
        )
        db.add(alert)
        db.commit()
        word = "above" if alert.condition == PriceAlert.ABOVE else "below"
        messages.success(
            request,
            f"Your price alert is ready. We will tell you when {crop.name} goes {word} "
            f"{peso(alert.target_price)}/{crop.unit}.",
        )
        if check_alerts(db, alert_ids=[alert.id]):
            messages.info(request, "Good news: that price has already been reached. See the message below.")
        # From the pop-up dialog: stay on the page the alert was made from.
        return redirect(_safe_next(request, reverse("alerts")))

    current = _headlines_by_crop(db, user.location)
    crop_options = [{"crop": c, "current": current.get(c.id)} for c in crops]
    return render(request, "core/alert_form.html", {"form": form, "crop_options": crop_options})


@auth.login_required
@require_POST
def alert_toggle(request, alert_id):
    alert = _owned_alert(request, alert_id)
    alert.active = not alert.active
    request.db.commit()
    state = "on" if alert.active else "off"
    messages.success(request, f"{alert.crop.name} alert is now {state}.")
    return redirect(_safe_next(request, reverse("alerts")))


@auth.login_required
@require_POST
def alert_delete(request, alert_id):
    alert = _owned_alert(request, alert_id)
    name = alert.crop.name
    request.db.delete(alert)
    request.db.commit()
    messages.success(request, f"{name} alert was deleted.")
    return redirect("alerts")


# --- My Crops ---------------------------------------------------------------

@auth.login_required
def my_crops(request):
    db, user = request.db, request.ani_user
    saved = list(
        db.scalars(
            select(SavedCrop)
            .where(SavedCrop.user_id == user.id)
            .options(selectinload(SavedCrop.crop))
            .order_by(SavedCrop.created_at)
        )
    )
    listings = catalog(db)
    categories = crop_lists.family_categories(listings)
    current = _headlines_by_crop(db, user.location)
    region_short = crop_lists.short_region(user.location)
    items = []
    for s_ in saved:
        listing = listings.get(s_.crop_id)
        summary = current.get(s_.crop_id)
        head = summary.headline if summary else None
        items.append({
            "saved": s_, "crop": s_.crop, "summary": summary, "fresh": market_overview.freshness(head.date) if head else "old",
            "title": crop_lists.title(listing) if listing else s_.crop.name,
            "tags": crop_lists.tags(listing, categories) if listing else [],
            "ranged": bool(head and head.quote and head.quote.low != head.quote.high),
            "low": head and (head.quote.low if head.quote else head.price),
            "high": head and (head.quote.high if head.quote else head.price),
            "where": head and " · ".join(filter(None, [head.source, crop_lists.short_region(head.market.location) or head.market.location])),
            "detail_link": (reverse("crop_family", args=[listing.family.slug]) + (f"?{urlencode({'region': region_id(user.location)})}" if user.location else "")) if listing else "",
            "other_regions_link": reverse("crop_family", args=[listing.family.slug]) + "?region=&snap=retail#snapshot" if listing else "",
        })
    saved_ids = {s_.crop_id for s_ in saved}
    groups, categories_present = crop_lists.add_groups(db, saved_ids)
    return render(request, "core/my_crops.html", {
        "items": items, "with_price": sum(1 for i in items if i["summary"]),
        "waiting_count": sum(1 for i in items if not i["summary"]),
        "report_alerts": set(db.scalars(select(PriceAlert.crop_id).where(
            PriceAlert.user_id == user.id, PriceAlert.active.is_(True),
            PriceAlert.target_price == Decimal(crop_lists.REPORT_TARGET)))),
        "region_short": region_short, "region_label": crop_lists.region_label(user.location),
        "add_groups": groups, "add_categories": categories_present,
        "report_target": crop_lists.REPORT_TARGET,
        "alert_choices": _alert_dialog_context(db, user, current),
    })


@auth.login_required
def my_crops_add(request):
    db, user = request.db, request.ani_user
    if request.method == "POST":
        crops = [c for c in (services.get_crop(db, slug) for slug in request.POST.getlist("crop")) if c is not None]
        if not crops:
            return HttpResponseBadRequest("Unknown crop")
        saved_ids = set(services.saved_crop_ids(db, user))
        added = [c for c in crops if c.id not in saved_ids]
        for crop in added:
            db.add(SavedCrop(user_id=user.id, crop_id=crop.id))
        db.commit()
        if len(added) == 1:
            messages.success(request, f"{added[0].name} was added to My Crops.")
        elif added:
            messages.success(request, f"{len(added)} crops were added to My Crops.")
        else:
            messages.info(request, "Those crops are already in My Crops.")
        return redirect(_safe_next(request, reverse("my_crops")))
    # The picker lives in a dialog on the My Crops page.
    return redirect(f"{reverse('my_crops')}#add")


@auth.login_required
@require_POST
def my_crops_remove(request, crop_slug):
    db, user = request.db, request.ani_user
    crop = services.get_crop(db, crop_slug)
    saved = crop and db.scalar(
        select(SavedCrop).where(SavedCrop.user_id == user.id, SavedCrop.crop_id == crop.id)
    )
    if saved:
        db.delete(saved)
        db.commit()
        messages.success(request, f"{crop.name} was removed from My Crops.")
    return redirect(_safe_next(request, reverse("my_crops")))


# --- Profile ----------------------------------------------------------------

@auth.login_required
def profile(request):
    return render(request, "core/profile/profile.html")


@auth.login_required
def profile_edit(request):
    db, user = request.db, request.ani_user
    locations = services.list_locations(db)
    initial = {"name": user.name, "email": user.email, "location": user.location}
    form = ProfileForm(request.POST or None, locations=locations, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        other = auth.find_user_by_email(db, data["email"])
        if other is not None and other.id != user.id:
            form.add_error("email", "Another account already uses this email address.")
        else:
            user.name = data["name"].strip()
            user.email = data["email"].strip().lower()
            user.location = data["location"]
            if data["new_password"]:
                user.password = auth.hash_password(data["new_password"])
            db.commit()
            request.session["location"] = user.location
            messages.success(request, "Your information was saved.")
            return redirect("profile")
    return render(request, "core/profile/edit.html", {"form": form})


@auth.login_required
def notification_settings(request):
    db, user = request.db, request.ani_user
    if request.method == "POST":
        user.push_enabled = request.POST.get("push_enabled") == "on"
        db.commit()
        messages.success(request, "Your notification settings were saved.")
        return redirect("notification_settings")
    return render(
        request,
        "core/profile/notifications.html",
        {
            "device_count": len(user.devices),
            "firebase_config": settings.FIREBASE_WEB_CONFIG,
            "vapid_key": settings.FIREBASE_VAPID_KEY,
        },
    )


@auth.login_required
@require_POST
def register_device(request):
    """Saves a Firebase Cloud Messaging token sent by the browser."""
    try:
        token = json.loads(request.body or "{}").get("token", "").strip()
    except (ValueError, AttributeError):
        token = ""
    if not token or len(token) > 512:
        return JsonResponse({"ok": False, "error": "Missing token"}, status=400)
    db = request.db
    device = db.scalar(select(DeviceToken).where(DeviceToken.token == token))
    if device is None:
        db.add(DeviceToken(user_id=request.ani_user.id, token=token))
    else:
        device.user_id = request.ani_user.id
    request.ani_user.push_enabled = True
    db.commit()
    return JsonResponse({"ok": True})


def firebase_service_worker(request):
    body = render_to_string(
        "core/firebase-messaging-sw.js", {"firebase_config": json.dumps(settings.FIREBASE_WEB_CONFIG)}
    )
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


# --- Help -------------------------------------------------------------------

def help_page(request):
    db = request.db
    return render(
        request,
        "core/help.html",
        {"runs": services.latest_scrape_runs(db), "sources": services.list_sources(db)},
    )


# --- Accounts ---------------------------------------------------------------

def login_view(request):
    if request.ani_user:
        return redirect("home")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = auth.authenticate(request.db, form.cleaned_data["email"], form.cleaned_data["password"])
        if user:
            auth.login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect(_safe_next(request, reverse("home")))
        form.add_error(None, "The email or password is not correct. Please try again.")
    return render(request, "core/auth/login.html", {"form": form, "next": request.GET.get("next", "")})


def signup_view(request):
    if request.ani_user:
        return redirect("home")
    db = request.db
    form = SignupForm(request.POST or None, locations=services.list_locations(db))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if auth.find_user_by_email(db, data["email"]):
            form.add_error("email", "An account with this email already exists. Try logging in instead.")
        else:
            user = User(
                name=data["name"].strip(),
                email=data["email"].strip().lower(),
                password=auth.hash_password(data["password"]),
                location=data["location"],
            )
            db.add(user)
            db.commit()
            auth.login(request, user)
            request.session["location"] = user.location
            messages.success(request, f"Welcome to Ani, {user.first_name}! Your account is ready.")
            return redirect(_safe_next(request, reverse("home")))
    return render(request, "core/auth/signup.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    auth.logout(request)
    messages.success(request, "You are now logged out.")
    return redirect("landing")


# --- Errors -----------------------------------------------------------------

def page_not_found(request, exception=None):
    return render(request, "core/404.html", status=404)


def server_error(request):
    return HttpResponse(render_to_string("core/500.html"), status=500)
