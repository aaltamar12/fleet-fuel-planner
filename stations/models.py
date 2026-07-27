from django.db import models


class FuelStation(models.Model):
    """A truck-stop fuel price entry from the OPIS dataset.

    Coordinates are approximated at the city centroid (see
    scripts/geocode_cities.py) since the source addresses are highway-exit
    descriptions, not geocodable street addresses. `geocode_status` other
    than GEOCODE_OK means we could not confidently place the station even at
    state-centroid precision, so it is excluded from route matching (see
    `geocoding_failed`) but kept for audit/manual correction.
    """

    GEOCODE_OK = "ok"
    GEOCODE_FALLBACK_STATE = "failed_fallback_state"
    GEOCODE_FAILED = "failed"
    GEOCODE_STATUS_CHOICES = [
        (GEOCODE_OK, "City-level match"),
        (GEOCODE_FALLBACK_STATE, "State-centroid fallback"),
        (GEOCODE_FAILED, "No match"),
    ]

    opis_truckstop_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=32, blank=True)
    retail_price = models.DecimalField(max_digits=6, decimal_places=4)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geocode_status = models.CharField(
        max_length=32, choices=GEOCODE_STATUS_CHOICES, default=GEOCODE_OK, db_index=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) - ${self.retail_price}"

    @property
    def geocoding_failed(self):
        return self.geocode_status != self.GEOCODE_OK
