# portal/payments_urls.py
"""
URL configuration for payment plan portal.
"""
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # FY list (landing)
    path('', views.fy_list, name='fy_list'),

    # Access with PAC
    path('<str:fy_code>/access/', views.payment_access, name='payment_access'),

    # Plan list for authenticated person
    path('<str:fy_code>/plans/', views.plan_list, name='plan_list'),

    # Complete banking details
    path('plan/<str:plan_code>/complete/', views.complete_plan, name='complete_plan'),

    # Status and upload
    path('plan/<str:plan_code>/status/', views.plan_status, name='plan_status'),

    # PDF download (public access via plan code)
    path('plan/<str:plan_code>/pdf/', views.plan_pdf, name='plan_pdf'),
]
