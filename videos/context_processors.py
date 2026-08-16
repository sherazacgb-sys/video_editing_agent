def guest_identity(request):
    # Injects the current guest_id (set by GuestIdentityMiddleware) into every
    # template context, so base.html can show a "Guest-xxxx" label without each
    # view passing it manually — mirrors user_accounts.context_processors.user_plan.
    return {'guest_id': getattr(request, 'guest_id', None)}
