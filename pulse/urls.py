from django.urls import path

from .views import (
    AdminSummaryView,
    AlertDetailView,
    AlertListCreateView,
    LoginView,
    RegisterView,
    get_flight_price,
)


urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("alerts/", AlertListCreateView.as_view(), name="alerts"),
    path("alerts/<int:pk>/", AlertDetailView.as_view(), name="alert-detail"),
    path("flights/price/", get_flight_price, name="flight-price"),
    path("admin/summary/", AdminSummaryView.as_view(), name="admin-summary"),
]
