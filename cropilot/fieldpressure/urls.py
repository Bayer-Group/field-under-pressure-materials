from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import api_not_found

urlpatterns = [
    path("admin/", admin.site.urls),
    # Platform API (core). Interactive docs: /api/docs/
    path("api/", include("core.urls")),
    # Chat endpoints (assistant app, owner Ola; docs/interfaces.md -> Chat)
    path("api/", include("assistant.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
    # Anything else under /api/ (unknown path, non-numeric id): {"detail"} like every API error, not an HTML page
    re_path(r"^api/", api_not_found),
    # Web app (must stay last: it serves "/")
    path("", include("frontend.urls")),
]
