from django import forms

from .models import Chore, LogEntry


class LogEntryForm(forms.ModelForm):
    class Meta:
        model = LogEntry
        fields = ["chore", "owner", "effort_rating"]
        widgets = {
            "effort_rating": forms.NumberInput(attrs={"min": 1, "max": 10}),
        }

    def clean_effort_rating(self):
        value = self.cleaned_data.get("effort_rating")
        if value in (None, ""):
            raise forms.ValidationError("Effort rating is required.")
        if value < 1 or value > 10:
            raise forms.ValidationError("Effort rating must be between 1 and 10.")
        return value


class ChoreForm(forms.ModelForm):
    class Meta:
        model = Chore
        fields = ["name", "default_owner"]
