from datetime import timedelta

from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import ChoreForm, LogEntryForm
from .models import Chore, LogEntry


def _get_dashboard_data():
    today = timezone.localdate()
    start_date = today - timedelta(days=29)
    date_list = [start_date + timedelta(days=i) for i in range(30)]
    dates = [d.strftime("%Y-%m-%d") for d in date_list]

    totals = (
        LogEntry.objects.filter(date__gte=start_date, date__lte=today)
        .values("date", "owner")
        .annotate(total=Sum("effort_rating"))
    )
    lookup = {(item["date"].strftime("%Y-%m-%d"), item["owner"]): item["total"] for item in totals}

    series = {
        "you": [lookup.get((d, "you"), 0) for d in dates],
        "partner": [lookup.get((d, "partner"), 0) for d in dates],
    }

    total_you = sum(series["you"])
    total_partner = sum(series["partner"])
    if total_you == 0 and total_partner == 0:
        fairness = "No data yet"
    else:
        fairness_value = abs(total_you - total_partner) / max(total_you, total_partner, 1) * 100
        fairness = f"{fairness_value:.2f}"

    return {
        "dates": dates,
        "series": series,
        "fairness": fairness,
        "total_you": total_you,
        "total_partner": total_partner,
    }


@require_http_methods(["GET", "POST"])
def dashboard(request):
    context = _get_dashboard_data()
    return render(request, "core/dashboard.html", context)


@require_http_methods(["GET", "POST"])
def log_list(request):
    if request.method == "POST":
        form = LogEntryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("log_list")
    else:
        form = LogEntryForm()

    entries = LogEntry.objects.select_related("chore").order_by("-date", "-id")[:20]
    chores = Chore.objects.all()
    context = {
        "form": form,
        "entries": entries,
        "chores": chores,
        "has_chores": chores.exists(),
    }
    return render(request, "core/log_list.html", context)


@require_http_methods(["GET", "POST"])
def chore_list(request):
    if request.method == "POST":
        chore_id = request.POST.get("chore_id")
        if chore_id:
            chore = get_object_or_404(Chore, pk=chore_id)
            form = ChoreForm(request.POST, instance=chore)
            if form.is_valid():
                form.save()
                return redirect("chore_list")
        else:
            form = ChoreForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect("chore_list")
    else:
        form = ChoreForm()

    chores = Chore.objects.order_by("-created_at", "-id")
    context = {
        "form": form,
        "chores": chores,
    }
    return render(request, "core/chore_list.html", context)
