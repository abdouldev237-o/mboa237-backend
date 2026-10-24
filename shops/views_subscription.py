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
        subscription.transaction_id = result.get("transaction_id") or None
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
    """
    GET /api/me/subscription/callback/
    Query params from NotchPay:
      - trxref     : our internal reference (SUB-xxx)
      - reference  : NotchPay transaction ID (trx.xxx)
      - status     : complete | canceled | failed
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        # 1. Extract both references
        sub_reference = (
            request.query_params.get("trxref")
            or request.query_params.get("sub_ref")
            or ""
        ).strip()

        notchpay_ref = (
            request.query_params.get("reference")
            or request.query_params.get("notchpay_trxref")
            or ""
        ).strip()

        # If trxref is missing, check if the `reference` param is our SUB-xxx
        if not sub_reference:
            if notchpay_ref.startswith("SUB-"):
                sub_reference = notchpay_ref
                notchpay_ref = ""  # it's not a trx.xxx

        # 2. Find the subscription
        sub = None

        if sub_reference:
            try:
                sub = Subscription.objects.select_related("shop").get(
                    reference=sub_reference
                )
            except Subscription.DoesNotExist:
                pass

        # Fallback: if not found by reference, try by transaction_id (trx.xxx)
        if not sub and notchpay_ref.startswith("trx"):
            try:
                sub = Subscription.objects.select_related("shop").get(
                    transaction_id=notchpay_ref
                )
            except Subscription.DoesNotExist:
                pass

        if not sub:
            return Response(
                {
                    "detail": f"Abonnement introuvable pour la référence "
                              f"trxref={sub_reference!r} / reference={notchpay_ref!r}."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3. Already active → idempotent
        if sub.is_active:
            return Response(_subscription_response(sub))

        # 4. Determine the NotchPay reference to verify
        candidate_refs = []
        if notchpay_ref.startswith("trx"):
            candidate_refs.append(notchpay_ref)
        if sub.transaction_id and sub.transaction_id.startswith("trx"):
            candidate_refs.append(sub.transaction_id)

        # 5. Verify with NotchPay
        state = None
        for ref in candidate_refs:
            try:
                state = retrieve_payment(ref)
                if state["status"] != "not_found":
                    break
            except NotchPayError as exc:
                logger.warning("NotchPay verify failed for %s: %s", ref, exc)
                continue

        if state is None or state["status"] == "not_found":
            return Response(
                {
                    "detail": "Paiement non encore visible chez NotchPay. "
                              "Réessaie dans quelques secondes.",
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
            {
                "detail": f"Paiement en statut « {state['status']} ».",
                "status": "pending_webhook",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class VerifySubscriptionPaymentView(APIView):
    """
    POST /api/me/subscription/verify/
    Body : { "reference": "SUB-xxx" }
    Force la vérification d'un paiement (bouton "Actualiser" du frontend).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ref = request.data.get("reference", "").strip()
        if not ref:
            return Response({"detail": "reference manquante"}, status=400)

        try:
            sub = Subscription.objects.select_related("shop").get(
                reference=ref, shop__owner=request.user
            )
        except Subscription.DoesNotExist:
            return Response({"detail": "Introuvable."}, status=404)

        if sub.is_active:
            return Response(_subscription_response(sub))

        # Essayer toutes les références NotchPay connues
        candidate_refs = []
        if sub.transaction_id:
            candidate_refs.append(sub.transaction_id)
        if sub.provider_payload.get("reference"):
            candidate_refs.append(sub.provider_payload["reference"])

        for r in candidate_refs:
            try:
                state = retrieve_payment(r)
                if state["is_complete"]:
                    sub.mark_active(transaction_id=state.get("transaction_id") or r)
                    return Response(_subscription_response(sub))
            except NotchPayError:
                continue

        return Response(
            {"status": "pending", "detail": "Toujours en attente."},
            status=status.HTTP_202_ACCEPTED,
        )        
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