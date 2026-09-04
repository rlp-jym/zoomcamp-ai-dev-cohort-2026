from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Chore(models.Model):
    OWNER_CHOICES = [
        ("you", "You"),
        ("partner", "Partner"),
    ]

    name = models.CharField(max_length=100)
    default_owner = models.CharField(max_length=20, choices=OWNER_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.default_owner})"


class LogEntry(models.Model):
    OWNER_CHOICES = [
        ("you", "You"),
        ("partner", "Partner"),
    ]

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE)
    owner = models.CharField(max_length=20, choices=OWNER_CHOICES)
    effort_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    date = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.chore.name} by {self.owner} ({self.effort_rating}) on {self.date}"
