from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import NotificationLog, PriceAlert, UserProfile
from .tasks import (
    check_prices,
    is_price_at_or_below_threshold,
    send_notification,
)


class PriceThresholdTest(TestCase):
    def test_price_below_threshold_triggers_alert(self):
        self.assertTrue(is_price_at_or_below_threshold(4200, 4500))

    def test_price_above_threshold_does_not_trigger(self):
        self.assertFalse(is_price_at_or_below_threshold(5000, 4500))

    def test_price_equal_to_threshold_triggers_alert(self):
        self.assertTrue(is_price_at_or_below_threshold(4500, 4500))


class PulseAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="test-user",
            password="securepass123",
            email="test@example.com",
        )
        self.other_user = User.objects.create_user(
            username="other-user",
            password="securepass123",
            email="other@example.com",
        )
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
        )
        self.other_alert = PriceAlert.objects.create(
            user=self.other_user,
            origin="BLR",
            destination="HYD",
            threshold_price=Decimal("2000.00"),
        )
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_new_users_receive_default_user_profile(self):
        self.assertEqual(self.user.profile.role, UserProfile.Role.USER)

    def test_registration_creates_profile_and_returns_access_token(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "new-user",
                "password": "securepass123",
                "email": "new@example.com",
                "role": "admin",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], UserProfile.Role.USER)
        self.assertTrue(response.data["access"])
        self.assertEqual(User.objects.get(username="new-user").profile.role, "user")

    def test_duplicate_registration_returns_400(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": self.user.username,
                "password": "securepass123",
                "email": "duplicate@example.com",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_401_for_invalid_credentials(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_alert_list_only_contains_current_users_alerts(self):
        response = self.client.get("/api/alerts/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [self.alert.id])

    def test_alert_list_requires_authentication(self):
        response = APIClient().get("/api/alerts/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_alert_uses_authenticated_user(self):
        response = self.client.post(
            "/api/alerts/",
            {
                "origin": "BOM",
                "destination": "GOA",
                "threshold_price": "2500.00",
                "user": self.other_user.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_alert = PriceAlert.objects.get(id=response.data["id"])
        self.assertEqual(created_alert.user, self.user)

    def test_delete_deactivates_owned_alert(self):
        response = self.client.delete(f"/api/alerts/{self.alert.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "inactive"})
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.INACTIVE)

    def test_delete_hides_another_users_alert(self):
        response = self.client.delete(f"/api/alerts/{self.other_alert.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.other_alert.refresh_from_db()
        self.assertEqual(self.other_alert.status, PriceAlert.Status.ACTIVE)

    def test_mock_price_feed_is_public_and_unknown_route_is_404(self):
        public_client = APIClient()
        response = public_client.get(
            "/api/flights/price/",
            {"route": "DEL-BOM"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.json()["price"], 3000)
        self.assertLessEqual(response.json()["price"], 7000)

        response = public_client.get(
            "/api/flights/price/",
            {"route": "XYZ-ABC"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_summary_requires_admin_profile_role(self):
        response = self.client.get("/api/admin/summary/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.user.profile.role = UserProfile.Role.ADMIN
        self.user.profile.save(update_fields=["role"])
        response = self.client.get("/api/admin/summary/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_alerts"], 2)
        self.assertEqual(response.data["active_alerts"], 2)
        self.assertEqual(response.data["triggered_alerts"], 0)
        self.assertEqual(response.data["top_routes"][0]["route"], "BLR-HYD")


class NotificationTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="notify-user",
            password="securepass123",
        )
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin="DEL",
            destination="BOM",
            threshold_price=Decimal("4500.00"),
            status=PriceAlert.Status.ACTIVE,
        )

    def test_notification_task_creates_log_and_triggers_alert(self):
        send_notification.run(self.alert.id, 4200)

        log = NotificationLog.objects.get(alert=self.alert)
        self.assertEqual(log.triggered_price, Decimal("4200.00"))
        self.assertIn("DEL-BOM", log.message)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)

    def test_repeated_notification_task_does_not_create_duplicate_log(self):
        send_notification.run(self.alert.id, 4200)
        send_notification.run(self.alert.id, 4100)

        self.assertEqual(NotificationLog.objects.filter(alert=self.alert).count(), 1)

    @patch("pulse.tasks.send_notification.delay")
    @patch("pulse.tasks.requests.get")
    def test_check_prices_fetches_route_and_queues_notification(
        self,
        mock_get,
        mock_notify,
    ):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"route": "DEL-BOM", "price": 4200}
        mock_get.return_value = response

        check_prices.run()

        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["params"], {"route": "DEL-BOM"})
        mock_notify.assert_called_once_with(self.alert.id, 4200)
