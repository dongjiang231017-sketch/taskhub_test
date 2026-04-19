from django.urls import path
from . import views

app_name = 'frontend'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('announcements/', views.announcement_list_view, name='announcements'),
    path('announcements/<int:pk>/', views.announcement_detail_view, name='announcement_detail'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('profile/', views.profile_view, name='profile'),
    path('wallet/', views.wallet_view, name='wallet'),
    path('transactions/', views.transaction_view, name='transactions'),
    path('staking/', views.staking_list_view, name='staking_list'),
    path('staking/stake/', views.stake_create_view, name='stake_create'),
    path('staking/records/', views.stake_record_view, name='stake_records'),
    path('staking/release/', views.release_record_view, name='release_records'),
]