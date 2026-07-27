from django.contrib import admin

from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "retail_price", "geocode_status", "geocoding_failed")
    list_filter = ("state", "geocode_status")
    search_fields = ("name", "city", "address")
