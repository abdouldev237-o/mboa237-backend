# shops/serializers.py
import re
from urllib.parse import quote

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Shop, Category, Product

User = get_user_model()

PHONE_RE = re.compile(r"^237[62]\d{8}$")
SHOP_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


# =================================================================
# HELPERS
# =================================================================
def clean_phone(value: str) -> str:
    digits = "".join(c for c in value if c.isdigit())
    if digits.startswith("237"):
        digits = digits[3:]
    if len(digits) != 9 or digits[0] not in ("6", "2"):
        raise serializers.ValidationError("Numéro invalide (ex: 237 6XX XXX XXX).")
    return f"237{digits}"


def clean_shop_slug(value: str) -> str:
    value = slugify(value.strip().lower())[:40]
    if not SHOP_SLUG.match(value):
        raise serializers.ValidationError("3 à 40 caractères : a-z, 0-9, tirets.")
    return value


# =================================================================
# 1. REGISTER
# =================================================================
from .models import ShopPlan, ShopStatus
from django.utils import timezone
from datetime import timedelta

class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=False, allow_blank=True)

    shop_name = serializers.CharField(max_length=100)
    shop_username = serializers.CharField(max_length=40, required=False, allow_blank=True)
    whatsapp_number = serializers.CharField(max_length=20)
    city = serializers.CharField(max_length=50, required=False, default="Douala")
    tagline = serializers.CharField(max_length=160, required=False, allow_blank=True)

    delivery_info = serializers.CharField(max_length=200, required=False, allow_blank=True)
    free_delivery_from = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    logo = serializers.ImageField(required=False, allow_null=True)
    banner = serializers.ImageField(required=False, allow_null=True)

    @transaction.atomic
    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            email=validated_data.get("email", ""),
        )
        shop = Shop.objects.create(
            username=validated_data["shop_username"] or validated_data["username"],
            shop_name=validated_data["shop_name"],
            tagline=validated_data.get("tagline", ""),
            city=validated_data.get("city", "Douala"),
            whatsapp_number=validated_data["whatsapp_number"],
            delivery_info=validated_data.get("delivery_info", ""),
            free_delivery_from=validated_data.get("free_delivery_from"),
            logo=validated_data.get("logo"),
            banner=validated_data.get("banner"),
            owner=user,
        )
        
        trial_days = 30 if Shop.objects.count() < 5 else 14
        shop.subscription_expires_at = timezone.now() + timedelta(days=trial_days)
        shop.plan = ShopPlan.PRO if trial_days == 30 else ShopPlan.FREE
        shop.is_promo_shop = (trial_days == 30)
        shop.status = ShopStatus.ACTIVE
        shop.save()
        return {"user": user, "shop": shop}

    def to_representation(self, instance):
        user, shop = instance["user"], instance["shop"]
        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id, 
                "username": user.username, 
                "email": user.email or None
            },
            "shop": {
                "username": shop.username,
                "shop_name": shop.shop_name,
                "city": shop.city,
                "whatsapp_number": shop.whatsapp_number,
                "logo": shop.logo.url if shop.logo else None,
                "banner": shop.banner.url if shop.banner else None,
                "url": f"/p/{shop.username}/",
                "plan": shop.plan,
                "plan_label": shop.get_plan_display(),
                "max_products": shop.max_products,
                "days_left": shop.days_left,  # 🟢 NOUVEAU
                "is_promo_shop": shop.is_promo_shop,  # 🟢 NOUVEAU
            },
        }


# =================================================================
# 2. LOGIN
# =================================================================
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"].strip(),
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError({"detail": "Identifiants incorrects."})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "Compte désactivé."})

        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": user,
        }

    def to_representation(self, instance):
        user = instance["user"]
        shop = getattr(user, "shop", None)
        return {
            "access": instance["access"],
            "refresh": instance["refresh"],
            "user": {"id": user.id, "username": user.username, "email": user.email or None},
            "shop": (
                {
                    "username": shop.username, 
                    "shop_name": shop.shop_name, 
                    "url": f"/p/{shop.username}/",
                    "days_left": shop.days_left,
                    "plan": shop.plan,
                    "plan_label": shop.get_plan_display(),
                }
                if shop else None
            ),
        }


