import os
from dataclasses import dataclass, field

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Settings:
    data_dir: str = os.environ.get("DATA_DIR", os.path.join(BACKEND, "data"))
    # The static preview, NOT ../frontend: that is the Next.js app, and serving its folder would
    # publish its .env.local.
    frontend_dir: str = os.environ.get("FRONTEND_DIR", os.path.join(BACKEND, "preview"))
    workers: int = int(os.environ.get("WORKERS", "1"))
    max_upload_mb: float = float(os.environ.get("MAX_UPLOAD_MB", "25"))
    cors_origins: list = field(default_factory=lambda: [o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o])


settings = Settings()
os.makedirs(os.path.join(settings.data_dir, "patients"), exist_ok=True)
