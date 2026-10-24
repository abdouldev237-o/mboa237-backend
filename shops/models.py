# shops/models.py
import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


# ================================================================
# HELPERS (inchangés)
# ================================================================
def product_image_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"products/{instance.shop_id}/{uuid.uuid4().hex[:12]}.{ext}"


def shop_logo_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"shops/{instance.username}/logo-{uuid.uuid4().hex[:8]}.{ext}"


def category_image_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"category/{instance.shop_id}/image-{uuid.uuid4().hex[:8]}.{ext}"


def shop_banner_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"shops/{instance.username}/banner-{uuid.uuid4().hex[:8]}.{ext}"


# ================================================================
# ENUMS
# ================================================================
class ShopPlan(models.TextChoices):
    FREE = "FREE", "Gratuit"
    PRO = "PRO", "Pro"


class ShopStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    SUSPENDED = "SUSPENDED", "Suspendu"
    BANNED = "BANNED", "Banni"


class ProductBadge(models.TextChoices):
    NEW = "NEW", "Nouveau"
    PROMO = "PROMO", "Promo"
    HOT = "HOT", "Populaire"


class BillingCycle(models.TextChoices):
    MONTHLY = "monthly", "Mensuel"
    YEARLY = "yearly", "Annuel"


class SubscriptionStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    ACTIVE = "active", "Actif"
    EXPIRED = "expired", "Expiré"
    FAILED = "failed", "Échoué"
    CANCELLED = "cancelled", "Annulé"


