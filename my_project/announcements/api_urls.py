from django.urls import path

from . import api_views

urlpatterns = [
    path("categories/", api_views.guide_categories_api, name="guides-categories"),
    path("featured/", api_views.guide_featured_api, name="guides-featured"),
    path("<int:pk>/", api_views.guide_detail_api, name="guides-detail"),
    path("", api_views.guide_list_api, name="guides-list"),
]
