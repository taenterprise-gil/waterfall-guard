import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    epic_fhir_base_url: str = os.environ.get("EPIC_FHIR_BASE_URL", "")
    epic_client_id: str = os.environ.get("EPIC_CLIENT_ID", "")
    epic_client_secret: str = os.environ.get("EPIC_CLIENT_SECRET", "")
    epic_token_url: str = os.environ.get("EPIC_TOKEN_URL", "")
    orphan_threshold_days: int = int(os.environ.get("ORPHAN_THRESHOLD_DAYS", "14"))


settings = Settings()
