from __future__ import annotations

from http import HTTPStatus
from typing import Any

from django.http import JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def build_error_payload(
    *,
    detail: str,
    code: str | None = None,
    errors: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"detail": detail}
    if code is not None:
        payload["code"] = code
    if errors not in (None, {}, []):
        payload["errors"] = errors
    return payload


def _flatten_messages(detail: Any) -> list[str]:
    if isinstance(detail, dict):
        messages: list[str] = []
        for value in detail.values():
            messages.extend(_flatten_messages(value))
        return messages
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            messages.extend(_flatten_messages(item))
        return messages
    return [str(detail)]


def _normalize_validation_error(detail: Any) -> Response:
    if isinstance(detail, dict):
        messages = _flatten_messages(detail)
        return Response(
            build_error_payload(
                detail=messages[0] if messages else "Request validation failed",
                code="validation_error",
                errors=detail,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(detail, list):
        messages = _flatten_messages(detail)
        return Response(
            build_error_payload(
                detail=messages[0] if messages else "Request validation failed",
                code="validation_error",
                errors=detail,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        build_error_payload(
            detail=str(detail),
            code="validation_error",
        ),
        status=status.HTTP_400_BAD_REQUEST,
    )


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        return _normalize_validation_error(detail)

    if isinstance(detail, dict):
        message = detail.get("detail")
        if isinstance(message, list):
            message = " ".join(str(item) for item in message)
        if isinstance(message, str):
            return Response(
                build_error_payload(
                    detail=message,
                    code=HTTPStatus(response.status_code).phrase.lower().replace(" ", "_"),
                    errors=detail if set(detail.keys()) != {"detail"} else None,
                ),
                status=response.status_code,
            )
        return Response(
            build_error_payload(
                detail="Request failed",
                code=HTTPStatus(response.status_code).phrase.lower().replace(" ", "_"),
                errors=detail,
            ),
            status=response.status_code,
        )

    return Response(
        build_error_payload(
            detail=str(detail),
            code=HTTPStatus(response.status_code).phrase.lower().replace(" ", "_"),
        ),
        status=response.status_code,
    )


def json_not_found(_: Any, exception: Exception) -> JsonResponse:
    return JsonResponse(
        build_error_payload(
            detail="The requested endpoint was not found",
            code="not_found",
        ),
        status=404,
    )


def json_server_error(_: Any) -> JsonResponse:
    return JsonResponse(
        build_error_payload(
            detail="Internal server error",
            code="internal_server_error",
        ),
        status=500,
    )
