import random

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import NotificationLog, PriceAlert
from .permissions import IsAdminUser
from .serializers import LoginSerializer, PriceAlertSerializer, RegisterSerializer


class RegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
            email=serializer.validated_data["email"],
        )
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "username": user.username,
                "access": str(refresh.access_token),
                "role": user.profile.role,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"error": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "username": user.username,
                "access": str(refresh.access_token),
                "role": user.profile.role,
            },
            status=status.HTTP_200_OK,
        )


class AlertListCreateView(APIView):
    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user)

    def get(self, request):
        serializer = PriceAlertSerializer(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PriceAlertSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        alert = serializer.save(user=request.user)
        return Response(
            PriceAlertSerializer(alert).data,
            status=status.HTTP_201_CREATED,
        )


class AlertDetailView(APIView):
    def delete(self, request, pk):
        alert = get_object_or_404(PriceAlert, id=pk)
        if alert.user_id != request.user.id:
            return Response(
                {"error": "Alert not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        alert.status = PriceAlert.Status.INACTIVE
        alert.save(update_fields=["status"])
        return Response(
            {"status": PriceAlert.Status.INACTIVE},
            status=status.HTTP_200_OK,
        )


MOCK_PRICES = {
    "DEL-BOM": (3000, 7000),
    "BLR-HYD": (1500, 4000),
    "DEL-BLR": (4000, 9000),
    "BOM-GOA": (2000, 5000),
}


def get_flight_price(request):
    route = request.GET.get("route", "")
    price_range = MOCK_PRICES.get(route)
    if price_range is None:
        return JsonResponse({"error": "Route not found"}, status=404)

    return JsonResponse(
        {"route": route, "price": random.randint(*price_range)},
        status=200,
    )


class AdminSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        alert_counts = PriceAlert.objects.aggregate(
            total_alerts=Count("id"),
            active_alerts=Count(
                "id",
                filter=Q(status=PriceAlert.Status.ACTIVE),
            ),
            triggered_alerts=Count(
                "id",
                filter=Q(status=PriceAlert.Status.TRIGGERED),
            ),
        )
        total_notifications = NotificationLog.objects.aggregate(
            total=Count("id")
        )["total"]
        route_counts = (
            PriceAlert.objects.values("origin", "destination")
            .annotate(alert_count=Count("id"))
            .order_by("-alert_count", "origin", "destination")[:5]
        )
        top_routes = [
            {
                "route": f"{item['origin']}-{item['destination']}",
                "alert_count": item["alert_count"],
            }
            for item in route_counts
        ]

        return Response(
            {
                **alert_counts,
                "total_notifications": total_notifications,
                "top_routes": top_routes,
            },
            status=status.HTTP_200_OK,
        )
