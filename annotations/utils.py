# File: annotations/utils.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

class HankoSignAction:
    """
    Standard HankoSign workflow action types with bilingual text templates.
    
    Use these constants instead of writing custom text for workflow actions.
    Each action has a standardized bilingual message format.
    """
    # Action constants
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    VERIFY = "VERIFY"
    RELEASE = "RELEASE"
    SUBMIT = "SUBMIT"
    WITHDRAW = "WITHDRAW"
    
    # Bilingual templates (DE / EN)
    # Format: "[HS] German text / English text {user}"
    TEMPLATES = {
        "LOCK": "Gesperrt durch / Locked by {user}",
        "UNLOCK": "Entsperrt durch / Unlocked by {user}",
        "APPROVE": "Genehmigt durch / Approved by {user}",
        "REJECT": "Zurückgewiesen durch / Rejected by {user}",
        "VERIFY": "Bestätigt durch / Verified by {user}",
        "RELEASE": "Freigegeben durch / Released by {user}",
        "SUBMIT": "Eingereicht durch / Submitted by {user}",
        "WITHDRAW": "Zurückgezogen durch / Withdrawn by {user}",
    }
    
    @classmethod
    def get_text(cls, action_type, user):
        """
        Get formatted bilingual text for a HankoSign action.
        
        Args:
            action_type: One of the action constants (e.g., "LOCK")
            user: Django User object
            
        Returns:
            Formatted text string with [HS] prefix, or None if action unknown
            
        Example:
            >>> HankoSignAction.get_text("LOCK", user)
            "[HS] Gesperrt durch / Locked by Sven Varszegi"
        """
        template = cls.TEMPLATES.get(action_type)
        if not template:
            return None
        
        user_name = user.get_full_name() if user and hasattr(user, 'get_full_name') else "System"
        return f"[HS] {template.format(user=user_name)}"