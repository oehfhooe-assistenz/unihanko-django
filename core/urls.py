# File: core/urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.urls import path
from . import views
from django.urls import path

urlpatterns = [
    path("", views.home, name="home"),
]