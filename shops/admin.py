# shops/admin.py
"""
Admin Mboa237 — gestion complète de Shop, Category, Product.

Principes :
  - Lecture dense (list_display compact + badges colorés)
  - Filtres rapides (statut, plan, ville, catégorie)
  - Actions en masse (activer/désactiver, changer de plan, vérifier)
  - Inlines pour éditer Shop + ses catégories/produits sur une seule page
  - Prévisualisation des images directement dans la liste
"""

from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.utils.text import slugify
from .models import (
    Shop,
    Category,
    Product,
    ShopPlan,
    ShopStatus,
    ProductBadge,
    Subscription,
    PaymentLog
)


# =================================================================
# HELPERS
# =================================================================

def _fmt_fcfa(value: int) -> str:
    """Formate un entier en '1 234 F CFA'."""
    return f"{value:,}".replace(",", " ") + " F"


def _img_preview(field, size: int = 40, radius: str = "8px") -> str:
    """Retourne un <img> ou un placeholder si pas d'image."""
    if not field:
        return mark_safe(
            f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'background:#f0f0f0;border-radius:{radius};"></span>'
        )
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;'
        'border-radius:{};border:1px solid #e5e5e5;" />',
        field.url, size, size, radius,
    )


def _pill(text: str, color: str) -> str:
    """Petite pastille colorée."""
    return format_html(
        '<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        'font-size:11px;font-weight:600;background:{};color:#fff;">{}</span>',
        color, text,
    )


PLAN_COLORS = {
    ShopPlan.FREE: "#6b7280",
    ShopPlan.PRO:  "#16a34a",
}

STATUS_COLORS = {
    ShopStatus.ACTIVE:    "#16a34a",
    ShopStatus.SUSPENDED: "#f59e0b",
    ShopStatus.BANNED:    "#ef4444",
}

BADGE_COLORS = {
    ProductBadge.NEW:   "#0ea5e9",
    ProductBadge.PROMO: "#ef4444",
    ProductBadge.HOT:   "#f97316",
}


# =================================================================
# INLINES
# =================================================================

class CategoryInline(admin.TabularInline):
    """Catégories éditables directement sur la page Shop."""
    model = Category
    extra = 0
    fields = ("name", "slug", "position", "emoji_preview", "emoji")
    readonly_fields = ("emoji_preview", "slug")
    show_change_link = True
    classes = ("collapse",)

    @admin.display(description="Aperçu")
    def emoji_preview(self, obj):
        return _img_preview(obj.emoji, size=32, radius="6px")


class ProductInline(admin.TabularInline):
    """Produits éditables directement sur la page Shop (mode compact)."""
    model = Product
    extra = 0
    fields = ("thumb", "name", "price", "is_active", "stock", "badge")
    readonly_fields = ("thumb",)
    show_change_link = True
    classes = ("collapse",)
    per_page = 20

    def has_add_permission(self, request, obj=None):
        # On gère l'ajout depuis la page dédiée Product (plus de contrôle)
        return False

    @admin.display(description="")
    def thumb(self, obj):
        return _img_preview(obj.image, size=40, radius="6px")

class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    fields = (
        "reference", "billing_cycle", "amount", "status",
        "is_test_mode", "started_at", "expires_at", "transaction_id",
    )
    readonly_fields = fields
    can_delete = False
    show_change_link = True
    max_num = 0
    classes = ("collapse",)




