from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("prices/", views.market_prices, name="prices"),
    path("crops/<slug:slug>/", views.crop_detail, name="crop_detail"),
    path("compare/", views.compare, name="compare"),
    path("alerts/", views.alerts, name="alerts"),
    path("alerts/new/", views.alert_new, name="alert_new"),
    path("alerts/<int:alert_id>/toggle/", views.alert_toggle, name="alert_toggle"),
    path("alerts/<int:alert_id>/delete/", views.alert_delete, name="alert_delete"),
    path("my-crops/", views.my_crops, name="my_crops"),
    path("my-crops/add/", views.my_crops_add, name="my_crops_add"),
    path("my-crops/<slug:crop_slug>/remove/", views.my_crops_remove, name="my_crops_remove"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("profile/notifications/", views.notification_settings, name="notification_settings"),
    path("help/", views.help_page, name="help"),
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("api/devices/", views.register_device, name="register_device"),
    path("firebase-messaging-sw.js", views.firebase_service_worker, name="firebase_sw"),
]
