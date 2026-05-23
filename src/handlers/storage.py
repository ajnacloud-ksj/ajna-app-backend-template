"""Storage presigned URL endpoints."""
from ajna_cloud.handlers.storage import make_storage_handlers

_handlers = make_storage_handlers()

get_upload_url = _handlers.get_upload_url
get_download_url = _handlers.get_download_url