# =================================================================
# SHOP
# =================================================================

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    inlines = (CategoryInline, ProductInline, SubscriptionInline)


    
    list_display = (
        "avatar",
        "shop_name",
        "username_link",
        "city",
        "plan_pill",
        "status_pill",
        "verified_icon",
        "products_count",
        "views_count",
        "whatsapp_clicks",
        "rating_display",
        "created_at",
        "is_test_mode",
        "subscription_expires_at",
        "days_left_display",
        "status"
    )
    list_display_links = ("shop_name",)
    list_filter = ("status", "plan", "is_verified", "city", "country","is_test_mode","is_promo_shop")
    search_fields = ("username", "shop_name", "city", "whatsapp_number", "email")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 30
    save_on_top = True

    readonly_fields = (
        "username",
        "views_count",
        "whatsapp_clicks",
        "products_count",
        "rating",
        "created_at",
        "updated_at",
        "logo_preview",
        "banner_preview",
        "storefront_link",
    )


    fieldsets = (
        ("Identité", {
            "fields": ("username", "shop_name", "tagline", "description"),
        }),
        ("Localisation", {
            "fields": ("city", "country"),
        }),
        ("Contact", {
            "fields": ("whatsapp_number", "phone_number", "email"),
        }),
        ("Médias", {
            "fields": ("logo", "logo_preview", "banner", "banner_preview"),
        }),
        ("statut", {
            "fields": ("status", "is_verified"),
        }),
        ("Livraison", {
            "fields": ("delivery_info", "free_delivery_from"),
        }),
        ("Propriétaire", {
            "fields": ("owner",),
        }),
        ("Statistiques (lecture seule)", {
            "fields": (
                "views_count", "whatsapp_clicks",
                "products_count", "rating",
            ),
            "classes": ("collapse",),
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at", "storefront_link"),
            "classes": ("collapse",),
        }),
        ("Abonnement", {
            "fields": (
                "plan",
                "subscription_expires_at",
                "is_promo_shop",
                "is_test_mode",       # ← toggle important
            ),
            "description": (
                "Active <b>is_test_mode</b> pour faire tester les paiements "
                "NotchPay à 100 XAF (sandbox). Désactive-le en production."
            ),
        }),
    )

    actions = (
        "action_activate",
        "action_suspend",
        "action_ban",
        "action_verify",
        "action_unverify",
        "action_upgrade_pro",
        "action_downgrade_free",
    )

    # ---------- Colonnes ----------
    @admin.display(description="")
    def avatar(self, obj):
        return _img_preview(obj.logo, size=40, radius="10px")

    @admin.display(description="URL", ordering="username")
    def username_link(self, obj):
        url = reverse("admin:shops_shop_change", args=[obj.pk])
        return format_html(
            '<a href="{}" style="font-family:monospace;color:#16a34a;">'
            '/p/{}/</a>',
            url, obj.username,
        )
        
        
    @admin.display(description="Jours restants")
    def days_left_display(self, obj):
        return obj.days_left    

    @admin.display(description="Plan", ordering="plan")
    def plan_pill(self, obj):
        return _pill(obj.get_plan_display(), PLAN_COLORS.get(obj.plan, "#6b7280"))

    @admin.display(description="Statut", ordering="status")
    def status_pill(self, obj):
        return _pill(obj.get_status_display(), STATUS_COLORS.get(obj.status, "#6b7280"))

    @admin.display(description="Vérifié", ordering="is_verified", boolean=True)
    def verified_icon(self, obj):
        return obj.is_verified

    @admin.display(description="Note", ordering="rating")
    def rating_display(self, obj):
        if not obj.rating:
            return "—"
        color = "#16a34a" if obj.rating >= 4 else ("#f59e0b" if obj.rating >= 3 else "#ef4444")
        return format_html(
            '<span style="color:{};font-weight:700;">★ {}</span>',
            color, obj.rating,
        )

    # ---------- Aperçus ----------
    @admin.display(description="Aperçu logo")
    def logo_preview(self, obj):
        return _img_preview(obj.logo, size=120, radius="14px")

    @admin.display(description="Aperçu bannière")
    def banner_preview(self, obj):
        if not obj.banner:
            return "—"
        return format_html(
            '<img src="{}" style="width:320px;height:auto;border-radius:12px;'
            'border:1px solid #e5e5e5;" />',
            obj.banner.url,
        )

    @admin.display(description="Lien boutique")
    def storefront_link(self, obj):
        if not obj.pk:
            return "—"
        return format_html(
            '<a href="/p/{}/" target="_blank" '
            'style="color:#16a34a;font-weight:600;">Ouvrir /p/{}/ ↗</a>',
            obj.username, obj.username,
        )

    # ---------- Actions en masse ----------
    @admin.action(description="Activer les boutiques sélectionnées")
    def action_activate(self, request, queryset):
        n = queryset.update(status=ShopStatus.ACTIVE)
        self.message_user(request, f"{n} boutique(s) activée(s).")

    @admin.action(description="Suspendre les boutiques sélectionnées")
    def action_suspend(self, request, queryset):
        n = queryset.update(status=ShopStatus.SUSPENDED)
        self.message_user(request, f"{n} boutique(s) suspendue(s).")

    @admin.action(description="Bannir les boutiques sélectionnées")
    def action_ban(self, request, queryset):
        n = queryset.update(status=ShopStatus.BANNED)
        self.message_user(request, f"{n} boutique(s) bannie(s).")

    @admin.action(description="Marquer comme vérifiées")
    def action_verify(self, request, queryset):
        n = queryset.update(is_verified=True)
        self.message_user(request, f"{n} boutique(s) vérifiée(s).")

    @admin.action(description="Retirer la vérification")
    def action_unverify(self, request, queryset):
        n = queryset.update(is_verified=False)
        self.message_user(request, f"{n} boutique(s) démarquée(s).")

    @admin.action(description="Passer en PRO")
    def action_upgrade_pro(self, request, queryset):
        n = queryset.update(plan=ShopPlan.PRO)
        self.message_user(request, f"{n} boutique(s) passée(s) en PRO.")

    @admin.action(description="Repasser en FREE")
    def action_downgrade_free(self, request, queryset):
        n = queryset.update(plan=ShopPlan.FREE)
        self.message_user(request, f"{n} boutique(s) repassée(s) en FREE.")

    # ---------- Optimisation ----------
    def get_queryset(self, request):
        return super().get_queryset(request).select_related("owner")


