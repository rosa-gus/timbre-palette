from workers import asgi

from palette_api.api import app


Default = asgi.entrypoint(app)

