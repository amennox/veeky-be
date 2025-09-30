from django.urls import path
from .views import EmbeddingAPIView, TrainEmbeddingAPIView

urlpatterns = [
    path('embed/', EmbeddingAPIView.as_view(), name='embed'),
    path('train/', TrainEmbeddingAPIView.as_view(), name='train-embedding'),
]