# shops/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views_subscription import (
    MySubscriptionStatusView,
    InitializeSubscriptionView,
    NotchPayCallbackView,
    notchpay_webhook,
    VerifySubscriptionPaymentView
)
from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    MeView,
    ChangePasswordView,
    PublicShopView,
    PublicShopListView,
    PublicCategoryListView,
    PublicProductListView,
    PublicProductDetailView,
    MyShopView,
    MyCategoryViewSet,
    MyProductViewSet,
    TrackWhatsappClickView,
)

# Dans urlpatterns :

router = DefaultRouter()
router.register("me/categories", MyCategoryViewSet, basename="my-category")
router.register("me/products",   MyProductViewSet,   basename="my-product")


urlpatterns = [
    path("me/subscription/verify/", VerifySubscriptionPaymentView.as_view(), name="my-sub-verify"),
    
    # ================= AUTH =================
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),

    # ================= PUBLIC =================
    path("shops/", PublicShopListView.as_view(), name="shop-list"),
    path("shops/<slug:username>/", PublicShopView.as_view(), name="shop-detail"),
    path("shops/<slug:username>/categories/", PublicCategoryListView.as_view(), name="shop-categories"),
    path("shops/<slug:username>/products/", PublicProductListView.as_view(), name="shop-products"),
    path("shops/<slug:username>/products/<uuid:pk>/", PublicProductDetailView.as_view(), name="shop-product-detail"),
    path("shops/<slug:username>/track-whatsapp/", TrackWhatsappClickView.as_view(), name="shop-track-wa"),

    # ================= OWNER =================
    path("me/shop/", MyShopView.as_view(), name="my-shop"),

    # ================= SUBSCRIPTION =================
    path("me/subscription/status/", MySubscriptionStatusView.as_view(), name="my-sub-status"),
    path("me/subscription/initialize/", InitializeSubscriptionView.as_view(), name="my-sub-init"),
    path("me/subscription/callback/", NotchPayCallbackView.as_view(), name="my-sub-callback"),

    # ================= WEBHOOK (public, signature vérifiée) =================
    path("webhooks/notchpay/", notchpay_webhook, name="notchpay-webhook"),

    # ================= ROUTERS =================
    path("", include(router.urls)),
]