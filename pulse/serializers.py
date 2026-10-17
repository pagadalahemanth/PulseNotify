from django.contrib.auth.models import User
from rest_framework import serializers

from .models import PriceAlert


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField()

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class PriceAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAlert
        fields = [
            "id",
            "origin",
            "destination",
            "threshold_price",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]
