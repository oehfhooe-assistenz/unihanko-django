# File: portal/urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-27

from django.urls import path, include
from . import views

app_name = 'portal'

urlpatterns = [
    path('', views.portal_home, name='home'),
    path('academia/', include(('portal.academia_urls', 'academia'), namespace='academia')),
    path('payments/', include(('portal.payments_urls', 'payments'), namespace='payments')),
]