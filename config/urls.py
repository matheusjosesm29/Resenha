from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from core import views

urlpatterns = [
    path('', views.index),
    path('admin/', admin.site.urls),
    path('api/<path:route>', views.api),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