# =================================================================
# 3. SHOP
# =================================================================
class ShopSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    whatsapp_link = serializers.SerializerMethodField()
    is_pro = serializers.BooleanField(read_only=True)
    max_products = serializers.IntegerField(read_only=True)
    can_add_product = serializers.SerializerMethodField()
    plan_label = serializers.CharField(source="get_plan_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    days_left = serializers.IntegerField(read_only=True) # 🟢 IntegerField
    is_subscription_active = serializers.BooleanField(read_only=True) # 🟢 NOUVEAU

    class Meta:
        model = Shop
        fields = [
            "username", "shop_name", "tagline", "description",
            "city", "country",
            "whatsapp_number", "whatsapp_link",
            "phone_number", "email",
            "logo", "banner",
            "plan", "plan_label", "is_pro",
            "status", "status_label", "is_verified",
            "delivery_info", "free_delivery_from",
            "views_count", "whatsapp_clicks",
            "products_count", "rating",
            "max_products", "can_add_product",
            "owner_username", "url",
            "created_at", "updated_at",
            "days_left", "is_subscription_active", "is_promo_shop",
        ]
        read_only_fields = [
            "username", "plan", "plan_label", "is_pro", "status", "status_label",
            "is_verified", "views_count", "whatsapp_clicks", "products_count",
            "rating", "max_products", "can_add_product", "owner_username",
            "url", "whatsapp_link", "created_at", "updated_at",
            "days_left", "is_subscription_active", "is_promo_shop",
        ]
        extra_kwargs = {
            "logo": {"required": False, "allow_null": True},
            "banner": {"required": False, "allow_null": True},
            "email": {"required": False, "allow_blank": True},
            "phone_number": {"required": False, "allow_blank": True},
            "tagline": {"required": False, "allow_blank": True},
            "description": {"required": False, "allow_blank": True},
            "delivery_info": {"required": False, "allow_blank": True},
            "free_delivery_from": {"required": False, "allow_null": True},
        }

    def get_url(self, obj):
        request = self.context.get("request")
        path = f"/p/{obj.username}/"
        return request.build_absolute_uri(path) if request else path

    def get_whatsapp_link(self, obj):
        return f"https://wa.me/{obj.whatsapp_number}"

    def get_can_add_product(self, obj):
        return obj.can_add_product()

    def validate_whatsapp_number(self, value):
        return clean_phone(value)

    def validate_phone_number(self, value):
        return clean_phone(value) if value else value

    def validate_shop_name(self, value):
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError("Nom de boutique trop court.")
        return v


# =================================================================
# 4. CATEGORY & PRODUCT (inchangés)
# =================================================================
class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.SerializerMethodField()
    emoji_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "emoji", "emoji_url", "position", "products_count", "created_at"]
        read_only_fields = ["id", "slug", "products_count", "emoji_url", "created_at"]
        extra_kwargs = {
            "emoji": {"required": False, "allow_null": True},
            "position": {"required": False},
        }

    def get_products_count(self, obj):
        return obj.products.filter(is_active=True).count()

    def get_emoji_url(self, obj):
        if not obj.emoji:
            return None
        request = self.context.get("request")
        url = obj.emoji.url
        return request.build_absolute_uri(url) if request else url

    def validate_name(self, value):
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError("Nom trop court.")
        return v

    def validate(self, attrs):
        shop = self.context.get("shop")
        name = attrs.get("name", getattr(self.instance, "name", None))
        if shop and name:
            slug = slugify(name)[:60]
            qs = Category.objects.filter(shop=shop, slug=slug)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "Catégorie déjà existante."})
        return attrs

    def create(self, validated_data):
        validated_data["shop"] = self.context["shop"]
        return super().create(validated_data)


class ProductSerializer(serializers.ModelSerializer):
    images = serializers.SerializerMethodField()
    discount_percent = serializers.IntegerField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    badge_label = serializers.CharField(source="get_badge_display", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    category_slug = serializers.CharField(source="category.slug", read_only=True, default=None)
    whatsapp_link = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "description",
            "price", "was_price", "discount_percent",
            "image", "second_image", "third_image", "images",
            "category", "category_name", "category_slug",
            "is_active", "in_stock", "stock",
            "badge", "badge_label",
            "rating", "views_count",
            "position", "whatsapp_link",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "slug", "discount_percent", "in_stock", "badge_label",
            "images", "category_name", "category_slug",
            "rating", "views_count", "whatsapp_link",
            "created_at", "updated_at",
        ]
        extra_kwargs = {
            "image": {"required": False, "allow_null": True},
            "second_image": {"required": False, "allow_null": True},
            "third_image": {"required": False, "allow_null": True},
            "category": {"required": False, "allow_null": True},
            "badge": {"required": False, "allow_blank": True},
            "stock": {"required": False, "allow_null": True},
            "was_price": {"required": False, "allow_null": True},
            "description": {"required": False, "allow_blank": True},
            "position": {"required": False},
        }

    def get_images(self, obj):
        request = self.context.get("request")
        out = []
        for img in (obj.image, obj.second_image, obj.third_image):
            if img:
                url = img.url
                out.append(request.build_absolute_uri(url) if request else url)
        return out

    def get_whatsapp_link(self, obj):
        msg = obj.whatsapp_message(obj.shop)
        return f"https://wa.me/{obj.shop.whatsapp_number}?text={quote(msg)}"

    def validate_name(self, value):
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError("Nom trop court.")
        return v

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Le prix doit être positif.")
        return value

    def validate_was_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Le prix barré doit être positif.")
        return value

    def validate_category(self, value):
        shop = self.context.get("shop")
        if value and shop and value.shop_id != shop.pk:
            raise serializers.ValidationError("Cette catégorie n'est pas dans ta boutique.")
        return value

    def validate(self, attrs):
        shop = self.context.get("shop")
        if shop and self.instance is None and not shop.can_add_product():
            raise serializers.ValidationError(
                f"Limite atteinte : {shop.max_products} produits en {shop.plan}."
            )

        was = attrs.get("was_price", getattr(self.instance, "was_price", None))
        price = attrs.get("price", getattr(self.instance, "price", None))
        if was is not None and price is not None and was <= price:
            raise serializers.ValidationError({"was_price": "Le prix barré doit être supérieur au prix actuel."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data["shop"] = self.context["shop"]
        return super().create(validated_data)


class WhatsappClickSerializer(serializers.Serializer):
    product_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_product_id(self, value):
        if value is None:
            return value
        shop = self.context.get("shop")
        if shop and not Product.objects.filter(pk=value, shop=shop).exists():
            raise serializers.ValidationError("Ce produit n'appartient pas à cette boutique.")
        return value