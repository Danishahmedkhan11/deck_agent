"""Shared Google GenAI client (Vertex AI backend)."""
import os
from functools import lru_cache

from google import genai
from models.config import Settings


@lru_cache(maxsize=1)
def get_client(project: str, location: str, credentials_path: str) -> genai.Client:
    if credentials_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    return genai.Client(vertexai=True, project=project, location=location)


def make_client(settings: Settings) -> genai.Client:
    return get_client(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.google_application_credentials,
    )
