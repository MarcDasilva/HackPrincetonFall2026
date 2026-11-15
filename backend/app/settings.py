import os
from dataclasses import dataclass, field

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# backend/.env holds the secrets (ANTHROPIC_API_KEY for ear detection, earrecon/detect.py). Read it HERE, at import, so EVERY
# way of starting the server has them — a restart that forgot to export the file left detection failing with "missing key".
# A variable already set in the environment wins.
_env = os.path.join(BACKEND, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _k, _eq, _v = _line.strip().partition("=")
        if _eq and _k and not _k.startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))


@dataclass
class Settings:
    data_dir: str = os.environ.get("DATA_DIR", os.path.join(BACKEND, "data"))
    # The static preview, NOT ../frontend: that is the Next.js app, and serving its folder would
    # publish its .env.local.
    frontend_dir: str = os.environ.get("FRONTEND_DIR", os.path.join(BACKEND, "preview"))
    workers: int = int(os.environ.get("WORKERS", "2"))   # 2: both ears of a patient at once
    max_upload_mb: float = float(os.environ.get("MAX_UPLOAD_MB", "25"))
    cors_origins: list = field(default_factory=lambda: [o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o])


settings = Settings()
os.makedirs(os.path.join(settings.data_dir, "patients"), exist_ok=True)
