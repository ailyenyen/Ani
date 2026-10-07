from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
]

handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
