"""Health check endpoints — backed by the SDK's make_health_handlers factory.

Exposes module-level check/ready/status so app.py can route them directly:
    ('GET', '/health'): health.check
    ('GET', '/ready'):  health.ready
    ('GET', '/status'): health.status
"""
from ajna_cloud import make_health_handlers

_handlers = make_health_handlers(service_name='{{app-name}}')

check = _handlers.check
ready = _handlers.ready
status = _handlers.status
