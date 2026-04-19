import os

from django.http import HttpResponse


class SimpleCorsMiddleware:
    """
    轻量级 CORS 中间件，适合前后端分离场景。
    通过环境变量 CORS_ALLOW_ORIGINS 控制允许来源（逗号分隔，默认 *）。
    """

    def __init__(self, get_response):
        self.get_response = get_response
        raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
        self.allow_all = raw_origins.strip() == "*"
        self.allowed_origins = {item.strip() for item in raw_origins.split(",") if item.strip()}

    def __call__(self, request):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        return self._attach_headers(request, response)

    def _attach_headers(self, request, response):
        origin = request.headers.get("Origin", "")
        allow_origin = ""
        if self.allow_all:
            allow_origin = origin or "*"
        elif origin in self.allowed_origins:
            allow_origin = origin

        if allow_origin:
            response["Access-Control-Allow-Origin"] = allow_origin
            response["Vary"] = "Origin"

        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"
        response["Access-Control-Max-Age"] = "86400"
        return response
