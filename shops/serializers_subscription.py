# shops/serializers_subscription.py
from django.utils import timezone
from rest_framework import serializers

from .models import Subscription, BillingCycle, ShopPlan
from django.conf import settings

SUBSCRIPTION_PRICES = settings.SUBSCRIPTION_PRICES
TEST_MODE_AMOUNT = settings.TEST_MODE_AMOUNT


class SubscriptionSerializer(serializers.ModelSerializer):
    billing_cycle_label = serializers.CharField(source="get_billing_cycle_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id", "plan", "billing_cycle", "billing_cycle_label",
            "amount", "currency", "reference", "transaction_id",
            "status", "status_label", "is_test_mode",
            "started_at", "expires_at", "paid_at", "created_at",
        ]
        read_only_fields = fields


class PaymentInitSerializer(serializers.Serializer):
    """
    Body POST pour initier un paiement.
    { "billing_cycle": "monthly" | "yearly" }
    """
    billing_cycle = serializers.ChoiceField(choices=BillingCycle.choices)

    def validate(self, attrs):
        shop = self.context["shop"]

        if shop.is_subscription_active:
            raise serializers.ValidationError(
                "Ta boutique est déjà active. Reviens quand elle expirera."
            )

        cycle = attrs["billing_cycle"]
        is_test = shop.is_test_mode

        if is_test:
            amount = TEST_MODE_AMOUNT
        else:
            amount = SUBSCRIPTION_PRICES[cycle]

        attrs["amount"] = amount
        attrs["is_test_mode"] = is_test
        attrs["plan"] = ShopPlan.PRO
        return attrs


class SubscriptionStatusSerializer(serializers.Serializer):
    """
    Réponse pour l'endpoint /me/subscription/status/.
    """
    is_active = serializers.BooleanField()
    days_left = serializers.IntegerField()
    subscription_expires_at = serializers.DateTimeField(allow_null=True)
    plan = serializers.CharField()
    plan_label = serializers.CharField()
    is_test_mode = serializers.BooleanField()
    is_promo_shop = serializers.BooleanField()
    prices = serializers.DictField()
    currency = serializers.CharField(default="XAF")
    last_subscription = SubscriptionSerializer(allow_null=True)