from django.contrib import admin

from .models import Chore, LogEntry


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = ("name", "default_owner", "created_at")


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("chore", "owner", "effort_rating", "date")
