from django.core.management.base import BaseCommand
from django.db.models import Count

from stations.models import FuelStation


class Command(BaseCommand):
    help = (
        "List city/state pairs that could not be geocoded (or only matched at "
        "state-centroid precision), grouped, for manual correction. Mirrors the "
        "manual fix-coordinates workflow used for failed geocodes in production: "
        "these stations are excluded from route matching until corrected."
    )

    def handle(self, *args, **options):
        qs = (
            FuelStation.objects.exclude(geocode_status=FuelStation.GEOCODE_OK)
            .values("city", "state", "geocode_status")
            .annotate(station_count=Count("id"))
            .order_by("state", "city")
        )
        if not qs:
            self.stdout.write(self.style.SUCCESS("No geocoding failures."))
            return

        for row in qs:
            self.stdout.write(
                f"{row['city']}, {row['state']} [{row['geocode_status']}] "
                f"- {row['station_count']} station(s)"
            )
        self.stdout.write(self.style.WARNING(f"\n{len(qs)} city/state pairs need correction."))
