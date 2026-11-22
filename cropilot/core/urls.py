from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("clock/", views.ClockView.as_view(), name="clock"),
    path("threats/", views.ThreatListView.as_view(), name="threats"),
    path("fields/", views.FieldListView.as_view(), name="fields"),
    path("fields/<int:pk>/", views.FieldDetailView.as_view(), name="field-detail"),
    path("fields/<int:pk>/risks/", views.FieldRiskSeriesView.as_view(), name="field-risks"),
    # <str:date>, not a date converter: a malformed date is a 400 with a message, not a 404
    path("fields/<int:pk>/risks/<str:date>/", views.FieldDayRisksView.as_view(), name="field-day-risks"),
    path("risks/", views.DayRisksView.as_view(), name="risks"),
]
