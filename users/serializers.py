from rest_framework import serializers
from django.contrib.auth import get_user_model
from videos.models import Category

User = get_user_model()

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "image_prompt", "text_prompt", "embedding_model_path"]

class UserSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    category_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Category.objects.all(), write_only=True, source="categories"
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "categories", "category_ids"]
