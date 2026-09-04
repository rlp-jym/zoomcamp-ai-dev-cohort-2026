from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("log/", views.log_list, name="log_list"),
    path("chores/", views.chore_list, name="chore_list"),
]
