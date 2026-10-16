"""Read-only BI API for Power BI (Web connector) and other analytical clients.

Authentication: session (browser) or `Authorization: Token <key>` (Power BI). Tokens are
accepted *only* by these endpoints, are issued to users holding `bi.access`, and can only
read whitelisted views in the `bi` schema.
"""
from __future__ import annotations

import csv
import io

from django.db import connection
from django.http import HttpResponse
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.accounts.permissions import HasPerm

from .datasets import DATASETS

MAX_PAGE = 50_000


class BIView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [HasPerm.of("bi.access")]


class DatasetListView(BIView):
    def get(self, request):
        return Response([{"name": n, **meta, "url": f"/api/bi/datasets/{n}/"} for n, meta in DATASETS.items()])


class DatasetView(BIView):
    """GET /api/bi/datasets/<name>/?limit=&offset=&output=json|csv"""

    def get(self, request, name: str):
        if name not in DATASETS:  # whitelist: the name is never interpolated unless it is a known view
            raise NotFound("Unknown dataset.")
        try:
            limit = min(int(request.query_params.get("limit", MAX_PAGE)), MAX_PAGE)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError as exc:
            raise ValidationError({"limit": "limit and offset must be integers."}) from exc
        key = DATASETS[name]["key"]
        with connection.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM bi."{name}"')
            total = cur.fetchone()[0]
            cur.execute(f'SELECT * FROM bi."{name}" ORDER BY "{key}" LIMIT %s OFFSET %s', [limit, offset])
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
        if request.query_params.get("output") == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            writer.writerows(rows)
            response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
            response["X-Total-Count"] = str(total)
            return response
        return Response({"dataset": name, "count": total, "limit": limit, "offset": offset, "columns": columns,
                         "rows": [dict(zip(columns, r, strict=False)) for r in rows]})


class TokenView(APIView):
    """POST: issue or rotate your personal BI token (shown once). DELETE: revoke it. Session-authenticated only."""
    permission_classes = [HasPerm.of("bi.access")]

    def get(self, request):
        token = Token.objects.filter(user=request.user).first()
        return Response({"has_token": token is not None, "created": token.created if token else None})

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        token = Token.objects.create(user=request.user)
        audit.record(request.user, AuditLog.Action.SECURITY, request.user, message="BI API token issued/rotated")
        return Response({"token": token.key, "created": token.created,
                         "note": "Store this token securely; it will not be shown again."}, status=201)

    def delete(self, request):
        deleted, _ = Token.objects.filter(user=request.user).delete()
        audit.record(request.user, AuditLog.Action.SECURITY, request.user, message="BI API token revoked")
        return Response({"revoked": bool(deleted)})
