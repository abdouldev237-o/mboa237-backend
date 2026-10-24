# shops/views_subscription.py
import hmac
import hashlib
import json
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Shop, Subscription, PaymentLog, ShopPlan,
    BillingCycle, SubscriptionStatus,
)
from .serializers_subscription import (
    SubscriptionSerializer,
    PaymentInitSerializer,
    SubscriptionStatusSerializer,
)
from .notchpay_service import (
    NotchPayError,
    initialize_payment,
    retrieve_payment,
)
from django.conf import settings

SUBSCRIPTION_PRICES = settings.SUBSCRIPTION_PRICES
TEST_MODE_AMOUNT = settings.TEST_MODE_AMOUNT
FRONTEND_URL = settings.FRONTEND_URL

logger = logging.getLogger(__name__)


# ================================================================
# HELPERS
# ================================================================
def _compute_expiry(cycle: str) -> "datetime":
    now = timezone.now()
    if cycle == BillingCycle.YEARLY:
        return now + timedelta(days=365)
    return now + timedelta(days=30)


def _verify_notchpay_signature(payload: bytes, signature: str) -> bool:
    """HMAC SHA-256 comme indiqué dans la doc NotchPay."""
    if not settings.NOTCHPAY_WEBHOOK_HASH or not signature:
        return False
    expected = hmac.new(
        settings.NOTCHPAY_WEBHOOK_HASH.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ================================================================
# 1. STATUT DE L'ABONNEMENT (utilisé par la page frontend)
# ================================================================
class MySubscriptionStatusView(APIView):
    """
    GET /api/me/subscription/status/
    Retourne l'état actuel + les prix + éventuellement le dernier abonnement.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop = getattr(request.user, "shop", None)
        if not shop:
            return Response({"detail": "Aucune boutique."}, status=status.HTTP_404_NOT_FOUND)

        last_sub = shop.subscriptions.order_by("-created_at").first()

        data = {
            "is_active": shop.is_subscription_active,
            "days_left": shop.days_left,
            "subscription_expires_at": shop.subscription_expires_at,
            "plan": shop.plan,
            "plan_label": shop.get_plan_display(),
            "is_test_mode": shop.is_test_mode,
            "is_promo_shop": shop.is_promo_shop,
            "prices": {
                "monthly": TEST_MODE_AMOUNT if shop.is_test_mode else SUBSCRIPTION_PRICES["monthly"],
                "yearly": TEST_MODE_AMOUNT if shop.is_test_mode else SUBSCRIPTION_PRICES["yearly"],
            },
            "currency": "XAF",
            "last_subscription": SubscriptionSerializer(last_sub).data if last_sub else None,
        }
        return Response(data)


# ================================================================
# 2. INITIALISER UN PAIEMENT
# ================================================================
class InitializeSubscriptionView(APIView):
    """
    POST /api/me/subscription/initialize/
    Body : { "billing_cycle": "monthly" | "yearly" }
    Retourne : { "authorization_url": "...", "reference": "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shop = getattr(request.user, "shop", None)
        if not shop:
            return Response({"detail": "Aucune boutique."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PaymentInitSerializer(
            data=request.data,
            context={"shop": shop},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Référence unique lisible
        reference = f"SUB-{shop.username}-{uuid.uuid4().hex[:12].upper()}"

        # Création de l'abonnement en attente
        subscription = Subscription.objects.create(
            shop=shop,
            plan=data["plan"],
            billing_cycle=data["billing_cycle"],
            amount=data["amount"],
            currency="XAF",
            reference=reference,
            status=SubscriptionStatus.PENDING,
            is_test_mode=data["is_test_mode"],
            started_at=timezone.now(),
            expires_at=_compute_expiry(data["billing_cycle"]),
        )

        # Callback URL → frontend SPA
        # callback_url = f"{FRONTEND_URL}/payment/callback?reference={reference}"
        callback_url = f"{FRONTEND_URL}/payment/callback"

        try:
            result = initialize_payment(
                amount=data["amount"],
                reference=reference,
                description=f"Abonnement {subscription.get_billing_cycle_display()} — {shop.shop_name}",
                customer_email=shop.email or request.user.email or "",
                customer_name=shop.shop_name,
                callback_url=callback_url,
                metadata={
                    "shop_username": shop.username,
                    "billing_cycle": data["billing_cycle"],
                    "is_test_mode": data["is_test_mode"],
                },
            )
        except NotchPayError as exc:
            subscription.mark_failed(str(exc))
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Mise à jour de l'abonnement avec les infos NotchPay
        subscription.payment_url = result["authorization_url"]
        subscription.transaction_id = result.get("notchpay_reference") or result.get("transaction_id")
        subscription.provider_payload = result.get("raw") or {}
        subscription.save(update_fields=["payment_url", "transaction_id", "provider_payload"])
        


        return Response(
            {
                "authorization_url": result["authorization_url"],
                "reference": reference,
                "amount": data["amount"],
                "is_test_mode": data["is_test_mode"],
            },
            status=status.HTTP_201_CREATED,
        )


# ================================================================
# 3. CALLBACK FRONTEND (retour utilisateur)
# ================================================================

class NotchPayCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        sub_ref = (
            request.query_params.get("trxref")
            or request.query_params.get("sub_ref")
            or ""
        ).strip()

        notchpay_ref = (
            request.query_params.get("reference")
            or request.query_params.get("notchpay_trxref")
            or ""
        ).strip()

        # If trxref contains a SUB-xxx (some flows), use it as our ref
        if sub_ref.startswith("SUB-") is False and notchpay_ref.startswith("SUB-"):
            sub_ref, notchpay_ref = notchpay_ref, sub_ref

        # If trxref IS actually a trx.xxx (test mode), treat it as notchpay_ref
        if sub_ref.startswith("trx"):
            notchpay_ref = notchpay_ref or sub_ref
            sub_ref = ""

        sub = None

        # ── Fallback 1: lookup by our reference (SUB-xxx)
        if sub_ref:
            sub = Subscription.objects.select_related("shop").filter(
                reference=sub_ref
            ).first()

        # ── Fallback 2: lookup by NotchPay ref (trx.xxx) stored as transaction_id
        if not sub and notchpay_ref:
            sub = Subscription.objects.select_related("shop").filter(
                transaction_id=notchpay_ref
            ).first()

        # ── Fallback 3: lookup via NotchPay API (recovers merchant reference from metadata)
        if not sub and notchpay_ref:
            try:
                state = retrieve_payment(notchpay_ref)
                recovered = state.get("merchant_reference")
                if recovered:
                    sub = Subscription.objects.select_related("shop").filter(
                        reference=recovered
                    ).first()
                # If we got a valid sub and payment complete → activate now
                if sub and state.get("is_complete"):
                    sub.mark_active(transaction_id=notchpay_ref)
                    return Response(_subscription_response(sub))
            except NotchPayError:
                pass

        if not sub:
            return Response(
                {
                    "detail": (
                        "Impossible de retrouver ton abonnement. "
                        "Ton paiement sera activé automatiquement via le webhook "
                        "dès confirmation par NotchPay."
                    ),
                    "trxref": sub_ref,
                    "reference": notchpay_ref,
                    "status": "pending_webhook",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        if sub.is_active:
            return Response(_subscription_response(sub))

        # ── Verify with NotchPay
        candidates = [r for r in [notchpay_ref, sub.transaction_id] if r]
        state = None
        for ref in candidates:
            try:
                state = retrieve_payment(ref)
                if state["status"] != "not_found":
                    break
            except NotchPayError:
                continue

        if not state or state["status"] == "not_found":
            return Response(
                {
                    "detail": "Paiement non encore visible chez NotchPay.",
                    "status": "pending_webhook",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        if state["is_complete"]:
            sub.mark_active(transaction_id=state.get("transaction_id") or notchpay_ref)
            return Response(_subscription_response(sub))

        if state["status"] in ("failed", "canceled"):
            sub.mark_failed(state["status"])
            return Response(_subscription_response(sub), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": f"Statut « {state['status']} ».", "status": "pending_webhook"},
            status=status.HTTP_202_ACCEPTED,
        )
class VerifySubscriptionPaymentView(APIView):
    """POST /api/me/subscription/verify/  body: {reference}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ref = (request.data.get("reference") or "").strip()
        if not ref:
            return Response({"detail": "reference manquante"}, status=400)

        sub = Subscription.objects.select_related("shop").filter(
            reference=ref, shop__owner=request.user
        ).first()

        if not sub:
            return Response({"detail": "Abonnement introuvable."}, status=404)

        if sub.is_active:
            return Response(_subscription_response(sub))

        for candidate in [sub.transaction_id, ref]:
            if not candidate:
                continue
            try:
                state = retrieve_payment(candidate)
                if state["is_complete"]:
                    sub.mark_active(transaction_id=state.get("transaction_id") or candidate)
                    return Response(_subscription_response(sub))
            except NotchPayError:
                continue

        return Response({"status": "pending"}, status=202)
    
               
# ================================================================
# 4. WEBHOOK NOTCHPAY (source de vérité)
# ================================================================
@csrf_exempt
def notchpay_webhook(request):
    """
    POST /api/webhooks/notchpay/
    Reçoit les événements NotchPay, vérifie la signature HMAC,
    et met à jour l'abonnement correspondant.
    """
    if request.method != "POST":
        return Response({"detail": "Method not allowed"}, status=405)

    payload_bytes = request.body
    signature = request.headers.get("X-Notchpay-Signature", "") or request.headers.get("x-notch-signature", "")
    signature_valid = _verify_notchpay_signature(payload_bytes, signature)

    try:
        event = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        return Response({"detail": "Invalid JSON"}, status=400)

    event_type = event.get("type", "")
    event_data = event.get("data", {}) or {}
    reference = (
        event_data.get("reference")
        or event_data.get("merchant_reference")
        or event_data.get("payment_reference")
        or ""
    )

    log = PaymentLog.objects.create(
        event_type=event_type,
        reference=reference,
        payload=event,
        signature_valid=signature_valid,
    )

    if not signature_valid:
        log.error = "Invalid signature"
        log.save(update_fields=["error"])
        logger.warning("NotchPay webhook signature invalide pour %s", reference)
        return Response({"detail": "Invalid signature"}, status=403)

    # Idempotence : si déjà traité, on sort
    if log.processed:
        return Response({"status": "already_processed"})

    try:
        if event_type in ("payment.complete", "payment.successful"):
            _handle_payment_complete(reference, event_data)
        elif event_type in ("payment.failed", "payment.canceled"):
            _handle_payment_failed(reference, event_type)

        log.processed = True
        log.save(update_fields=["processed"])
    except Exception as exc:  # noqa: BLE001
        log.error = str(exc)
        log.save(update_fields=["error"])
        logger.exception("NotchPay webhook processing failed")
        return Response({"detail": "Processing error"}, status=500)

    return Response({"status": "ok"})


def _find_subscription(reference: str):
    """
    Cherche un Subscription par :
    1. reference (SUB-xxx)
    2. transaction_id (trx.xxx)
    3. provider_payload['reference'] (fallback JSON)
    """
    if not reference:
        return None

    # Cas 1 : référence interne
    sub = Subscription.objects.filter(reference=reference).first()
    if sub:
        return sub

    # Cas 2 : transaction_id NotchPay
    sub = Subscription.objects.filter(transaction_id=reference).first()
    if sub:
        return sub

    # Cas 3 : stockée dans provider_payload
    sub = Subscription.objects.filter(
        provider_payload__reference=reference
    ).first()
    return sub


def _handle_payment_complete(reference: str, data: dict):
    sub = _find_subscription(reference)
    if not sub:
        logger.warning("Webhook: aucun abonnement pour ref=%s", reference)
        return
    if sub.is_active:
        return  # idempotent
    sub.mark_active(transaction_id=data.get("transaction_id") or data.get("id"))


def _handle_payment_failed(reference: str, event_type: str):
    sub = _find_subscription(reference)
    if not sub:
        return
    if sub.status == SubscriptionStatus.PENDING:
        sub.mark_failed(event_type)


def _subscription_response(sub: Subscription) -> dict:
    return {
        "reference": sub.reference,
        "status": sub.status,
        "is_active": sub.is_active,
        "amount": sub.amount,
        "expires_at": sub.expires_at,
        "days_left": sub.shop.days_left,
    }