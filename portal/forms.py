# portal/forms.py
"""
Forms for the public ECTS filing portal.
"""
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.forms import formset_factory
from captcha.fields import CaptchaField
from decimal import Decimal
import pikepdf

from academia.models import InboxRequest, InboxCourse, Semester
from people.models import PersonRole


class AccessCodeForm(forms.Form):
    """
    Form for entering either semester access password or request reference code.
    """
    access_code = forms.CharField(
        label=_("Access Code"),
        max_length=50,
        widget=forms.TextInput(attrs={
            'placeholder': _('Enter semester code or reference code'),
            'class': 'form-input'
        }),
        help_text=_("Enter your semester access code (e.g., forest-mountain-23) for new filing, "
                   "or your reference code (e.g., WS24-MUEL-1234) to check status")
    )
    captcha = CaptchaField(label=_("Security Check"))

    def __init__(self, *args, semester=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.semester = semester
        self.access_type = None  # Will be 'semester' or 'reference'
        self.inbox_request = None  # Set if reference code is valid

    def clean_access_code(self):
        code = self.cleaned_data['access_code'].strip()

        # Try as reference code first (format: SSSS-LLLL-####)
        if '-' in code and len(code.split('-')) == 3:
            try:
                inbox_request = InboxRequest.objects.get(reference_code__iexact=code)
                # Verify it's for the current semester
                if self.semester and inbox_request.semester != self.semester:
                    raise ValidationError(
                        _("This reference code is not for the selected semester.")
                    )
                self.access_type = 'reference'
                self.inbox_request = inbox_request
                return code
            except InboxRequest.DoesNotExist:
                pass  # Fall through to try as semester code

        # Try as semester access password
        if self.semester:
            if self.semester.access_password.lower() == code.lower():
                self.access_type = 'semester'
                return code
            else:
                raise ValidationError(
                    _("Invalid access code. Please check and try again.")
                )

        raise ValidationError(
            _("Invalid access code format.")
        )


class CourseForm(forms.Form):
    """
    Form for a single course entry.
    """
    course_code = forms.CharField(
        label=_("Course Code"),
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': _('e.g., LV101'),
            'class': 'form-input'
        })
    )

    course_name = forms.CharField(
        label=_("Course Name"),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': _('e.g., Advanced Mathematics'),
            'class': 'form-input'
        })
    )

    ects_amount = forms.DecimalField(
        label=_("ECTS"),
        max_digits=3,
        decimal_places=1,
        min_value=Decimal('0.1'),
        widget=forms.NumberInput(attrs={
            'placeholder': _('e.g., 3.0'),
            'class': 'form-input',
            'step': '0.5'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        course_code = cleaned_data.get('course_code', '').strip()
        course_name = cleaned_data.get('course_name', '').strip()
        ects_amount = cleaned_data.get('ects_amount')

        # If ECTS is provided, at least one of code or name must be provided
        if ects_amount and not course_code and not course_name:
            raise ValidationError(
                _("Please provide either a course code or course name.")
            )

        # If any field is filled, ECTS must be provided
        if (course_code or course_name) and not ects_amount:
            raise ValidationError(
                _("Please provide ECTS amount for this course.")
            )

        return cleaned_data


# Formset for up to 10 courses
CourseFormSet = formset_factory(
    CourseForm,
    extra=10,
    max_num=10,
    validate_max=True
)


class FileRequestForm(forms.Form):
    """
    Form for filing a new ECTS request (selecting person role and courses).
    """
    person_role = forms.ModelChoiceField(
        label=_("Your Role"),
        queryset=PersonRole.objects.none(),  # Will be set in __init__
        empty_label=_("Select your role..."),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_("Select the role under which you are claiming ECTS")
    )

    student_note = forms.CharField(
        label=_("Notes (Optional)"),
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': _('Any additional information...'),
            'class': 'form-textarea'
        }),
        help_text=_("Optional notes about your request")
    )

    affidavit1_confirmed = forms.BooleanField(
        label=_("I confirm"),
        required=True,
        error_messages={
            'required': _("You must confirm the affidavit to proceed.")
        }
    )

    def __init__(self, *args, semester=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.semester = semester

        if semester:
            # Filter PersonRoles active during this semester, excluding system roles
            from django.db.models import Q
            self.fields['person_role'].queryset = PersonRole.objects.filter(
                Q(start_date__lte=semester.end_date),
                Q(end_date__gte=semester.start_date) | Q(end_date__isnull=True),
                role__is_system=False
            ).select_related('person', 'role').order_by(
                'person__last_name',
                'person__first_name',
                'role__name'
            )

            # Custom label to show person name, role, dates, and ECTS
            self.fields['person_role'].label_from_instance = self._label_from_instance

    def _label_from_instance(self, obj):
        """Custom label showing: Name - Role (dates) - X.X ECTS"""
        person = obj.person
        role = obj.role
        start = obj.start_date.strftime('%Y-%m-%d')
        end = obj.end_date.strftime('%Y-%m-%d') if obj.end_date else '…'
        ects = role.ects_cap

        return f"{person.last_name}, {person.first_name} - {role.name} ({start} → {end}) - {ects} ECTS"


class UploadFormForm(forms.Form):
    """
    Form for uploading the signed PDF form.
    """
    uploaded_form = forms.FileField(
        label=_("Signed PDF Form"),
        help_text=_("Upload your signed form (PDF, max 20MB)"),
        widget=forms.FileInput(attrs={
            'accept': '.pdf',
            'class': 'form-file'
        })
    )

    affidavit2_confirmed = forms.BooleanField(
        label=_("I confirm"),
        required=True,
        error_messages={
            'required': _("You must confirm the affidavit to proceed.")
        }
    )

    def clean_uploaded_form(self):
        uploaded_file = self.cleaned_data.get('uploaded_form')

        if not uploaded_file:
            return uploaded_file

        # Check file size (20MB)
        max_size = 20 * 1024 * 1024  # 20MB in bytes
        if uploaded_file.size > max_size:
            raise ValidationError(
                _("File size exceeds 20MB. Please upload a smaller file.")
            )

        # Check if it's a PDF
        if not uploaded_file.name.lower().endswith('.pdf'):
            raise ValidationError(
                _("Only PDF files are allowed.")
            )

        # Validate PDF with pikepdf (basic security checks)
        try:
            uploaded_file.seek(0)  # Reset file pointer
            pdf = pikepdf.open(uploaded_file)

            # Check for embedded files (potential malware vector)
            if '/EmbeddedFiles' in pdf.Root.get('/Names', {}):
                raise ValidationError(
                    _("PDF contains embedded files, which are not allowed for security reasons.")
                )

            # Check for JavaScript (potential XSS vector)
            # Note: eIDAS signatures are fine, they use /AcroForm which is different
            if '/JavaScript' in pdf.Root.get('/Names', {}):
                raise ValidationError(
                    _("PDF contains JavaScript, which is not allowed for security reasons.")
                )

            pdf.close()

        except pikepdf.PdfError as e:
            raise ValidationError(
                _("Invalid or corrupted PDF file. Please try another file.")
            )
        except Exception as e:
            # Catch any other errors during validation
            raise ValidationError(
                _("Unable to validate PDF file. Please ensure it's a valid PDF.")
            )

        # Reset file pointer for saving
        uploaded_file.seek(0)
        return uploaded_file
