# portal/urls.py
"""
Main URL configuration for the public portal.
"""
from django.urls import path, include

app_name = 'portal'

urlpatterns = [
    # Academia ECTS filing
    path('academia/', include('portal.academia_urls')),

    # Future: Add other portal modules here (e.g., payment plans)
    # path('payments/', include('portal.payment_urls')),
]
