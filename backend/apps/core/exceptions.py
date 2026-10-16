"""Uniform API error responses.

Service-layer code raises django.core.exceptions.ValidationError for business-rule
violations; it is converted to HTTP 400 with the same shape DRF uses for serializer
errors so that the frontend can render field-level messages consistently.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("plantops.api")


def _django_validation_payload(exc: DjangoValidationError) -> dict:
    if hasattr(exc, "error_dict"):
        errors = {field: [str(m) for e in errs for m in e.messages] for field, errs in exc.error_dict.items()}
        non_field = errors.pop("__all__", None)
        payload: dict = {"detail": "Validation failed.", "errors": errors}
        if non_field:
            payload["detail"] = " ".join(non_field)
            payload["errors"]["non_field_errors"] = non_field
        return payload
    messages = [str(m) for m in exc.messages]
    return {"detail": " ".join(messages), "errors": {"non_field_errors": messages}}


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        return Response(_django_validation_payload(exc), status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detail": str(exc) or "You do not have permission to perform this action."}, status=403)
    if isinstance(exc, ProtectedError):
        return Response(
            {"detail": "This record is referenced by other records and cannot be deleted. Archive or deactivate it instead."},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, IntegrityError):
        # Constraint violations that slipped past validation: report a conflict, never the SQL.
        logger.warning("Integrity error in %s: %s", context.get("view").__class__.__name__, exc.__class__.__name__)
        return Response(
            {"detail": "The change conflicts with an existing record or a data-integrity rule."},
            status=status.HTTP_409_CONFLICT,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        return response
    if isinstance(data, dict):
        non_field = data.get("non_field_errors")
        detail = " ".join(str(m) for m in non_field) if non_field else "Validation failed."
        response.data = {"detail": detail, "errors": data}
    elif isinstance(data, list):
        response.data = {"detail": " ".join(str(m) for m in data), "errors": {"non_field_errors": data}}
    return response
