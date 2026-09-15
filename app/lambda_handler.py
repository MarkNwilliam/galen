"""AWS Lambda entrypoint.

Mangum adapts the ASGI app to Lambda's event/response model. The Lambda
filesystem is read-only, so the deployed function sets STORAGE_BACKEND=dynamodb
(see agent/repo.py); the SQLite backend remains the default everywhere else.
"""
from mangum import Mangum

from agent import repo
from app.main import app

repo.init()

handler = Mangum(app, lifespan="off")
