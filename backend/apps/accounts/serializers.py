from __future__ import annotations

from django.contrib.auth import authenticate
from rest_framework import serializers

from apps.accounts.models import User
from common.auth import create_access_token


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "created_at")


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate_email(self, value: str) -> str:
        email = value.lower()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("Email already registered")
        return email

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate(self, attrs: dict) -> dict:
        email = attrs["email"].lower()
        password = attrs["password"]
        user = authenticate(username=email, password=password)
        if user is None:
            user = User.objects.filter(email=email).first()
            if user is None or not user.check_password(password):
                raise serializers.ValidationError("Invalid credentials")
        attrs["user"] = user
        return attrs


class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField(default="bearer")
    expires_in_seconds = serializers.IntegerField()

    @staticmethod
    def from_user(user: User) -> dict:
        from django.conf import settings

        return {
            "access_token": create_access_token(str(user.id)),
            "token_type": "bearer",
            "expires_in_seconds": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
