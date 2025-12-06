"""
URL configuration for payment plan portal.
"""
# File: portal/payments_urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-27

from django.urls import path
from . import views

urlpatterns = [
    # FY list (landing)
    path('', views.fy_list, name='fy_list'),

    # Access with PAC
    path('<str:fy_code>/access/', views.payment_access, name='payment_access'),

    # Plan list for authenticated person
    path('<str:fy_code>/plans/', views.plan_list, name='plan_list'),

    # PDF download (public access via plan code)
    path('plan/<str:plan_code>/pdf/', views.plan_pdf, name='plan_pdf'),
]
