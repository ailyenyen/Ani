import csv

from django import forms
from django.http import HttpResponse
from django.shortcuts import render
from sqlalchemy import select

from .models import RegionalQuote, CropPrice, Crop, Market
from .regional_reports import build_report, family
from .services import today


class ReportForm(forms.Form):
    crop = forms.ChoiceField(label="Crop")
    product = forms.ChoiceField(label="Product / specification", required=False)
    region = forms.MultipleChoiceField(label="Regions", required=False, widget=forms.CheckboxSelectMultiple)
    source = forms.ChoiceField(label="Source", required=False)
    as_of = forms.DateField(label="As of", widget=forms.DateInput(attrs={"type": "date"}))
    days = forms.TypedChoiceField(label="Look back", choices=[(1,"Same day only"),(3,"3 days"),(7,"7 days"),(14,"14 days")], coerce=int)


def regional_report(request):
    db = request.db
    regions = list(db.scalars(select(RegionalQuote.region).distinct().order_by(RegionalQuote.region)))
    sources = sorted(set(db.scalars(select(RegionalQuote.source).distinct())) | set(db.scalars(select(CropPrice.source).distinct())))
    identities = list(db.execute(select(RegionalQuote.product_key, RegionalQuote.product, RegionalQuote.specification).distinct()))
    crops = sorted({family(p) for _, p, _ in identities})
    defaults = {"crop": "Tomato / Kamatis" if "Tomato / Kamatis" in crops else (crops[0] if crops else ""), "as_of": today(), "days": 7}
    query = request.GET.copy()
    linked_crop = db.scalar(select(Crop).where(Crop.slug == query.get("crop", "")))
    if linked_crop:
        key = linked_crop.slug.removeprefix("market-")
        label = next((p for k,p,_ in identities if k == key), linked_crop.english_name or linked_crop.name)
        selected = family(label)
        if selected not in crops and "rice" in label.lower():
            selected = "Rice"
        query["crop"] = selected if selected in crops else defaults["crop"]
        if any(k == key for k,_,_ in identities):
            query["product"] = key
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
    form.fields["crop"].widget.attrs["onchange"] = "this.form.elements.product.value='';"
    chosen_crop = query.get("crop", defaults["crop"])
    form.fields["product"].choices = [("", "All specifications (ranked separately)")] + sorted([(k, p+" · "+s) for k,p,s in identities if family(p) == chosen_crop], key=lambda x:x[1])
    form.fields["region"].choices = [(r,r) for r in regions]
    form.fields["source"].choices = [("", "All sources")] + [(s,s) for s in sources]
    valid = not form.is_bound or form.is_valid()
    values = form.cleaned_data if form.is_bound and valid else defaults
    report = build_report(db, values["as_of"], values["days"], values.get("region", []), values.get("source", ""), values["crop"], values.get("product", "")) if valid else {"groups":[],"records":[],"runs":[]}
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
    report["groups"].sort(key=lambda g: (g["date"], len(g["rows"])), reverse=True)
    benchmarks = []
    selected_regions = values.get("region", [])
    if valid and not values.get("product") and (not selected_regions or any(r.startswith("NCR (") for r in selected_regions)):
        weekly = select(CropPrice).join(CropPrice.crop).where(
            ~CropPrice.regional_listing.has(), CropPrice.date.between(report["cutoff"], values["as_of"])
        ).order_by(CropPrice.date.desc())
        if values.get("source"):
            weekly = weekly.where(CropPrice.source == values["source"])
        seen = set()
        for price in db.scalars(weekly):
            label = family(price.crop.english_name or price.crop.name)
            if price.crop.slug in ("bigas", "kadiwa-program-rice"):
                label = "Rice"
            if label == values["crop"] and price.crop_id not in seen and price.evidence:
                seen.add(price.crop_id)
                benchmarks.append(price)
    return render(request, "core/regional_report.html", {"form":form,"report":report,"benchmarks":benchmarks,
        "as_of":values["as_of"],"selected_crop":values["crop"]}, status=200 if valid else 400)
