"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# File: config/urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib import admin
from django.urls import path, include
from core import views as core_views
from django.views.generic import TemplateView
from django.conf import settings

admin.site.index_title = "Dashboard"

urlpatterns = [
    path('tinymce/', include('tinymce.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('captcha/', include('captcha.urls')),
    path('', core_views.home, name='home'),
    path('portal/', include('portal.urls')),
    path('admin/', admin.site.urls),
    path('markdownx/', include('markdownx.urls')),
    path('annotations/', include('annotations.urls')),
    path('assembly/', include('assembly.urls')),
]

if settings.DEBUG:
    urlpatterns += [
        path('test/404/', TemplateView.as_view(template_name='404.html')),
        path('test/500/', TemplateView.as_view(template_name='500.html')),
        path('test/403/', TemplateView.as_view(template_name='403.html')),
        path('test/maintenance/', TemplateView.as_view(template_name='maintenance.html')),
        path('rosetta/', include('rosetta.urls')),
    ]
