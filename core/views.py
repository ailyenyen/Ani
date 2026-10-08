import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from . import auth, services
from .alerts import check_alerts, describe_alert
from .forms import LoginForm, PriceAlertForm, ProfileForm, SignupForm
from .models import DeviceToken, Market, Notification, PriceAlert, SavedCrop, User
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

def home(request):
    db, user = request.db, request.ani_user
    locations = services.list_locations(db)
    location = _location_for(request, locations)

    summaries = services.summarize_by_crop(services.latest_prices(db, location=location or None))
    saved_ids = services.saved_crop_ids(db, user)
    by_id = {s.crop.id: s for s in summaries}
    ordered = [by_id[cid] for cid in saved_ids if cid in by_id]
    ordered += [s for s in summaries if s.crop.id not in saved_ids]

    featured = ordered[0] if ordered else None
    chart = None
    if featured:
        headline = featured.headline
        points = services.price_trend(db, headline.crop, headline.market, 7)
        chart = services.chart_data(points, f"{headline.crop.name} Price — Last 7 Days")

    markets_stmt = select(func.count(Market.id))
    if location:
        markets_stmt = markets_stmt.where(Market.location == location)
    stats = {
        "crop_count": len(summaries),
        "source_count": len(services.list_sources(db)),
        "market_count": db.scalar(markets_stmt),
        "saved_count": len(saved_ids),
        "active_alerts": db.scalar(
            select(func.count(PriceAlert.id)).where(PriceAlert.user_id == user.id, PriceAlert.active.is_(True))
        ) if user else 0,
    }

    return render(
        request,
        "core/home.html",
        {
            "stats": stats,
            "locations": locations,
            "location": location,
            "featured": featured,
            "chart": chart,
            "latest": ordered[:6],
            "has_saved": bool(saved_ids),
            "last_update": services.last_price_date(db),
        },
    )


def market_prices(request):
    db = request.db
    crops = services.list_crops(db)
    locations = services.list_locations(db)
    location = _location_for(request, locations)

    crop_slug = request.GET.get("crop", "")
    crop = next((c for c in crops if c.slug == crop_slug), None)
    when = request.GET.get("when", "today")
    if when not in {key for key, _l, _d in services.WHEN_CHOICES}:
        when = "today"
    category = request.GET.get("category", "")
    source = request.GET.get("source", "")
    sort = request.GET.get("sort", "")

    rows = services.latest_prices(
        db,
        as_of=services.as_of_for(when),
        location=location or None,
        crop_ids=[crop.id] if crop else None,
        category=category or None,
        source=source or None,
    )
    summaries = services.sort_summaries(services.summarize_by_crop(rows), sort)

    return render(
        request,
        "core/prices.html",
        {
            "crops": crops,
            "locations": locations,
            "location": location,
            "selected_crop": crop,
            "when": when,
            "when_choices": services.WHEN_CHOICES,
            "categories": services.list_categories(db),
            "sources": services.list_sources(db),
            "category": category,
            "source": source,
            "sort": sort,
            "more_filters_open": bool(category or source or sort),
            "summaries": summaries,
        },
    )


def crop_detail(request, slug):
    db, user = request.db, request.ani_user
    crop = services.get_crop(db, slug)
    if crop is None:
        raise Http404("Crop not found")
    locations = services.list_locations(db)
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

    chart = None
    if headline:
        range_label = dict(services.RANGE_CHOICES)[days]
        points = services.price_trend(db, crop, headline.market, days)
        chart = services.chart_data(points, f"{crop.name} Price — Last {range_label}")

    return render(
        request,
        "core/crop_detail.html",
        {
            "crop": crop,
            "locations": locations,
            "location": location,
            "rows": rows,
            "headline": headline,
            "chart": chart,
            "days": days,
            "range_choices": services.RANGE_CHOICES,
            "range_label": dict(services.RANGE_CHOICES)[days],
            "stats": services.price_stats(db, crop, location, days) if rows else None,
            "is_saved": crop.id in services.saved_crop_ids(db, user),
        },
    )


def compare(request):
    db, user = request.db, request.ani_user
    crops = services.list_crops(db)
    locations = services.list_locations(db)
    location = _location_for(request, locations, require_specific=True)

    crop_slug = request.GET.get("crop")
    crop = next((c for c in crops if c.slug == crop_slug), None)
    if crop is None:
        saved_ids = services.saved_crop_ids(db, user)
        crop = next((c for c in crops if c.id in saved_ids[:1]), crops[0] if crops else None)

    rows, best, chart, chart_height = [], None, None, 0
    if crop is not None:
        rows = services.compare_markets(db, crop, location)
    if rows:
        best = rows[0]
        chart = {
            "title": f"{crop.name} Price by Market",
            "labels": [r.market.name for r in rows],
            "values": [float(r.price) for r in rows],
            "colors": [services.MARKET_COLORS[services.market_color_index(r.market.name)] for r in rows],
            "bestIndex": 0,
        }
        chart_height = 70 * len(rows) + 30
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
            "chart_height": chart_height,
        },
    )


# --- Price alerts -----------------------------------------------------------

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
    current = _headlines_by_crop(db, user.location, [a.crop_id for a in user_alerts]) if user_alerts else {}
    notifications = list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(10)
        )
    )
    items = [
        {"alert": a, "text": describe_alert(a), "current": current.get(a.crop_id)} for a in user_alerts
    ]
    response = render(
        request, "core/alerts.html", {"items": items, "notifications": notifications}
    )
    # Notifications count as read once this page has been shown.
    unread_ids = [n.id for n in notifications if not n.is_read]
    if unread_ids:
        db.execute(update(Notification).where(Notification.id.in_(unread_ids)).values(is_read=True))
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
        return redirect("alerts")

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
    return redirect("alerts")


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
    current = _headlines_by_crop(db, user.location, [s.crop_id for s in saved]) if saved else {}
    items = [{"saved": s, "summary": current.get(s.crop_id)} for s in saved]
    return render(request, "core/my_crops.html", {"items": items})


@auth.login_required
def my_crops_add(request):
    db, user = request.db, request.ani_user
    if request.method == "POST":
        crop = services.get_crop(db, request.POST.get("crop", ""))
        if crop is None:
            return HttpResponseBadRequest("Unknown crop")
        if crop.id not in services.saved_crop_ids(db, user):
            db.add(SavedCrop(user_id=user.id, crop_id=crop.id))
            db.commit()
            messages.success(request, f"{crop.name} was added to My Crops.")
        else:
            messages.info(request, f"{crop.name} is already in My Crops.")
        return redirect(_safe_next(request, reverse("my_crops")))

    saved_ids = set(services.saved_crop_ids(db, user))
    available = [c for c in services.list_crops(db) if c.id not in saved_ids]
    return render(request, "core/my_crops_add.html", {"crops": available})


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
    return redirect("home")


# --- Errors -----------------------------------------------------------------

def page_not_found(request, exception=None):
    return render(request, "core/404.html", status=404)


def server_error(request):
    return HttpResponse(render_to_string("core/500.html"), status=500)
