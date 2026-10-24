# shops/permissions.py
from rest_framework import permissions


class IsShopOwner(permissions.BasePermission):
    """Autorise seulement le propriétaire de la boutique ciblée."""

    message = "Tu n'as pas accès à cette boutique."

    def has_object_permission(self, request, view, obj):
        # obj peut être Shop, Category, Product
        shop = getattr(obj, "shop", obj)
        return shop.owner_id == request.user.id


class HasShop(permissions.BasePermission):
    """Autorise seulement si l'utilisateur possède une boutique."""

    message = "Tu dois avoir une boutique pour cette action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and hasattr(request.user, "shop")
        )