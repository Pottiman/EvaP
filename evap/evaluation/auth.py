from functools import wraps

from django.core.exceptions import PermissionDenied
from django.contrib import auth
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.backends import ModelBackend, RemoteUserBackend
from django.contrib.auth.models import User
from django.utils.decorators import available_attrs

from evaluation.models import UserProfile

class RequestAuthMiddleware(object):
    """
    Middleware for utilizing request-based authentication.

    If request.user is not authenticated, then this middleware attempts to
    authenticate a user with the ``userkey`` URL variable.
    If authentication is successful, the user is automatically logged in to
    persist the user in the session.
    """
    
    field_name = "userkey"

    def process_request(self, request):
        # AuthenticationMiddleware is required so that request.user exists.
        if not hasattr(request, 'user'):
            raise ImproperlyConfigured(
                "The Django remote user auth middleware requires the"
                " authentication middleware to be installed.  Edit your"
                " MIDDLEWARE_CLASSES setting to insert"
                " 'django.contrib.auth.middleware.AuthenticationMiddleware'"
                " before the RequestAuthMiddleware class.")
        
        try:
            key = request.GET[self.field_name]
        except KeyError:
            # If specified variable doesn't exist then return (leaving
            # request.user set to AnonymousUser by the
            # AuthenticationMiddleware).
            return

        # We are seeing this user for the first time in this session, attempt
        # to authenticate the user.
        user = auth.authenticate(key=key)
        if user:
            # User is valid.  Set request.user and persist user in the session
            # by logging the user in.
            request.user = user
            auth.login(request, user)

class CaseInsensitiveModelBackend(ModelBackend):
    """
    By default ModelBackend does case _sensitive_ username authentication, which isn't what is
    generally expected.  This backend supports case insensitive username authentication.
    """
    def authenticate(self, username=None, password=None):
        try:
            user = User.objects.get(username__iexact=username)
            if user.check_password(password):
                return user
            else:
                return None
        except User.DoesNotExist:
            return None

class CaseInsensitiveRemoteUserBackend(RemoteUserBackend):
    """
    By default RemoteUserBackend does case _sensitive_ username authentication, which isn't what is
    generally expected.  This backend supports case insensitive username authentication.
    """
    def authenticate(self, remote_user):
        """
        The username passed as ``remote_user`` is considered trusted.  This
        method simply returns the ``User`` object with the given username,
        creating a new ``User`` object if ``create_unknown_user`` is ``True``.
        
        Returns None if ``create_unknown_user`` is ``False`` and a ``User``
        object with the given username is not found in the database.
        """
        
        if not remote_user:
            return
        
        user = None
        username = self.clean_username(remote_user)
        
        # Note that this could be accomplished in one try-except clause, but
        # instead we use get_or_create when creating unknown users since it has
        # built-in safeguards for multiple threads.
        if self.create_unknown_user:
            user, created = User.objects.get_or_create(username__iexact=username)
            if created:
                user = self.configure_user(user)
        else:
            try:
                user = User.objects.get(username__iexact=username)
            except User.DoesNotExist:
                pass
        return user

class RequestAuthUserBackend(ModelBackend):
    """
    The RequestAuthBackend works together with the RequestAuthMiddleware to
    allow authentication of users via URL parameters, i.e. supplied in an
    email.
    
    It looks for the appropriate key in the logon_key field of the UserProfile.
    """
    def authenticate(self, key):
        if not key:
            return
        
        user = None
        
        try:
            profile = UserProfile.objects.get(logon_key=key)
            user = profile.user
        except UserProfile.DoesNotExist:
            pass
        
        return user

def user_passes_test_without_redirect(test_func):
    """
    Decorator for views that checks that the user passes the given test.
    The test should be a callable that takes the user object and returns
    True if the user passes.
    """
    
    def decorator(view_func):
        @wraps(view_func, assigned=available_attrs(view_func))
        def _wrapped_view(request, *args, **kwargs):
            if test_func(request.user):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped_view
    return decorator

def login_required(func):
    """
    Decorator for views that checks that the user is logged in
    """
    def check_user(user):
        return user.is_authenticated()
    return user_passes_test_without_redirect(check_user)(func)

def fsr_required(func):
    """
    Decorator for views that checks that the user is logged in and member
    of the student representatives
    """
    
    def check_user(user):
        if not user.is_authenticated():
            return False
        return user.get_profile().fsr
    return user_passes_test_without_redirect(check_user)(func)

def lecturer_required(func):
    """
    Decorator for views that checks that the user is logged in and lectures
    a course in the latest semester
    """
    
    def check_user(user):
        if not user.is_authenticated():
            return False
        return user.get_profile().lectures_courses()
    return user_passes_test_without_redirect(check_user)(func)