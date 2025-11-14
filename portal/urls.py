# portal/urls.py
"""
Main URL configuration for the public portal.
"""
from django.urls import path, include
from . import views

app_name = 'portal'

urlpatterns = [
    # Portal landing page (menu)
    path('', views.portal_home, name='home'),

    # Academia ECTS filing
    path('academia/', include('portal.academia_urls')),

    # Payment plans
    path('payments/', include('portal.payments_urls')),
]
