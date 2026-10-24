from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from shops.views import home_view
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('shops.urls')),
    path('', home_view)
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)