# =================================================================
# CATEGORY
# =================================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "emoji_preview",
        "name",
        "shop_link",
        "slug",
        "products_count",
        "position",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = ("shop__status", "shop__plan", "shop__city")
    search_fields = ("name", "slug", "shop__shop_name", "shop__username")
    ordering = ("shop", "position", "name")
    list_per_page = 40
    autocomplete_fields = ("shop",)
    save_on_top = True

    readonly_fields = ("slug", "emoji_preview_large", "created_at", "products_count_display")

    fieldsets = (
        ("Boutique", {"fields": ("shop",)}),
        ("Contenu", {"fields": ("name", "slug", "position")}),
        ("Visuel", {"fields": ("emoji", "emoji_preview_large")}),
        ("Info", {
            "fields": ("products_count_display", "created_at"),
            "classes": ("collapse",),
        }),
    )

    actions = ("action_reset_slug",)

    # ---------- Colonnes ----------
    @admin.display(description="")
    def emoji_preview(self, obj):
        return _img_preview(obj.emoji, size=36, radius="6px")

    @admin.display(description="Boutique", ordering="shop__shop_name")
    def shop_link(self, obj):
        url = reverse("admin:shops_shop_change", args=[obj.shop_id])
        return format_html('<a href="{}" style="color:#16a34a;">{}</a>', url, obj.shop.shop_name)

    @admin.display(description="Produits", ordering="products_count")
    def products_count(self, obj):
        return obj.products.count()

    # ---------- Aperçus ----------
    @admin.display(description="Aperçu")
    def emoji_preview_large(self, obj):
        return _img_preview(obj.emoji, size=120, radius="12px")

    @admin.display(description="Nombre de produits")
    def products_count_display(self, obj):
        return obj.products.count()

    # ---------- Actions ----------
    @admin.action(description="Régénérer le slug depuis le nom")
    def action_reset_slug(self, request, queryset):
        n = 0
        for cat in queryset:
            new_slug = slugify(cat.name)[:60]
            if cat.slug != new_slug:
                cat.slug = new_slug
                cat.save(update_fields=["slug"])
                n += 1
        self.message_user(request, f"{n} slug(s) régénéré(s).")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shop").annotate(
            products_count_annot=Count("products"),
        )


