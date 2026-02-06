from starlette.routing import Mount

from app.factory import create_app
import app.globals as app_globals


def test_mcp_mount_exists():
    app = create_app()
    mounts = [route for route in app.routes if isinstance(route, Mount)]

    assert app_globals.mcp_app is not None
    assert any(mount.path == "/mcp" for mount in mounts)
