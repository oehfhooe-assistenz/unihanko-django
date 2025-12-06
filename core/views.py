# File: core/views.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.shortcuts import render
from django.contrib.flatpages.models import FlatPage

def home(request):
    ctx = {
        "flat_about":   FlatPage.objects.filter(url="/pages/about/").first(),
        "flat_privacy": FlatPage.objects.filter(url="/pages/privacy/").first(),
        "flat_contact": FlatPage.objects.filter(url="/pages/contact/").first(),
    }
    return render(request, "core/home.html", ctx)
