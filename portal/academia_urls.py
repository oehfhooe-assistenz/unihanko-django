# portal/academia_urls.py
from django.urls import path
from . import views

# Remove this line: app_name = 'academia'

urlpatterns = [
    path('', views.semester_list, name='semester_list'),
    path('semester/<int:semester_id>/access/', views.access_login, name='access_login'),
    path('semester/<int:semester_id>/file/', views.file_request, name='file_request'),
    path('status/<str:reference_code>/', views.status, name='status'),
    path('pdf/<str:reference_code>/', views.request_pdf, name='request_pdf'),
]