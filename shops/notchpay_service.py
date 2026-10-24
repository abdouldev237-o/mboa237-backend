# shops/notchpay_service.py
"""
Service NotchPay — encapsule les appels API.
Doc : https://developer.notchpay.co/sdks/python
"""
import logging
from decimal import Decimal
import httpx


from django.conf import settings

try:
    from notchpay import NotchPay
except ImportError:
    NotchPay = None  # permet d'éviter un crash si le SDK n'est pas installé

logger = logging.getLogger(__name__)


class NotchPayError(Exception):
    """Erreur métier NotchPay (message user-friendly)."""
    pass


def _get_client() -> "NotchPay":
    if NotchPay is None:
        raise NotchPayError(
            "Le SDK NotchPay n'est pas installé. Lance `pip install notchpay`."
        )
    if not settings.NOTCHPAY_PUBLIC_KEY:
        raise NotchPayError("NOTCHPAY_PUBLIC_KEY manquant dans .env")

    client = NotchPay(settings.NOTCHPAY_PUBLIC_KEY)
    if settings.NOTCHPAY_GRANT_KEY:
        client.set_grant_key(settings.NOTCHPAY_GRANT_KEY)
    return client


def initialize_payment(
    *,
    amount: int,
    reference: str,
    description: str,
    customer_email: str,
    customer_name: str,
    callback_url: str,
    metadata: dict | None = None,
) -> dict:
    """
    Crée un paiement NotchPay et retourne le dict complet :
    { authorization_url, reference, transaction_id, raw }
    """
    if amount < 100:
        raise NotchPayError("Le montant minimum NotchPay est de 100 XAF.")

    client = _get_client()

    try:
        payment = client.payments.create(
            {
                "amount": amount,
                "currency": "XAF",
                "customer": {
                    "email": customer_email or "client@mboa237.com",
                    "name": customer_name or "Client Mboa237",
                },
                "reference": reference,
                "callback": callback_url,
                "description": description,
                "metadata": metadata or {},
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("NotchPay init failed for %s", reference)
        raise NotchPayError(f"Échec de l'initialisation du paiement : {exc}") from exc

    return {
        "authorization_url": payment.authorization_url,
        "reference": getattr(payment, "reference", reference),
        "transaction_id": getattr(getattr(payment, "transaction", None), "id", None),
        "raw": _safe_dict(payment),
    }



def retrieve_payment(reference: str) -> dict:
    """
    Récupère un paiement NotchPay.
    Retourne toujours un dict — ne lève jamais d'exception pour un 404.
    """
    client = _get_client()
    try:
        payment = client.payments.retrieve(reference)
    except Exception as exc:  # noqa: BLE001
        # 404 = référence inconnue côté NotchPay (ex: SUB-xxx envoyé par erreur)
        msg = str(exc)
        if "404" in msg or "Not Found" in msg:
            logger.warning("NotchPay: reference %s introuvable (404)", reference)
            return {
                "status": "not_found",
                "is_complete": False,
                "amount": None,
                "currency": None,
                "transaction_id": None,
                "raw": {"error": "not_found", "reference": reference},
            }

        logger.exception("NotchPay retrieve failed for %s", reference)
        raise NotchPayError(f"Impossible de vérifier le paiement : {exc}") from exc

    status = getattr(getattr(payment, "transaction", None), "status", None)
    return {
        "status": status,
        "is_complete": status == "complete",
        "amount": getattr(payment, "amount", None),
        "currency": getattr(payment, "currency", None),
        "transaction_id": getattr(getattr(payment, "transaction", None), "id", None),
        "raw": _safe_dict(payment),
    }
    
def _safe_dict(obj) -> dict:
    """Convertit un objet SDK en dict JSON-safe (best effort)."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _safe_value(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return {k: _safe_value(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return {"value": str(obj)}


def _safe_value(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _safe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe_value(x) for x in v]
    return str(v)