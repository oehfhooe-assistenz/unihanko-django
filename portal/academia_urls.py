# portal/academia_urls.py
"""
URL configuration for public ECTS filing under /portal/academia/
"""
from django.urls import path
from . import views

urlpatterns = [
    # Landing page - list of open semesters
    path('', views.semester_list, name='semester_list'),

    # Access code entry for a specific semester
    path('semester/<int:semester_id>/access/', views.access_login, name='access_login'),

    # File new request (after semester auth)
    path('semester/<int:semester_id>/file/', views.file_request, name='file_request'),

    # Check status with reference code (no auth needed)
    path('status/<str:reference_code>/', views.status, name='status'),

    # Download PDF (no auth needed)
    path('pdf/<str:reference_code>/', views.request_pdf, name='request_pdf'),
]
