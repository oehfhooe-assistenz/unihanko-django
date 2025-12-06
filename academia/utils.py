"""
Utility functions for Academia module.

Includes ECTS calculation, aliquotation, audit synchronization,
and password generation utilities.
"""
# File: academia/utils.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.utils import timezone
import random
import yaml
from pathlib import Path


# --- Password Generation -----------------------------------------------------

def get_random_words(count=2):
    """
    Get random words from wordlist for password generation.

    Args:
        count: Number of words to return

    Returns:
        List of random words
    """
    wordlist_path = Path(__file__).parent / 'wordlist.yaml'

    try:
        with open(wordlist_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            words = data.get('words', [])

            if not words:
                # Fallback words if YAML is empty
                words = [
                    'forest', 'mountain', 'river', 'ocean', 'valley',
                    'sunrise', 'sunset', 'thunder', 'breeze', 'meadow',
                    'glacier', 'canyon', 'desert', 'island', 'storm'
                ]

            return random.sample(words, min(count, len(words)))

    except FileNotFoundError:
        # Fallback if file doesn't exist yet
        fallback = [
            'forest', 'mountain', 'river', 'ocean', 'valley',
            'sunrise', 'sunset', 'thunder', 'breeze', 'meadow'
        ]
        return random.sample(fallback, count)


# --- ECTS Calculation --------------------------------------------------------


def validate_ects_total(inbox_request):
    """
    Validate that total ECTS from courses doesn't exceed the role's nominal ECTS cap.

    This is a formal validation only - checks against the role's max ECTS without
    aliquotation. The actual earned ECTS calculation (with aliquotation based on
    work period) happens during the audit phase.

    Args:
        inbox_request: InboxRequest instance

    Returns:
        tuple: (is_valid: bool, max_ects: Decimal, total_ects: Decimal, message: str)
    """
    from academia.models import InboxRequest

    # Get the role's nominal ECTS cap (formal limit, no aliquotation)
    person_role = inbox_request.person_role
    max_ects = Decimal(str(person_role.role.ects_cap))

    # Calculate total from courses
    total_ects = Decimal('0.00')
    for course in inbox_request.courses.all():
        total_ects += Decimal(str(course.ects_amount))

    is_valid = total_ects <= max_ects

    if not is_valid:
        message = f"Total ECTS ({total_ects}) exceeds role's maximum ({max_ects})."
    else:
        message = f"Total ECTS ({total_ects}) is within role's limit ({max_ects})."

    return is_valid, max_ects, total_ects, message
