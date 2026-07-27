from rest_framework import serializers


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(required=False, allow_blank=False)
    end = serializers.CharField(required=False, allow_blank=False)
    start_latitude = serializers.FloatField(required=False)
    start_longitude = serializers.FloatField(required=False)
    end_latitude = serializers.FloatField(required=False)
    end_longitude = serializers.FloatField(required=False)
    strategy = serializers.ChoiceField(
        choices=["cheapest_fuel", "balanced", "fewest_stops"],
        required=False,
        default="balanced",
        help_text=(
            "cheapest_fuel minimizes fuel dollars alone (more, smaller stops); "
            "fewest_stops minimizes stops (slightly costlier fuel); balanced "
            "weighs each stop at its real driver-time cost."
        ),
    )

    def validate(self, data):
        has_start = bool(data.get("start")) or (
            "start_latitude" in data and "start_longitude" in data
        )
        has_end = bool(data.get("end")) or ("end_latitude" in data and "end_longitude" in data)

        if not has_start:
            raise serializers.ValidationError(
                "Provide either 'start' (a place name/address) or both "
                "'start_latitude' and 'start_longitude'."
            )
        if not has_end:
            raise serializers.ValidationError(
                "Provide either 'end' (a place name/address) or both "
                "'end_latitude' and 'end_longitude'."
            )
        return data


class LatLonSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    station_name = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    mile_marker = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    cost_usd = serializers.FloatField()
    distance_from_route_miles = serializers.FloatField()

    def get_station_name(self, obj):
        return obj["station"].name

    def get_city(self, obj):
        return obj["station"].city

    def get_state(self, obj):
        return obj["station"].state

    def get_latitude(self, obj):
        return obj["station"].latitude

    def get_longitude(self, obj):
        return obj["station"].longitude


class RoutePlanResponseSerializer(serializers.Serializer):
    strategy = serializers.CharField()
    start = LatLonSerializer()
    end = LatLonSerializer()
    total_distance_miles = serializers.FloatField()
    total_duration_hours = serializers.FloatField()
    total_gallons_needed = serializers.FloatField()
    total_fuel_cost_usd = serializers.FloatField()
    fuel_stops = FuelStopSerializer(many=True)
    map_url = serializers.URLField()
    route_geometry = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2)
    )
