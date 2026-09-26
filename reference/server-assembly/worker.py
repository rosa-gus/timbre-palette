from fastapi.middleware.cors import CORSMiddleware
from workers import asgi

from palette_api.api import app


# Keep CORS outside FastAPI's error middleware so unhandled 500s receive it too.
cors_app = CORSMiddleware(
    app,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept"],
)

Default = asgi.entrypoint(cors_app)
