# File: portal/utils.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-27

from django.core.exceptions import ValidationError
import pikepdf
from django.utils.translation import gettext_lazy as _

def validate_pdf_upload(uploaded_file, max_size_mb=20):
    """
    Validate uploaded PDF file for size and security.
    Raises ValidationError if invalid.
    """
    max_size = max_size_mb * 1024 * 1024
    
    if uploaded_file.size > max_size:
        raise ValidationError(
            _("File size exceeds %(size)dMB. Please upload a smaller file.") 
            % {'size': max_size_mb}
        )
    
    if not uploaded_file.name.lower().endswith('.pdf'):
        raise ValidationError(_("Only PDF files are allowed."))
    
    try:
        uploaded_file.seek(0)
        pdf = pikepdf.open(uploaded_file)
        
        if '/EmbeddedFiles' in pdf.Root.get('/Names', {}):
            raise ValidationError(
                _("PDF contains embedded files, not allowed for security.")
            )
        
        if '/JavaScript' in pdf.Root.get('/Names', {}):
            raise ValidationError(
                _("PDF contains JavaScript, not allowed for security.")
            )
        
        pdf.close()
    except pikepdf.PdfError:
        raise ValidationError(_("Invalid or corrupted PDF file."))
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(_("Unable to validate PDF file."))
    
    uploaded_file.seek(0)
    return uploaded_file