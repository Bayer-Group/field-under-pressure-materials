from django.views.generic import TemplateView


class IndexView(TemplateView):
    """The single dashboard page. The chat and the map are mounted into it by the TypeScript bundle."""

    template_name = "frontend/index.html"
