from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_CHOICES = [
        (PLAN_FREE, 'Free'),
        (PLAN_PRO, 'Pro'),
    ]

    # One profile per Django user account
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # Subscription plan — defaults to free; set to pro manually (Stripe integration later)
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default=PLAN_FREE)

    def __str__(self):
        return f'{self.user.username} ({self.plan})'

    @property
    def is_pro(self):
        # Convenience check used in templates and views
        return self.plan == self.PLAN_PRO


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    # Auto-create a free profile whenever a new User is saved
    if created:
        UserProfile.objects.create(user=instance)
