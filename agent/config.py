import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-4b-32k-fast")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "azure")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "sqlite")
DYNAMO_TABLE = os.getenv("DYNAMO_TABLE", "voicekb")
S3_BUCKET = os.getenv("S3_BUCKET", "voicekb-assets")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
