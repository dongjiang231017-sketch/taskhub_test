"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from taskhub.doc_html_view import openapi_discovery_json, taskhub_api_docs_html

# 配置后台标题
admin.site.site_header = getattr(settings, 'ADMIN_SITE_HEADER', 'Django 管理')
admin.site.site_title = getattr(settings, 'ADMIN_SITE_TITLE', 'Django 站点管理员')
admin.site.index_title = getattr(settings, 'ADMIN_INDEX_TITLE', '网站管理')

urlpatterns = [
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path("docs/", RedirectView.as_view(url="/docs/taskhub-api/", permanent=False)),
    path("openapi.json", openapi_discovery_json, name="openapi-discovery-json"),
    path("docs/taskhub-api/", taskhub_api_docs_html, name="taskhub-api-docs-html"),
    path('api/v1/', include('taskhub.api_urls')),
    path('api/v1/guides/', include('announcements.api_urls')),
    path('admin/', admin.site.urls),
    path('dashboard/', include('dashboard.urls')),
    path('announcements/', include('announcements.urls')),
    path('staking/', include('staking.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
