class RoutePlannerError(Exception):
    """Base class for errors that should be surfaced to the API client as 4xx/5xx.

    Subclasses set `status_code`; the view catches this single base class and
    reads it off, so adding a new domain error never requires touching the view.
    """

    status_code = 500


class GeocodingError(RoutePlannerError):
    status_code = 422


class RoutingError(RoutePlannerError):
    status_code = 502


class InfeasibleRouteError(RoutePlannerError):
    """Raised when the 500-mile range can't be satisfied with available stations."""

    status_code = 422
