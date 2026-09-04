from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ChoreForm, LogEntryForm
from .models import Chore, LogEntry


class ChoreModelTests(TestCase):
    def test_str(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        self.assertEqual(str(chore), "Dishes (you)")

    def test_cascade_delete_chore_deletes_log_entries(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        entry = LogEntry.objects.create(
            chore=chore, owner="you", effort_rating=5, date=timezone.localdate()
        )
        entry_id = entry.id
        chore.delete()
        self.assertFalse(LogEntry.objects.filter(id=entry_id).exists())

    def test_effort_rating_validators_reject_out_of_range(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        for bad in (0, 11):
            entry = LogEntry(
                chore=chore, owner="you", effort_rating=bad, date=timezone.localdate()
            )
            with self.assertRaises(ValidationError):
                entry.full_clean()

    def test_date_defaults_to_today(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        entry = LogEntry.objects.create(chore=chore, owner="you", effort_rating=5)
        entry.refresh_from_db()
        value = entry.date
        if hasattr(value, "date"):
            value = value.date()
        self.assertEqual(value, timezone.localdate())

    def test_log_entry_str(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        today = timezone.localdate()
        entry = LogEntry.objects.create(
            chore=chore, owner="partner", effort_rating=7, date=today
        )
        self.assertIn("Dishes", str(entry))
        self.assertIn("partner", str(entry))


class LogEntryFormTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes", default_owner="you")

    def test_valid_rating_passes(self):
        form = LogEntryForm(
            data={"chore": str(self.chore.id), "owner": "you", "effort_rating": 5}
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_blank_rating_fails(self):
        form = LogEntryForm(
            data={"chore": str(self.chore.id), "owner": "you", "effort_rating": ""}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("effort_rating", form.errors)

    def test_rating_below_minimum_fails(self):
        form = LogEntryForm(
            data={"chore": str(self.chore.id), "owner": "you", "effort_rating": 0}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("effort_rating", form.errors)

    def test_rating_above_maximum_fails(self):
        form = LogEntryForm(
            data={"chore": str(self.chore.id), "owner": "you", "effort_rating": 11}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("effort_rating", form.errors)


class ChoreFormTests(TestCase):
    def test_valid_passes(self):
        form = ChoreForm(data={"name": "Vacuum", "default_owner": "partner"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_name_fails(self):
        form = ChoreForm(data={"name": "", "default_owner": "you"})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_bad_owner_fails(self):
        form = ChoreForm(data={"name": "Vacuum", "default_owner": "nobody"})
        self.assertFalse(form.is_valid())
        self.assertIn("default_owner", form.errors)


class ChoreListViewTests(TestCase):
    def test_get_renders_template_and_lists_chores(self):
        Chore.objects.create(name="Dishes", default_owner="you")
        response = self.client.get(reverse("chore_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/chore_list.html")
        self.assertContains(response, "Dishes")

    def test_post_add_creates_chore_and_redirects(self):
        response = self.client.post(
            reverse("chore_list"), {"name": "Vacuum", "default_owner": "partner"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("chore_list"))
        self.assertTrue(
            Chore.objects.filter(name="Vacuum", default_owner="partner").exists()
        )

    def test_post_edit_updates_default_owner_and_redirects(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        response = self.client.post(
            reverse("chore_list"),
            {"chore_id": str(chore.id), "name": "Dishes", "default_owner": "partner"},
        )
        self.assertEqual(response.status_code, 302)
        chore.refresh_from_db()
        self.assertEqual(chore.default_owner, "partner")

    def test_put_returns_405(self):
        response = self.client.put(reverse("chore_list"), {})
        self.assertEqual(response.status_code, 405)


class LogListViewTests(TestCase):
    def test_get_empty_shows_add_chore_message(self):
        response = self.client.get(reverse("log_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/log_list.html")
        self.assertContains(response, "Add a chore first via /chores/")

    def test_post_valid_creates_entry_and_redirects(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        response = self.client.post(
            reverse("log_list"),
            {"chore": str(chore.id), "owner": "you", "effort_rating": 8},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("log_list"))
        self.assertTrue(LogEntry.objects.filter(effort_rating=8).exists())
        follow = self.client.get(reverse("log_list"))
        self.assertContains(follow, "Dishes")

    def test_post_invalid_rating_creates_nothing_and_shows_errors(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        response = self.client.post(
            reverse("log_list"),
            {"chore": str(chore.id), "owner": "you", "effort_rating": 11},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LogEntry.objects.count(), 0)
        self.assertIn("form", response.context)
        self.assertIn("effort_rating", response.context["form"].errors)

    def test_get_lists_max_20_ordered_desc(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        today = timezone.localdate()
        for i in range(25):
            LogEntry.objects.create(
                chore=chore,
                owner="you",
                effort_rating=5,
                date=today - timedelta(days=i),
            )
        response = self.client.get(reverse("log_list"))
        self.assertEqual(response.status_code, 200)
        entries = list(response.context["entries"])
        self.assertEqual(len(entries), 20)
        dates = [e.date for e in entries]
        self.assertEqual(dates, sorted(dates, reverse=True))
        # oldest 5 should be excluded
        self.assertNotIn(today - timedelta(days=24), dates)


class DashboardViewTests(TestCase):
    def test_get_empty_shows_chart_and_no_data(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/dashboard.html")
        self.assertEqual(response.context["fairness"], "No data yet")
        self.assertEqual(len(response.context["dates"]), 30)
        self.assertTrue(all(v == 0 for v in response.context["series"]["you"]))
        self.assertTrue(all(v == 0 for v in response.context["series"]["partner"]))
        self.assertContains(response, "<canvas")
        self.assertContains(response, "chart.js")

    def test_get_with_data_sums_per_day_and_fairness_two_decimals(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        today = timezone.localdate()
        LogEntry.objects.create(chore=chore, owner="you", effort_rating=5, date=today)
        LogEntry.objects.create(
            chore=chore, owner="partner", effort_rating=3, date=today
        )
        LogEntry.objects.create(
            chore=chore, owner="you", effort_rating=2, date=today - timedelta(days=1)
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        series = response.context["series"]
        # totals: you=7, partner=3 -> 57.14
        self.assertEqual(response.context["total_you"], 7)
        self.assertEqual(response.context["total_partner"], 3)
        self.assertEqual(response.context["fairness"], "57.14")
        self.assertContains(response, "57.14% imbalance")
        self.assertEqual(series["you"][-1], 5)
        self.assertEqual(series["partner"][-1], 3)
        self.assertEqual(series["you"][-2], 2)
        self.assertEqual(series["partner"][-2], 0)

    def test_entries_older_than_30_days_excluded(self):
        chore = Chore.objects.create(name="Dishes", default_owner="you")
        today = timezone.localdate()
        LogEntry.objects.create(
            chore=chore, owner="you", effort_rating=9, date=today - timedelta(days=40)
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["fairness"], "No data yet")
        self.assertEqual(response.context["total_you"], 0)

    def test_put_returns_405(self):
        response = self.client.put(reverse("dashboard"))
        self.assertEqual(response.status_code, 405)

    def test_log_view_put_returns_405(self):
        response = self.client.put(reverse("log_list"), {})
        self.assertEqual(response.status_code, 405)
