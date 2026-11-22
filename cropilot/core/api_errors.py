"""The API's exception handler: DRF's own, plus a 503 when the demo date is not set."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.clock import ClockNotSetError

CLOCK_NOT_SET_DETAIL = "The demo date is not set: set it in /admin/ or run the seed."


def exception_handler(exc, context):
    if isinstance(exc, ClockNotSetError):
        return Response({"detail": CLOCK_NOT_SET_DETAIL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return drf_exception_handler(exc, context)
