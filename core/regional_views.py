import csv
from datetime import date

from django import forms
from django.http import HttpResponse
from django.shortcuts import render
from sqlalchemy import select

from .models import RegionalQuote, CropPrice, Crop, Market
from .regional_reports import build_report, family
from .services import today

DEFAULT_WINDOW = 30
REPORT_WINDOWS = [(1, "Same day only"), (3, "3 days"), (7, "7 days"), (14, "14 days"), (30, "30 days"), (90, "90 days")]


class ReportForm(forms.Form):
    crop = forms.ChoiceField(label="Crop")
    product = forms.ChoiceField(label="Crop specification", required=False)
    report_date = forms.TypedChoiceField(label="Reporting date", required=False, coerce=date.fromisoformat, empty_value=None)
    region = forms.MultipleChoiceField(label="Regions", required=False, widget=forms.CheckboxSelectMultiple)
    source = forms.ChoiceField(label="Source", required=False)
    as_of = forms.DateField(label="As of", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    days = forms.TypedChoiceField(label="Look back", choices=REPORT_WINDOWS, coerce=int, widget=forms.RadioSelect)


def region_label(region):
    code, separator, name = region.partition(" (")
    if not separator or not name.endswith(")"):
        return region
    name = name[:-1]
    if name not in {"CALABARZON", "MIMAROPA", "SOCCSKSARGEN"} and name.isupper():
        name = name.title()
    return f"{name} · {code}"


def regional_report(request):
    db = request.db
    regions = list(db.scalars(select(RegionalQuote.region).distinct().order_by(RegionalQuote.region)))
    sources = sorted(set(db.scalars(select(RegionalQuote.source).distinct())) | set(db.scalars(select(CropPrice.source).distinct())))
    identities = list(db.execute(select(RegionalQuote.product_key, RegionalQuote.product, RegionalQuote.specification).distinct()))
    crops = sorted({family(p) for _, p, _ in identities})
    defaults = {"crop": "Tomato / Kamatis" if "Tomato / Kamatis" in crops else (crops[0] if crops else ""), "as_of": today(), "days": DEFAULT_WINDOW}
    query = request.GET.copy()
    linked_crop = db.scalar(select(Crop).where(Crop.slug == query.get("crop", "")))
    if linked_crop:
        key = linked_crop.slug.removeprefix("market-")
        label = next((p for k,p,_ in identities if k == key), linked_crop.english_name or linked_crop.name)
        selected = family(label)
        query["crop"] = selected if selected in crops else defaults["crop"]
        if any(k == key for k,_,_ in identities):
            query.setdefault("product", key)
    elif query.get("crop") and family(query["crop"]) in crops:
        query["crop"] = family(query["crop"])
    if query:
        for field, value in defaults.items():
            query.setdefault(field, value)
        location = query.get("location")
        if location == "NCR":
            location = next((r for r in regions if r.startswith("NCR (")), location)
        if location in regions and not query.getlist("region"):
            query["region"] = location
    form = ReportForm(query if query else None, initial=defaults)
    form.fields["crop"].choices = [(p,p) for p in crops]
    form.fields["crop"].widget.attrs.update({
        "onchange": "this.form.elements.product.value=''; this.form.elements.report_date.value='';",
        "data-autosubmit": True,
    })
    chosen_crop = query.get("crop", defaults["crop"])
    products = {k: f"{p} · {s}" for k, p, s in identities if family(p) == chosen_crop}
    report_dates = db.scalars(select(RegionalQuote.date).where(
        RegionalQuote.product_key.in_(products), RegionalQuote.date <= defaults["as_of"],
    ).distinct().order_by(RegionalQuote.date.desc()))
    form.fields["product"].choices = [("", "All specifications")] + sorted(products.items(), key=lambda item: item[1])
    form.fields["report_date"].choices = [("", "All dates in reporting window")] + [
        (day.isoformat(), day.strftime("%d %b %Y")) for day in report_dates
    ]
    form.fields["region"].choices = sorted(((r, region_label(r)) for r in regions), key=lambda choice: choice[1])
    form.fields["source"].choices = [("", "All sources")] + [(s,s) for s in sources]
    valid = not form.is_bound or form.is_valid()
    values = form.cleaned_data if form.is_bound and valid else defaults
    report_date = values.get("report_date")
    as_of = report_date or values["as_of"]
    days = 1 if report_date else values["days"]
    report = build_report(db, as_of, days, values.get("region", []), values.get("source", ""), values["crop"], values.get("product", "")) if valid else {"groups":[],"records":[],"runs":[]}
    if valid and request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="ani-regional-price-report.csv"'
        writer = csv.writer(response)
        writer.writerow(["Source","Region","Market","Product","Specification","Unit","Low PHP","High PHP","Source-reported date","Source URL","Archive SHA256"])
        def safe(value):
            value = str(value)
            return "'"+value if value.lstrip().startswith(("=","+","-","@")) else value
        for row in sorted(report["records"], key=lambda r:(r.product,r.date,r.low,r.market)):
            writer.writerow([safe(v) for v in [row.source,row.region,row.market,row.product,row.specification,row.unit,row.low,row.high,row.date,row.source_url,row.sha256]])
        return response
    ranked_groups = sorted(
        (g for g in report["groups"] if g["market_count"] > 1),
        key=lambda g: (g["date"], g["market_count"]), reverse=True,
    )
    records = sorted(report["records"], key=lambda r: (-r.date.toordinal(), r.product, r.region, r.market, r.source))
    market_count = len({(r.region, r.market) for r in records})
    wider_window_query = ""
    if valid and not report_date and values["crop"] and not ranked_groups and days < REPORT_WINDOWS[-1][0]:
        wider = query.copy()
        wider["crop"] = values["crop"]
        wider["as_of"] = values["as_of"].isoformat()
        wider["days"] = DEFAULT_WINDOW if days < DEFAULT_WINDOW else REPORT_WINDOWS[-1][0]
        wider_window_query = wider.urlencode()
    comparison_charts = [
        {
            "title": f'{group["product"]} · {group["specification"]} · {group["date"].isoformat()}',
            "unit": group["unit"],
            "markets": [
                {"name": row.market.title(), "region": row.region, "source": row.source,
                 "low": float(row.low), "high": float(row.high)}
                for row in group["rows"]
            ],
        }
        for group in ranked_groups
    ]
    benchmarks = []
    selected_regions = values.get("region", [])
    if valid and not values.get("product") and (not selected_regions or any(r.startswith("NCR (") for r in selected_regions)):
        weekly = select(CropPrice).join(CropPrice.crop).where(
            ~CropPrice.regional_listing.has(), CropPrice.date.between(report["cutoff"], as_of)
        ).order_by(CropPrice.date.desc())
        if values.get("source"):
            weekly = weekly.where(CropPrice.source == values["source"])
        seen = set()
        for price in db.scalars(weekly):
            label = family(price.crop.english_name or price.crop.name)
            if label == values["crop"] and price.crop_id not in seen and price.evidence:
                seen.add(price.crop_id)
                benchmarks.append(price)
    return render(request, "core/regional_report.html", {"form":form,"report":report,"benchmarks":benchmarks,
        "comparison_charts": comparison_charts, "ranked_groups": ranked_groups,
        "records": records, "market_count": market_count, "wider_window_query": wider_window_query,
        "window_label": dict(REPORT_WINDOWS)[days], "report_date": report_date,
        "as_of":as_of,"selected_crop":values["crop"]}, status=200 if valid else 400)
