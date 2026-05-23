"""Local dev server — wraps the Lambda handler in a FastAPI app."""
from dotenv import load_dotenv
load_dotenv()

from ajna_cloud.dev import create_local_app
from src.app import lambda_handler

app = create_local_app(lambda_handler, title='{{app-name}} (Local Dev)')
