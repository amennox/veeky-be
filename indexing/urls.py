from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DjangoQTaskViewSet

router = DefaultRouter()
router.register(r"django-q/tasks", DjangoQTaskViewSet, basename="djangoq-task")

urlpatterns = [
    path("", include(router.urls)),
]
