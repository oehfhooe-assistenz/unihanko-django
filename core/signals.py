# File: core/signals.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
import logging

auth_logger = logging.getLogger('unihanko.auth')

def log_user_login(sender, request, user, **kwargs):
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    auth_logger.info(f"User '{user.username}' logged in from {ip}")

def log_user_logout(sender, request, user, **kwargs):
    auth_logger.info(f"User '{user.username}' logged out")

def log_user_login_failed(sender, credentials, request, **kwargs):
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    username = credentials.get('username', 'unknown')
    auth_logger.warning(f"Failed login attempt for '{username}' from {ip}")

user_logged_in.connect(log_user_login)
user_logged_out.connect(log_user_logout)
user_login_failed.connect(log_user_login_failed)