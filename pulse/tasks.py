import logging
from decimal import Decimal, InvalidOperation

import requests
from celery import shared_task
from django.conf import settings
from django.db import transaction

from .models import NotificationLog, PriceAlert


logger = logging.getLogger(__name__)


def is_price_at_or_below_threshold(current_price, threshold_price):
    try:
        return Decimal(str(current_price)) <= Decimal(str(threshold_price))
    except (InvalidOperation, TypeError, ValueError):
        return False


@shared_task
def check_prices():
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)
    routes = active_alerts.values_list("origin", "destination").distinct()

    for origin, destination in routes:
        route = f"{origin}-{destination}"
        try:
            response = requests.get(
                settings.FLIGHT_PRICE_FEED_URL,
                params={"route": route},
                timeout=10,
            )
            response.raise_for_status()
            current_price = response.json().get("price")
        except (requests.RequestException, ValueError) as error:
            logger.warning("Unable to check flight price for %s: %s", route, error)
            continue

        if current_price is None:
            logger.warning("Price feed returned no price for route %s", route)
            continue

        route_alerts = active_alerts.filter(
            origin=origin,
            destination=destination,
        )
        for alert in route_alerts:
            if is_price_at_or_below_threshold(
                current_price,
                alert.threshold_price,
            ):
                send_notification.delay(alert.id, current_price)


@shared_task
def send_notification(alert_id, triggered_price):
    with transaction.atomic():
        alert = PriceAlert.objects.select_for_update().get(id=alert_id)
        if alert.status != PriceAlert.Status.ACTIVE:
            return

        message = (
            f"Price alert triggered! {alert.origin}-{alert.destination} "
            f"is now ₹{triggered_price} - below your threshold of "
            f"₹{alert.threshold_price}"
        )
        NotificationLog.objects.create(
            alert=alert,
            triggered_price=triggered_price,
            message=message,
        )
        alert.status = PriceAlert.Status.TRIGGERED
        alert.save(update_fields=["status"])
