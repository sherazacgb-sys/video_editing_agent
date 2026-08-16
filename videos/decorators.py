from functools import wraps

from django.contrib.auth.views import redirect_to_login


def identity_required(view_func):
    """
    Like @login_required, but also admits an anonymous request that already
    carries a guest_id (i.e. already chose "Continue as guest" once — see
    views.continue_as_guest and GuestIdentityMiddleware). A request with
    neither is sent to the login page, which offers both options.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated or request.guest_id is not None:
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path())
    return _wrapped
