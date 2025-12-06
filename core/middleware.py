# File: core/middleware.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-12-04

from django.db import IntegrityError
from django.shortcuts import render
from django.utils.translation import gettext as _
import logging
import re
import os
import tempfile

admin_logger = logging.getLogger('unihanko.admin')


class ConstraintErrorMiddleware:
    """
    Middleware to catch database constraint violations and display user-friendly error pages.
    
    Catches IntegrityError exceptions globally and renders a styled error template
    instead of showing Django's 500 error page with stack traces.
    
    Handles:
    - UNIQUE constraint violations (duplicate records)
    - FOREIGN KEY constraint violations (referenced records)
    - CHECK constraint violations (invalid data)
    - NOT NULL constraint violations (missing required fields)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        return self.get_response(request)
    
    def process_exception(self, request, exception):
        """
        Called when any view raises an exception.
        If it's an IntegrityError, render friendly error page.
        """
        if not isinstance(exception, IntegrityError):
            return None  # Let Django handle other exceptions
        
        # Log the full error for debugging
        admin_logger.error(
            f"Database constraint violation: {exception}",
            exc_info=True,
            extra={
                'user': request.user.username if request.user.is_authenticated else 'anonymous',
                'path': request.path,
                'method': request.method,
            }
        )
        
        # Parse error message for user-friendly display
        error_message = str(exception)
        user_message, error_type = self._parse_constraint_error(error_message)
        
        context = {
            'error_type': error_type,
            'user_message': user_message,
            'technical_details': error_message if request.user.is_superuser else None,
        }
        
        return render(request, 'error_constraint.html', context, status=400)
    
    def _parse_constraint_error(self, error_message):
        """
        Parse IntegrityError message and return user-friendly message + error type.
        
        Returns:
            tuple: (user_message, error_type)
        """
        error_lower = error_message.lower()
        
        # UNIQUE constraint violations
        if 'unique constraint' in error_lower or 'unique_' in error_lower:
            # Try to extract field names from constraint name
            field_match = re.search(r'uq_\w+_(\w+)', error_message, re.IGNORECASE)
            if field_match:
                field = field_match.group(1).replace('_', ' ')
                return (
                    _("A record with this %(field)s already exists. Please use a different value.") % {'field': field},
                    'unique'
                )
            return (
                _("This record already exists. Please check for duplicates or modify your input."),
                'unique'
            )
        
        # FOREIGN KEY constraint violations
        if 'foreign key constraint' in error_lower or 'foreign_key' in error_lower:
            if 'delete' in error_lower or 'update' in error_lower:
                return (
                    _("This record cannot be deleted or modified because other records depend on it. "
                      "Please remove the dependent records first."),
                    'foreign_key'
                )
            return (
                _("The selected related record does not exist or has been deleted. "
                  "Please choose a valid option."),
                'foreign_key'
            )
        
        # CHECK constraint violations
        if 'check constraint' in error_lower or 'ck_' in error_lower:
            return (
                _("The data you entered violates business rules. "
                  "Please check that all dates, amounts, and values are valid."),
                'check'
            )
        
        # NOT NULL constraint violations
        if 'not null constraint' in error_lower or 'null value' in error_lower:
            field_match = re.search(r'column "(\w+)"', error_message, re.IGNORECASE)
            if field_match:
                field = field_match.group(1).replace('_', ' ')
                return (
                    _("The field '%(field)s' is required and cannot be empty.") % {'field': field},
                    'not_null'
                )
            return (
                _("A required field is missing. Please fill in all required fields."),
                'not_null'
            )
        
        # Generic fallback
        return (
            _("A database error occurred. Please check your input and try again. "
              "If the problem persists, contact support."),
            'generic'
        )
    
class MaintenanceModeMiddleware:
    """
    Middleware to enable/disable maintenance mode via file flag.
    
    When maintenance mode is active (flag file exists), all non-superuser
    requests are redirected to the maintenance page.
    
    To enable: python manage.py maintenance on
    To disable: python manage.py maintenance off
    
    Or manually: touch {temp_dir}/maintenance.flag (Linux/Mac)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Use OS-appropriate temp directory
        import tempfile
        self.flag_file = os.path.join(tempfile.gettempdir(), 'maintenance.flag')
    
    def __call__(self, request):
        # Check if maintenance mode is enabled
        if os.path.exists(self.flag_file):
            # Allow superusers to still access the site
            if request.user.is_authenticated and request.user.is_superuser:
                return self.get_response(request)
            
            # Show maintenance page to everyone else
            return render(request, 'maintenance.html', status=503)
        
        return self.get_response(request)