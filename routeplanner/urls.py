from django.urls import path

from .views import RouteMapPreviewView, RoutePlanView

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
    path("route/map/", RouteMapPreviewView.as_view(), name="route-map-preview"),
]