# ================================================================
# SHOP (mis à jour)
# ================================================================
class Shop(models.Model):
    # --- identité (inchangé) ---
    username = models.SlugField(max_length=40, primary_key=True, unique=True)
    shop_name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)

    city = models.CharField(max_length=50, default="Douala")
    country = models.CharField(max_length=2, default="CM")

    whatsapp_number = models.CharField(max_length=20)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    logo = models.ImageField(upload_to=shop_logo_path, null=True, blank=True)
    banner = models.ImageField(upload_to=shop_banner_path, null=True, blank=True)

    plan = models.CharField(max_length=10, choices=ShopPlan.choices, default=ShopPlan.FREE)
    status = models.CharField(max_length=12, choices=ShopStatus.choices, default=ShopStatus.ACTIVE)
    is_verified = models.BooleanField(default=False)

    delivery_info = models.CharField(max_length=200, blank=True)
    free_delivery_from = models.PositiveIntegerField(null=True, blank=True)

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shop",
    )

    # --- compteurs (inchangés) ---
    views_count = models.PositiveIntegerField(default=0, db_default=0)
    whatsapp_clicks = models.PositiveIntegerField(default=0, db_default=0)
    products_count = models.PositiveIntegerField(default=0, db_default=0)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, db_default=0)

    # --- NOUVEAU : abonnement ---
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    is_promo_shop = models.BooleanField(
        default=False,
        help_text="True si la boutique a bénéficié du trial 30 jours",
    )
    is_test_mode = models.BooleanField(
        default=True,
        help_text="Si activé, les paiements utiliseront NotchPay en mode test (100 XAF)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="shop_status_idx"),
            models.Index(fields=["plan"], name="shop_plan_idx"),
            models.Index(fields=["city"], name="shop_city_idx"),
            models.Index(fields=["-created_at"], name="shop_created_idx"),
            models.Index(fields=["subscription_expires_at"], name="shop_sub_exp_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=0) & Q(rating__lte=5),
                name="shop_rating_0_5",
            ),
            models.CheckConstraint(
                condition=Q(free_delivery_from__isnull=True) | Q(free_delivery_from__gte=0),
                name="shop_free_delivery_positive",
            ),
            models.CheckConstraint(
                condition=Q(username__regex=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
                name="shop_username_format",
            ),
        ]

    def __str__(self):
        return self.shop_name

    # --- LOGIQUE ABONNEMENT ---
    @property
    def is_subscription_active(self) -> bool:
        if not self.subscription_expires_at:
            return False
        return self.subscription_expires_at > timezone.now()

    @property
    def days_left(self) -> int:
        if not self.subscription_expires_at:
            return 0
        delta = self.subscription_expires_at - timezone.now()
        return max(0, delta.days)

    @property
    def is_expired(self) -> bool:
        return not self.is_subscription_active

    # --- Aides business ---
    @property
    def is_pro(self) -> bool:
        return self.plan == ShopPlan.PRO

    @property
    def max_products(self) -> int:
        return 25 if self.is_pro else 10

    def can_add_product(self) -> bool:
        return self.products_count < self.max_products

    def whatsapp_url(self, message: str = "") -> str:
        from urllib.parse import quote
        base = f"https://wa.me/{self.whatsapp_number}"
        return f"{base}?text={quote(message)}" if message else base

    def get_absolute_url(self):
        return reverse("shop-detail", kwargs={"username": self.username})

    # --- SAVE : TRIAL 30j POUR LES 5 PREMIÈRES BOUTIQUES ---
        # --- SAVE : TRIAL 30j POUR LES 5 PREMIÈRES, 14j POUR LES SUIVANTES ---
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new and not self.subscription_expires_at:
            # Les 5 premières boutiques reçoivent 30 jours (PRO).
            # Les suivantes reçoivent 14 jours (2 semaines) en FREE.
            existing_count = Shop.objects.count()
            trial_days = 30 if existing_count < 5 else 14

            self.subscription_expires_at = timezone.now() + timedelta(days=trial_days)
            self.plan = ShopPlan.PRO if trial_days == 30 else ShopPlan.FREE
            self.is_promo_shop = (trial_days == 30)
            self.status = ShopStatus.ACTIVE

        super().save(*args, **kwargs)

# ================================================================
# CATEGORY (inchangé)
# ================================================================
class Category(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60)
    emoji = models.ImageField(upload_to=category_image_path, null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"
        indexes = [models.Index(fields=["shop"], name="category_shop_idx")]
        constraints = [
            models.UniqueConstraint(fields=["shop", "slug"], name="unique_category_slug_per_shop"),
        ]

    def __str__(self):
        return self.name

    def save(self, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:60]
        super().save(**kwargs)


# ================================================================
# PRODUCT (inchangé)
# ================================================================
class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)

    price = models.PositiveIntegerField(help_text="Prix en FCFA")
    was_price = models.PositiveIntegerField(null=True, blank=True)

    image = models.ImageField(upload_to=product_image_path, null=True, blank=True)
    second_image = models.ImageField(upload_to=product_image_path, null=True, blank=True)
    third_image = models.ImageField(upload_to=product_image_path, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    stock = models.PositiveIntegerField(null=True, blank=True)
    badge = models.CharField(max_length=8, choices=ProductBadge.choices, blank=True)

    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, db_default=0)
    views_count = models.PositiveIntegerField(default=0, db_default=0)
    position = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "-created_at"]
        indexes = [
            models.Index(fields=["shop", "is_active"], name="product_shop_active_idx"),
            models.Index(fields=["category"], name="product_category_idx"),
            models.Index(fields=["price"], name="product_price_idx"),
            models.Index(fields=["shop", "-created_at"], name="product_shop_recent_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["shop", "slug"], name="unique_product_slug_per_shop"),
            models.CheckConstraint(condition=Q(price__gte=0), name="product_price_positive"),
            models.CheckConstraint(
                condition=Q(was_price__isnull=True) | Q(was_price__gte=0),
                name="product_was_price_positive",
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=0) & Q(rating__lte=5),
                name="product_rating_0_5",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:200]
        super().save(**kwargs)

    @property
    def discount_percent(self) -> int:
        if not self.was_price or self.was_price <= self.price:
            return 0
        return round((self.was_price - self.price) / self.was_price * 100)

    @property
    def in_stock(self) -> bool:
        return self.stock is None or self.stock > 0

    @property
    def images(self) -> list[str]:
        return [img.url for img in (self.image, self.second_image, self.third_image) if img]

    def whatsapp_message(self, shop: Shop, qty: int = 1) -> str:
        lines = [
            f"Bonjour {shop.shop_name} 👋",
            "",
            "Je souhaite commander :",
            f"• {self.name}" + (f" × {qty}" if qty > 1 else ""),
            f"  {self.price * qty:,} FCFA".replace(",", " "),
            "",
            "Merci de me confirmer la disponibilité.",
        ]
        return "\n".join(lines)


# ================================================================
# SUBSCRIPTION (mis à jour : ajout billing_cycle, provider_payload, payment_url)
# ================================================================
class Subscription(models.Model):
    """
    Historique des abonnements. Chaque paiement réussi crée une ligne ici.
    """
    shop = models.ForeignKey(
        Shop, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.CharField(max_length=10, choices=ShopPlan.choices, default=ShopPlan.PRO)
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    amount = models.PositiveIntegerField(help_text="Montant en XAF")
    currency = models.CharField(max_length=3, default="XAF")

    # --- NotchPay ---
    reference = models.CharField(
        max_length=100, unique=True,
        help_text="Référence interne envoyée à NotchPay (unique)",
    )
    transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    payment_url = models.URLField(blank=True, help_text="URL de paiement NotchPay")
    provider_payload = models.JSONField(default=dict, blank=True)

    # --- Statut ---
    status = models.CharField(
        max_length=12, choices=SubscriptionStatus.choices, default=SubscriptionStatus.PENDING
    )
    is_test_mode = models.BooleanField(
        default=True,
        help_text="True si ce paiement a été fait en mode test (100 XAF)",
    )

    # --- Dates ---
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shop", "status"], name="sub_shop_status_idx"),
            models.Index(fields=["reference"], name="sub_reference_idx"),
            models.Index(fields=["transaction_id"], name="sub_tx_idx"),
        ]

    def __str__(self):
        return f"{self.shop.shop_name} — {self.get_billing_cycle_display()} — {self.status}"

    @property
    def is_active(self) -> bool:
        return self.status == SubscriptionStatus.ACTIVE and self.expires_at > timezone.now()

    def mark_active(self, transaction_id: str | None = None):
        """Active l'abonnement + propage sur la boutique."""
        self.status = SubscriptionStatus.ACTIVE
        self.paid_at = timezone.now()
        if transaction_id:
            self.transaction_id = transaction_id
        self.save(update_fields=["status", "paid_at", "transaction_id"])

        # Mise à jour de la boutique
        shop = self.shop
        shop.subscription_expires_at = self.expires_at
        shop.plan = self.plan
        shop.status = ShopStatus.ACTIVE
        shop.save(update_fields=["subscription_expires_at", "plan", "status"])

    def mark_failed(self, reason: str = ""):
        self.status = SubscriptionStatus.FAILED
        if reason:
            self.provider_payload = {**self.provider_payload, "failure_reason": reason}
        self.save(update_fields=["status", "provider_payload"])


# ================================================================
# PAYMENT LOG (nouveau — audit webhook)
# ================================================================
class PaymentLog(models.Model):
    """
    Journal brut de tous les webhooks NotchPay.
    Permet de rejouer un événement en cas de bug.
    """
    event_type = models.CharField(max_length=60)
    reference = models.CharField(max_length=100, blank=True, db_index=True)
    payload = models.JSONField()
    signature_valid = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payment log"
        verbose_name_plural = "Payment logs"

    def __str__(self):
        return f"{self.event_type} — {self.reference or '?'} — {self.created_at:%Y-%m-%d %H:%M}"