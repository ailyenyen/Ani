from .auth import load_user
from .db import get_session


class AniMiddleware:
    """Opens a SQLAlchemy session for each request and loads the signed-in user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.db = get_session()
        try:
            request.ani_user = load_user(request)
            return self.get_response(request)
        finally:
            # Anything a view did not commit is rolled back here.
            request.db.close()
