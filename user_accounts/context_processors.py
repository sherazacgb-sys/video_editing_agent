def user_plan(request):
    # Inject the current user's plan into every template context so base.html
    # can show the subscription badge without each view passing it manually.
    if request.user.is_authenticated:
        try:
            plan = request.user.profile.plan
        except Exception:
            # Profile may not exist yet for users created before this app was added
            plan = 'free'
    else:
        plan = None  # Anonymous users have no plan
    return {'user_plan': plan}
