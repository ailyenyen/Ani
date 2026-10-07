"""
Sign-in for Ani's SQLAlchemy ``User`` model.

Passwords are hashed with Django's password hashers; the signed-in user's id
is kept in the (signed cookie) session.
"""
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect
from django.urls import reverse
from sqlalchemy import func, select

from .models import User

SESSION_KEY = "ani_user_id"


def hash_password(raw_password):
    return make_password(raw_password)


def verify_password(user, raw_password):
    return check_password(raw_password, user.password)


def find_user_by_email(db, email):
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def authenticate(db, email, password):
    user = find_user_by_email(db, email)
    if user and verify_password(user, password):
        return user
    # Run the hasher anyway so response time doesn't reveal whether the email exists.
    make_password(password)
    return None


def login(request, user):
    request.session.cycle_key()
    request.session[SESSION_KEY] = user.id
    request.ani_user = user


def logout(request):
    request.session.flush()
    request.ani_user = None


def load_user(request):
    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        return None
    return request.db.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.ani_user is None:
            messages.info(request, "Please log in first. It only takes a moment.")
            return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")
        return view(request, *args, **kwargs)

    return wrapper
