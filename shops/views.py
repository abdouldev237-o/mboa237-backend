# shops/views.py
"""
Vues DRF — Auth + Boutique publique + Dashboard propriétaire + Tracking.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, render
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import Shop, Category, Product, ShopPlan, ShopStatus
from .pagination import DefaultPagination
from .permissions import IsShopOwner, HasShop
from .serializers import (
    RegisterSerializer, LoginSerializer, ShopSerializer,
    CategorySerializer, ProductSerializer, WhatsappClickSerializer,
)
from .signals import sync_view_count
from django.core.cache import cache
from django.utils import timezone

User = get_user_model()


# =================================================================
# ============  Initiation   ======================================
# =================================================================
def home_view(request):
    return render(request, 'home.html')


# =================================================================
# ============  Helpers pour les vues publiques  ==================
# =================================================================
def session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


# =================================================================
# ============  1. AUTHENTIFICATION  ==============================
# =================================================================
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(serializer.to_representation(result), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.to_representation(serializer.validated_data))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("refresh")
        if not token:
            return Response({"detail": "Refresh token requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            return Response({"detail": "Token invalide ou déjà expiré."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Déconnecté."}, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        shop = getattr(user, "shop", None)
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email or None,
            "date_joined": user.date_joined,
            "last_login": user.last_login,
            "shop": (
                {
                    "username": shop.username,
                    "shop_name": shop.shop_name,
                    "url": f"/p/{shop.username}/",
                    "days_left": shop.days_left,
                    "is_active": shop.is_subscription_active,
                } if shop else None
            ),
        })

    def patch(self, request):
        user = request.user
        email = request.data.get("email", None)
        if email is not None:
            user.email = email.strip()
            user.save(update_fields=["email"])
        return self.get(request)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        from rest_framework.exceptions import ValidationError

        old = request.data.get("old_password", "")
        new = request.data.get("new_password", "")

        if not request.user.check_password(old):
            raise ValidationError({"old_password": "Mot de passe actuel incorrect."})

        validate_password(new, request.user)
        request.user.set_password(new)
        request.user.save(update_fields=["password"])
        return Response({"detail": "Mot de passe mis à jour."})


# =================================================================
# ============  2. BOUTIQUE PUBLIQUE  =============================
# =================================================================

class PublicShopView(generics.RetrieveAPIView):
    """
    GET /api/shops/{username}/
    Fiche publique d'une boutique. 
    Gère la protection d'abonnement (affiche l'écran "Expired" si nécessaire).
    """
    permission_classes = [AllowAny]
    serializer_class = ShopSerializer
    lookup_field = "username"

    def retrieve(self, request, *args, **kwargs):
        username = kwargs.get("username")
        
        # 1. Récupérer la boutique sans filtre de plan/expiration pour capter l'erreur
        shop = get_object_or_404(Shop, username=username)

        # 2. Si la boutique est bannie
        if shop.status == ShopStatus.BANNED:
            return Response({
                'detail': 'Boutique bannie',
                'reason': 'banned',
                'message': "Cette boutique a été retirée de la plateforme."
            }, status=status.HTTP_403_FORBIDDEN)
            
        # 3. Si la boutique est suspendue
        if shop.status == ShopStatus.SUSPENDED:
            return Response({
                'detail': 'Boutique suspendue',
                'reason': 'suspended',
                'message': "Cette boutique est temporairement suspendue."
            }, status=status.HTTP_403_FORBIDDEN)

        # 4. Si l'abonnement est expiré (le frontend affichera l'écran d'expiration)
        if not shop.is_subscription_active:
            return Response({
                'detail': 'Boutique en pause',
                'reason': 'subscription_expired',
                'days_left': 0,
                'shop_name': shop.shop_name,
                'whatsapp_number': shop.whatsapp_number,
                'message': f"{shop.shop_name} a suspendu son abonnement. Contactez-le directement sur WhatsApp."
            }, status=status.HTTP_403_FORBIDDEN)

        # 5. Enregistrement de la vue (anti-spam via cache de 20 secondes)
        cache_key = f'shop_view_by_{session_key(request)}_{shop.pk}'
        if not cache.get(cache_key):
            cache.set(cache_key, 1, timeout=20)
            sync_view_count(shop)

        # 6. Retourner les données
        serializer = self.get_serializer(shop)
        return Response(serializer.data)


class PublicShopListView(generics.ListAPIView):
    """
    GET /api/shops/
    Annuaire public des boutiques actives ET dont l'abonnement est valide.
    """
    permission_classes = [AllowAny]
    serializer_class = ShopSerializer
    pagination_class = DefaultPagination

    def get_queryset(self):
        qs = Shop.objects.filter(
            status=ShopStatus.ACTIVE,
            subscription_expires_at__gt=timezone.now()
        )
        city = self.request.query_params.get("city")
        search = self.request.query_params.get("search")
        if city:
            qs = qs.filter(city__iexact=city)
        if search:
            qs = qs.filter(shop_name__icontains=search)
        return qs


class PublicCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        username = self.kwargs["username"]
        return Category.objects.filter(
            shop__username=username,
            shop__status=ShopStatus.ACTIVE,
            shop__subscription_expires_at__gt=timezone.now(), # Protégé
        ).select_related("shop")


class PublicProductListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductSerializer
    pagination_class = DefaultPagination

    def get_queryset(self):
        username = self.kwargs["username"]
        qs = Product.objects.filter(
            shop__username=username,
            shop__status=ShopStatus.ACTIVE,
            shop__subscription_expires_at__gt=timezone.now(), # Protégé
            is_active=True,
        ).select_related("shop", "category")

        category = self.request.query_params.get("category")
        search = self.request.query_params.get("search")
        min_p = self.request.query_params.get("min_price")
        max_p = self.request.query_params.get("max_price")

        if category:
            qs = qs.filter(category__slug=category)
        if search:
            qs = qs.filter(name__icontains=search)
        if min_p:
            qs = qs.filter(price__gte=min_p)
        if max_p:
            qs = qs.filter(price__lte=max_p)

        ordering = self.request.query_params.get("ordering")
        allowed = {"price", "-price", "-created_at", "position", "name"}
        if ordering in allowed:
            qs = qs.order_by(ordering)

        return qs


class PublicProductDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductSerializer

    def get_object(self):
        username = self.kwargs["username"]
        product_id = self.kwargs["pk"]
        product = get_object_or_404(
            Product.objects.select_related("shop", "category"),
            pk=product_id,
            shop__username=username,
            shop__status=ShopStatus.ACTIVE,
            shop__subscription_expires_at__gt=timezone.now(), # Protégé
            is_active=True,
        )
        Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)
        product.refresh_from_db(fields=["views_count"])
        return product


# =================================================================
# ============  3. DASHBOARD PROPRIÉTAIRE  ========================
# =================================================================

class MyShopView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, HasShop]
    serializer_class = ShopSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user.shop

    def patch(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().patch(request, *args, **kwargs)


class MyCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasShop]
    serializer_class = CategorySerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Category.objects.filter(shop=self.request.user.shop)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["shop"] = self.request.user.shop
        return ctx


class MyProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasShop]
    serializer_class = ProductSerializer
    pagination_class = DefaultPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Product.objects.filter(shop=self.request.user.shop).select_related("category")

        category = self.request.query_params.get("category")
        search = self.request.query_params.get("search")
        is_active = self.request.query_params.get("is_active")

        if category:
            qs = qs.filter(category__slug=category)
        if search:
            qs = qs.filter(name__icontains=search)
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))

        ordering = self.request.query_params.get("ordering")
        allowed = {"price", "-price", "-created_at", "position", "name"}
        if ordering in allowed:
            qs = qs.order_by(ordering)

        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["shop"] = self.request.user.shop
        return ctx


# =================================================================
# ============  4. TRACKING  ======================================
# =================================================================

class TrackWhatsappClickView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, username):
        shop = get_object_or_404(
            Shop, 
            username=username, 
            status=ShopStatus.ACTIVE,
            subscription_expires_at__gt=timezone.now()
        )

        serializer = WhatsappClickSerializer(data=request.data, context={"shop": shop})
        serializer.is_valid(raise_exception=True)

        Shop.objects.filter(pk=shop.pk).update(whatsapp_clicks=F("whatsapp_clicks") + 1)

        return Response(
            {"detail": "Clic enregistré.", "whatsapp_link": f"https://wa.me/{shop.whatsapp_number}"},
            status=status.HTTP_200_OK,
        )