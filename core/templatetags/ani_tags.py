from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def peso(value):
    """35 -> "₱35.00"."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return value
    return f"₱{amount:,.2f}"


@register.filter
def change_text(row):
    """'↑ 5.2%' / '↓ 1.5%' / 'No change' for a PriceRow."""
    pct = row.change_pct
    if pct is None:
        return "New price"
    if row.direction == "same":
        return "No change"
    arrow = "↑" if pct > 0 else "↓"
    return f"{arrow} {abs(pct):.1f}%"


@register.filter
def change_words(row):
    """Spoken form for screen readers and longer labels."""
    pct = row.change_pct
    if pct is None:
        return "No earlier price to compare yet"
    if row.direction == "same":
        return "Same as last week"
    word = "Up" if pct > 0 else "Down"
    return f"{word} {abs(pct):.1f}% from last week"


@register.filter
def updated_label(value):
    if value is None:
        return ""
    today = timezone.localdate()
    if value == today:
        return "Updated today"
    if value == today - timedelta(days=1):
        return "Updated yesterday"
    if value.year == today.year:
        return f"Updated {value:%b} {value.day}"
    return f"Updated {value:%b} {value.day}, {value.year}"


@register.filter
def nice_date(value):
    if value is None:
        return ""
    return f"{value:%B} {value.day}, {value.year}"


@register.simple_tag
def greeting():
    hour = timezone.localtime().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@register.simple_tag(takes_context=True)
def nav_active(context, *names):
    match = getattr(context.get("request"), "resolver_match", None)
    if match and match.url_name in names:
        return mark_safe('aria-current="page"')
    return ""


# Simple line icons (24x24, drawn with currentColor). Important actions always
# pair an icon with a text label.
ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "wheat": '<path d="M12 21V5"/><path d="M12 9c-2.6 0-4.2-1.5-4.6-4 2.6 0 4.2 1.5 4.6 4Z"/>'
    '<path d="M12 9c2.6 0 4.2-1.5 4.6-4-2.6 0-4.2 1.5-4.6 4Z"/>'
    '<path d="M12 14c-2.6 0-4.2-1.5-4.6-4 2.6 0 4.2 1.5 4.6 4Z"/>'
    '<path d="M12 14c2.6 0 4.2-1.5 4.6-4-2.6 0-4.2 1.5-4.6 4Z"/>'
    '<path d="M12 19c-2.6 0-4.2-1.5-4.6-4 2.6 0 4.2 1.5 4.6 4Z"/>'
    '<path d="M12 19c2.6 0 4.2-1.5 4.6-4-2.6 0-4.2 1.5-4.6 4Z"/>',
    "compare": '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "sprout": '<path d="M7 21h10"/><path d="M12 21v-9"/><path d="M12 12c0-3.6-2.6-6-7-6 0 3.6 2.6 6 7 6Z"/>'
    '<path d="M12 10c0-4 2.6-7 7.5-7 0 4-2.6 7-7.5 7Z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7v.5"/><path d="M12 17h.01"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-left": '<path d="m15 6-6 6 6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "pin": '<path d="M12 21s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12Z"/><circle cx="12" cy="9" r="2.5"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
    '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
    "trend": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "store": '<path d="M4 10v10h16V10"/><path d="M3 4h18l-1 6H4L3 4Z"/><path d="M10 20v-5h4v5"/>',
    "shield": '<path d="M12 3 5 6v6c0 4.5 3 8 7 9 4-1 7-4.5 7-9V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1'
    'M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/>',
}


@register.simple_tag
def icon(name, size=24, label=""):
    paths = ICONS.get(name, "")
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="icon icon-{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        "{} focusable=\"false\">{}</svg>",
        name,
        size,
        size,
        aria,
        mark_safe(paths),
    )
