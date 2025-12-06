# File: annotations/urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.urls import path
from . import views

app_name = 'annotations'

urlpatterns = [
    path('add/', views.add_annotation, name='add'),
    path('delete/<int:annotation_id>/', views.delete_annotation, name='delete'),
]