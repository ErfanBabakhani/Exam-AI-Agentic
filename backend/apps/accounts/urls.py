from __future__ import annotations

from django.urls import re_path

from apps.accounts.views import LoginView, MeView, RegisterView


urlpatterns = [
    re_path(r"^register/?$", RegisterView.as_view()),
    re_path(r"^login/?$", LoginView.as_view()),
    re_path(r"^me/?$", MeView.as_view()),
]
