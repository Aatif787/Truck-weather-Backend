from django.urls import path
from .views import RouteCalculationView, HealthCheckView

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health-check'),
    path('routes/', RouteCalculationView.as_view(), name='calculate-routes'),
]