# =================================================================
# PRODUCT
# =================================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "thumb",
        "name_short",
        "shop_link",
        "category_link",
        "price_display",
        "was_price_display",
        "discount_pill",
        "badge_pill",
        "stock_pill",
        "is_active_icon",
        "views_count",
        "created_at",
    )
    list_display_links = ("name_short", "thumb")
    list_filter = (
        "is_active",
        "badge",
        "shop__status",
        "shop__plan",
        "shop__city",
        "category",
        "created_at",
    )
    search_fields = (
        "name", "slug", "description",
        "shop__shop_name", "shop__username",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 40
    autocomplete_fields = ("shop", "category")
    save_on_top = True
    list_select_related = ("shop", "category")

    readonly_fields = (
        "slug",
        "views_count",
        "rating",
        "created_at",
        "updated_at",
        "whatsapp_preview",
        "images_preview",
    )

    fieldsets = (
        ("Boutique", {"fields": ("shop", "category")}),
        ("Contenu", {"fields": ("name", "slug", "description")}),
        ("Prix", {"fields": ("price", "was_price")}),
        ("Images", {
            "fields": (
                "image", "second_image", "third_image",
                "images_preview",
            ),
        }),
        ("État", {"fields": ("is_active", "stock", "badge", "position")}),
        ("Statistiques", {
            "fields": ("views_count", "rating"),
            "classes": ("collapse",),
        }),
        ("WhatsApp", {
            "fields": ("whatsapp_preview",),
            "classes": ("collapse",),
        }),
        ("Métadonnées", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    actions = (
        "action_activate",
        "action_deactivate",
        "action_clear_badge",
        "action_set_new",
        "action_set_promo",
        "action_set_hot",
    )

    # ---------- Colonnes ----------
    @admin.display(description="")
    def thumb(self, obj):
        return _img_preview(obj.image, size=44, radius="8px")

    @admin.display(description="Nom", ordering="name")
    def name_short(self, obj):
        return (obj.name[:45] + "…") if len(obj.name) > 45 else obj.name

    @admin.display(description="Boutique", ordering="shop__shop_name")
    def shop_link(self, obj):
        url = reverse("admin:shops_shop_change", args=[obj.shop_id])
        return format_html('<a href="{}" style="color:#16a34a;">{}</a>', url, obj.shop.shop_name)

    @admin.display(description="Catégorie", ordering="category__name")
    def category_link(self, obj):
        if not obj.category:
            return "—"
        url = reverse("admin:shops_category_change", args=[obj.category.pk])
        return format_html('<a href="{}">{}</a>', url, obj.category.name)

    @admin.display(description="Prix", ordering="price")
    def price_display(self, obj):
        return format_html(
            '<span style="font-weight:700;">{}</span>',
            _fmt_fcfa(obj.price),
        )

    @admin.display(description="Ancien prix", ordering="was_price")
    def was_price_display(self, obj):
        if not obj.was_price:
            return "—"
        return format_html(
            '<span style="text-decoration:line-through;color:#999;">{}</span>',
            _fmt_fcfa(obj.was_price),
        )

    @admin.display(description="Remise")
    def discount_pill(self, obj):
        d = obj.discount_percent
        if not d:
            return "—"
        return _pill(f"-{d}%", "#ef4444")

    @admin.display(description="Badge", ordering="badge")
    def badge_pill(self, obj):
        if not obj.badge:
            return "—"
        return _pill(obj.get_badge_display(), BADGE_COLORS.get(obj.badge, "#6b7280"))

    @admin.display(description="Stock")
    def stock_pill(self, obj):
        if obj.stock is None:
            return _pill("∞ illimité", "#0ea5e9")
        if obj.stock == 0:
            return _pill("Rupture", "#ef4444")
        if obj.stock <= 5:
            return _pill(f"Plus que {obj.stock}", "#f59e0b")
        return _pill(f"{obj.stock} en stock", "#16a34a")

    @admin.display(description="Actif", boolean=True, ordering="is_active")
    def is_active_icon(self, obj):
        return obj.is_active

    # ---------- Aperçus ----------
    @admin.display(description="Aperçu des 3 images")
    def images_preview(self, obj):
        imgs = [obj.image, obj.second_image, obj.third_image]
        html = "".join(
            f'<div style="display:inline-block;margin-right:8px;">'
            f'{_img_preview(img, size=140, radius="12px")}</div>'
            for img in imgs
        )
        return mark_safe(html)

    @admin.display(description="Message WhatsApp généré")
    def whatsapp_preview(self, obj):
        if not obj.pk or not obj.shop_id:
            return "—"
        msg = obj.whatsapp_message(obj.shop)
        return format_html(
            '<pre style="background:#f6f6f7;border:1px solid #e5e5e5;'
            'border-radius:10px;padding:12px;font-size:12.5px;'
            'white-space:pre-wrap;max-width:520px;">{}</pre>',
            msg,
        )

    # ---------- Actions en masse ----------
    @admin.action(description="Activer les produits sélectionnés")
    def action_activate(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} produit(s) activé(s).")

    @admin.action(description="Désactiver les produits sélectionnés")
    def action_deactivate(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} produit(s) désactivé(s).")

    @admin.action(description="Retirer le badge")
    def action_clear_badge(self, request, queryset):
        n = queryset.update(badge="")
        self.message_user(request, f"{n} badge(s) retiré(s).")

    @admin.action(description="Marquer comme Nouveau")
    def action_set_new(self, request, queryset):
        n = queryset.update(badge=ProductBadge.NEW)
        self.message_user(request, f"{n} produit(s) marqué(s) Nouveau.")

    @admin.action(description="Marquer comme Promo")
    def action_set_promo(self, request, queryset):
        n = queryset.update(badge=ProductBadge.PROMO)
        self.message_user(request, f"{n} produit(s) marqué(s) Promo.")

    @admin.action(description="Marquer comme Populaire")
    def action_set_hot(self, request, queryset):
        n = queryset.update(badge=ProductBadge.HOT)
        self.message_user(request, f"{n} produit(s) marqué(s) Populaire.")

    # ---------- Optimisation ----------
    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shop", "category")

    # ---------- Validation côté admin ----------
    def save_model(self, request, obj, form, change):
        # Slug auto si vide
        if not obj.slug:
            obj.slug = slugify(obj.name)[:200]
        super().save_model(request, obj, form, change)




@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "shop", "billing_cycle", "amount",
        "status", "is_test_mode", "started_at", "expires_at",
    )
    list_filter = ("status", "billing_cycle", "is_test_mode")
    search_fields = ("reference", "transaction_id", "shop__shop_name", "shop__username")
    readonly_fields = (
        "reference", "transaction_id", "payment_url",
        "provider_payload", "created_at", "paid_at",
    )


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "reference", "signature_valid", "processed", "created_at")
    list_filter = ("event_type", "signature_valid", "processed")
    search_fields = ("reference",)
    readonly_fields = ("event_type", "reference", "payload", "signature_valid", "processed", "error", "created_at")
    
# =================================================================
# SITE ADMIN — En-tête personnalisé
# =================================================================

admin.site.site_header = "Mboa237 — Administration"
admin.site.site_title = "Mboa237 Admin"
admin.site.index_title = "Gestion des boutiques, catégories et produits"

