from django.contrib import admin
from django.urls import path, include  # 👈 qui aggiunto include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("users.urls")),  # 👈 ora funziona
]