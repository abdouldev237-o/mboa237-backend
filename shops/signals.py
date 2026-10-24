# shops/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import F
from .models import Product, Shop

def sync_view_count(shop):
    Shop.objects.filter(pk=shop.pk).update(views_count=F('views_count') + 1)


def _sync_products_count(shop):
    """Recalcule et écrit le compteur sur la Shop concernée."""
    if not shop:
        return
    count = Product.objects.filter(shop=shop).count()
    Shop = shop.__class__
    Shop.objects.filter(pk=shop.pk).update(products_count=count)


@receiver(post_save, sender=Product)
def product_saved(sender, instance, **kwargs):
    _sync_products_count(instance.shop)

def get_request(request):
    if not request.session:
        request.session.create
    return request.session        


@receiver(post_delete, sender=Product)
def product_deleted(sender, instance, **kwargs):
    _sync_products_count(instance.shop)