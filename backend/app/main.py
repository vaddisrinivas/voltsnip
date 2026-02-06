import sys
import asyncio
from app.factory import create_app
from app.constants import PLATFORM_WIN32

if sys.platform != PLATFORM_WIN32:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except Exception:
        pass

app = create_app()
