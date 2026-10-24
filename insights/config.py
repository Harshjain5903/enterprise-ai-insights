import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional for tests
    pass


@dataclass(frozen=True)
class Settings:
    project: str
    location: str = "global"
    dataset: str = "enterprise_ai_insights"
    bq_location: str = "US"
    model: str = "gemini-2.5-flash"
    tz: str = "America/Chicago"
    max_bytes_billed: int = 2_000_000_000
    temperature: float = 0.2
    max_input_tokens: int = 6000
    # "studio" = Gemini API key (free tier), "vertex" = Vertex AI (needs billing)
    gemini_backend: str = "studio"
    gemini_api_key: str | None = None
    # BigQuery sandbox (no billing): no DML, so loads rebuild tables instead of MERGE
    sandbox: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set (see .env.example)")
        return cls(
            project=project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            dataset=os.getenv("BQ_DATASET", "enterprise_ai_insights"),
            bq_location=os.getenv("BQ_LOCATION", "US"),
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            tz=os.getenv("REPORT_TZ", "America/Chicago"),
            max_bytes_billed=int(os.getenv("MAX_BYTES_BILLED", "2000000000")),
            gemini_backend=os.getenv("GEMINI_BACKEND", "studio").lower(),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            sandbox=os.getenv("BQ_SANDBOX", "0").lower() in ("1", "true", "yes"),
        )
