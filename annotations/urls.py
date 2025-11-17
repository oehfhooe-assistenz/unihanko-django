from django.urls import path
from . import views

app_name = 'annotations'

urlpatterns = [
    path('add/', views.add_annotation, name='add'),
    path('delete/<int:annotation_id>/', views.delete_annotation, name='delete'),
]