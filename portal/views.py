"""
Fixed Portal Views - Academia follows payment plan pattern
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_http_methods
from core.pdf import render_pdf_response
from hankosign.utils import seal_signatures_context
from django.utils.text import slugify

from academia.models import Semester, InboxRequest, InboxCourse
from academia.utils import validate_ects_total
from organisation.models import OrgInfo
from people.models import PersonRole, Person
from finances.models import FiscalYear, PaymentPlan

from .forms import (
    AccessCodeForm, FileRequestForm, CourseFormSet, UploadFormForm,
    PaymentAccessForm, BankingDetailsForm, PaymentUploadForm
)


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


# ============================================================================
# Portal Landing
# ============================================================================

@ratelimit(key='ip', rate='30/m', method='GET')
def portal_home(request):
    """Portal landing page with menu to choose between ECTS Filing and Payment Plans."""
    context = {
        'page_title': _("Self Service Portal")
    }
    return render(request, 'portal/home.html', context)


# ============================================================================
# ECTS Filing Portal Views (Following Payment Plan Pattern)
# ============================================================================

@ratelimit(key='ip', rate='30/m', method='GET')
def semester_list(request):
    """Landing page showing available semesters for filing."""
    now = timezone.now()
    open_semesters = Semester.objects.filter(
        filing_start__lte=now,
        filing_end__gte=now
    ).order_by('-start_date')

    # Handle status check
    if request.GET.get('check_status') and request.GET.get('reference_code'):
        reference_code = request.GET.get('reference_code', '').strip()
        try:
            inbox_request = InboxRequest.objects.get(reference_code__iexact=reference_code)
            return redirect('portal:academia:status', reference_code=inbox_request.reference_code)
        except InboxRequest.DoesNotExist:
            messages.error(request, _("Reference code not found: %(ref)s") % {'ref': reference_code})

    context = {
        'open_semesters': open_semesters,
        'page_title': _("ECTS Filing Portal")
    }
    return render(request, 'portal/semester_list.html', context)


@ratelimit(key='ip', rate='30/m', method=['GET', 'POST'])
@require_http_methods(["GET", "POST"])
def access_login(request, semester_id):
    """Access code entry page. Handles semester codes (new) and reference codes (status)."""
    semester = get_object_or_404(Semester, pk=semester_id)

    if not semester.is_filing_open:
        messages.error(request, _("Filing is not currently open for this semester."))
        return redirect('portal:academia:semester_list')

    if request.method == 'POST':
        form = AccessCodeForm(request.POST, semester=semester)
        if form.is_valid():
            if form.access_type == 'semester':
                request.session['semester_id'] = semester.id
                request.session['semester_authenticated'] = True
                return redirect('portal:academia:file_request', semester_id=semester.id)
            elif form.access_type == 'reference':
                return redirect('portal:academia:status', reference_code=form.inbox_request.reference_code)
    else:
        form = AccessCodeForm(semester=semester)

    context = {
        'form': form,
        'semester': semester,
        'page_title': _("Access Code")
    }
    return render(request, 'portal/access_login.html', context)


@ratelimit(key='ip', rate='20/m', method=['GET', 'POST'])
@require_http_methods(["GET", "POST"])
@transaction.atomic
def file_request(request, semester_id):
    """
    File a new ECTS request - FIRST STEP ONLY.
    Select role, add courses, confirm affidavit 1 → Create InboxRequest → Redirect to status.
    """
    semester = get_object_or_404(Semester, pk=semester_id)

    # Check session auth
    if not request.session.get('semester_authenticated') or request.session.get('semester_id') != semester.id:
        messages.error(request, _("Please enter the access code first."))
        return redirect('portal:academia:access_login', semester_id=semester.id)

    if not semester.is_filing_open:
        messages.error(request, _("Filing period has ended for this semester."))
        return redirect('portal:academia:semester_list')

    org = OrgInfo.get_solo()

    if request.method == 'POST':
        form = FileRequestForm(request.POST, semester=semester)
        course_formset = CourseFormSet(request.POST, prefix='courses')

        if form.is_valid() and course_formset.is_valid():
            person_role = form.cleaned_data['person_role']
            student_note = form.cleaned_data['student_note']

            # Check if already exists
            existing = InboxRequest.objects.filter(
                semester=semester,
                person_role__person=person_role.person
            ).first()

            if existing:
                messages.warning(
                    request,
                    _("You already have a request for this semester (%(ref)s).") % {'ref': existing.reference_code}
                )
                return redirect('portal:academia:status', reference_code=existing.reference_code)

            # Collect courses
            courses_data = []
            for course_form in course_formset:
                if course_form.cleaned_data and not course_form.cleaned_data.get('DELETE', False):
                    course_code = course_form.cleaned_data.get('course_code', '').strip()
                    course_name = course_form.cleaned_data.get('course_name', '').strip()
                    ects_amount = course_form.cleaned_data.get('ects_amount')

                    if (course_code or course_name) and ects_amount:
                        courses_data.append({
                            'course_code': course_code,
                            'course_name': course_name,
                            'ects_amount': ects_amount
                        })

            if not courses_data:
                messages.error(request, _("Please add at least one course."))
                context = {
                    'form': form,
                    'course_formset': course_formset,
                    'semester': semester,
                    'org': org,
                    'affidavit_1': org.ects_affidavit_1,
                    'page_title': _("File Request")
                }
                return render(request, 'portal/file_request.html', context)

            # Create InboxRequest
            inbox_request = InboxRequest.objects.create(
                semester=semester,
                person_role=person_role,
                student_note=student_note,
                filing_source='PUBLIC',
                affidavit1_confirmed_at=timezone.now(),
                submission_ip=get_client_ip(request)
            )

            # Create courses
            for course_data in courses_data:
                InboxCourse.objects.create(
                    inbox_request=inbox_request,
                    **course_data
                )

            # Validate ECTS total
            is_valid, max_ects, total_ects, message = validate_ects_total(inbox_request)
            if not is_valid:
                messages.warning(request, _("Warning: ") + message)

            messages.success(
                request,
                _("✅ Request filed successfully! Your reference code is: %(ref)s") % {
                    'ref': inbox_request.reference_code
                }
            )

            # Clear session
            request.session.pop('semester_authenticated', None)
            request.session.pop('semester_id', None)

            # Redirect to status page
            return redirect('portal:academia:status', reference_code=inbox_request.reference_code)

    else:
        form = FileRequestForm(semester=semester)
        course_formset = CourseFormSet(prefix='courses')

    context = {
        'form': form,
        'course_formset': course_formset,
        'semester': semester,
        'org': org,
        'affidavit_1': org.ects_affidavit_1,
        'page_title': _("File Request")
    }
    return render(request, 'portal/file_request.html', context)


@ratelimit(key='ip', rate='30/m', method=['GET', 'POST'])
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def status(request, reference_code):
    """
    Status page for existing request - handles upload of signed form.
    Shows progress, allows upload if DRAFT/SUBMITTED, or just download if completed.
    """
    inbox_request = get_object_or_404(InboxRequest, reference_code__iexact=reference_code)
    org = OrgInfo.get_solo()
    stage = inbox_request.stage

    # Handle upload
    if request.method == 'POST' and stage in ('DRAFT', 'SUBMITTED') and not inbox_request.uploaded_form:
        upload_form = UploadFormForm(request.POST, request.FILES)
        if upload_form.is_valid():
            inbox_request.uploaded_form = upload_form.cleaned_data['uploaded_form']
            inbox_request.uploaded_form_at = timezone.now()
            inbox_request.affidavit2_confirmed_at = timezone.now()
            inbox_request.save(update_fields=['uploaded_form', 'uploaded_form_at', 'affidavit2_confirmed_at'])

            messages.success(
                request, 
                _("🎉 Form uploaded successfully! Your request is now being processed by our team.")
            )
            return redirect('portal:academia:status', reference_code=reference_code)
        else:
            for field, errors in upload_form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        upload_form = UploadFormForm()

    # Validate ECTS
    is_valid, max_ects, total_ects, message = validate_ects_total(inbox_request)

    context = {
        'inbox_request': inbox_request,
        'stage': stage,
        'org': org,
        'affidavit_2': org.ects_affidavit_2,
        'upload_form': upload_form,
        'is_valid': is_valid,
        'max_ects': max_ects,
        'total_ects': total_ects,
        'validation_message': message,
        'page_title': _("Request Status")
    }
    return render(request, 'portal/status.html', context)


@ratelimit(key='ip', rate='60/m', method='GET')
def request_pdf(request, reference_code):
    """Generate PDF for ECTS request (public access via reference code)."""
    inbox_request = get_object_or_404(InboxRequest, reference_code__iexact=reference_code)
    org = OrgInfo.get_solo()

    signatures = seal_signatures_context(inbox_request)

    context = {
        'request_obj': inbox_request,
        'org': org,
        'signatures': signatures,
        'signers': [
            {'label': inbox_request.person_role.person.last_name},
            {'label': 'LV-Leitung | FH OÖ'},
        ]
    }

    date_str = timezone.localtime().strftime("%Y-%m-%d")
    lname = slugify(inbox_request.person_role.person.last_name)[:20]

    return render_pdf_response(
        "academia/inboxrequest_form_pdf.html",
        context,
        request,
        f"ECTS-REQUEST_{inbox_request.reference_code}_{lname}_{date_str}.pdf"
    )


# ============================================================================
# Payment Plan Portal Views (Consolidated Anti-Ping-Pong Design)
# ============================================================================

@ratelimit(key='ip', rate='30/m', method='GET')
def fy_list(request):
    """Landing page showing available fiscal years with active payment plans."""
    now = timezone.now()
    active_fys = FiscalYear.objects.filter(is_active=True).order_by('-start')

    context = {
        'fiscal_years': active_fys,
        'page_title': _("Payment Plan Portal")
    }
    return render(request, 'portal/payments/fy_list.html', context)


@ratelimit(key='ip', rate='20/m', method=['GET', 'POST'])
@require_http_methods(['GET', 'POST'])
def payment_access(request, fy_code):
    """Enter Personal Access Code (PAC) to access payment plans for a fiscal year."""
    fiscal_year = get_object_or_404(FiscalYear, code=fy_code)

    if request.method == 'POST':
        form = PaymentAccessForm(request.POST, fiscal_year=fiscal_year)
        if form.is_valid():
            request.session['payment_person_id'] = form.person.id
            request.session['payment_fiscal_year_id'] = fiscal_year.id
            return redirect('portal:payments:plan_list', fy_code=fy_code)
    else:
        form = PaymentAccessForm(fiscal_year=fiscal_year)

    context = {
        'form': form,
        'fiscal_year': fiscal_year,
        'page_title': _("Access Payment Plans")
    }
    return render(request, 'portal/payments/access.html', context)


@ratelimit(key='ip', rate='30/m', method=['GET', 'POST'])
def plan_list(request, fy_code):
    """
    Consolidated payment plans view: show all plans with inline editing capability.
    """
    from django.urls import reverse
    
    fiscal_year = get_object_or_404(FiscalYear, code=fy_code)
    
    # Check session authentication
    if 'payment_person_id' not in request.session or \
       request.session.get('payment_fiscal_year_id') != fiscal_year.id:
        messages.warning(request, _("Please enter your access code first."))
        return redirect('portal:payments:payment_access', fy_code=fy_code)

    person = get_object_or_404(Person, id=request.session['payment_person_id'])
    
    # Get all payment plans for this person and fiscal year
    all_plans = PaymentPlan.objects.filter(
        person_role__person=person,
        fiscal_year=fiscal_year
    ).select_related('person_role', 'person_role__role', 'fiscal_year')

    # Handle inline form submissions
    if request.method == 'POST':
        plan_code = request.POST.get('plan_code')
        action = request.POST.get('action')
        
        if plan_code:
            payment_plan = get_object_or_404(PaymentPlan, 
                plan_code=plan_code,
                person_role__person=person
            )
            
            if action == 'save_banking' and payment_plan.status == 'DRAFT':
                # Handle banking details form
                form = BankingDetailsForm(request.POST, instance=payment_plan)
                if form.is_valid():
                    plan = form.save(commit=False)
                    plan.submission_ip = get_client_ip(request)
                    
                    # Auto-generate reference if not set by ÖH yet
                    if not plan.reference:
                        plan.reference = f"REF-{plan.plan_code}"
                    
                    plan.save()
                    
                    # Better success message that clearly indicates next steps
                    messages.success(request, _(
                        "✅ Banking details saved for %(code)s! Now please: "
                        "1️⃣ Review terms below, "
                        "2️⃣ Download & sign the PDF, "
                        "3️⃣ Upload the signed form to complete."
                    ) % {'code': plan_code})
                    
                    # Redirect with parameter to keep accordion open and scroll to next step
                    return redirect(f"{reverse('portal:payments:plan_list', args=[fy_code])}?plan_saved={plan_code}")
                else:
                    for field, errors in form.errors.items():
                        for error in errors:
                            messages.error(request, f"{payment_plan.plan_code} - {field}: {error}")

            elif action == 'upload_form':
                # Handle file upload (for completed banking details)
                upload_form = PaymentUploadForm(request.POST, request.FILES)
                if upload_form.is_valid():
                    payment_plan.pdf_file = upload_form.cleaned_data['pdf_file']
                    payment_plan.signed_person_at = upload_form.cleaned_data['signed_person_at']
                    payment_plan.save()
                    
                    # Completion success message
                    messages.success(request, _(
                        "🎉 Payment plan %(code)s completed successfully! "
                        "Your form has been uploaded and is now being processed."
                    ) % {'code': plan_code})
                    
                    return redirect('portal:payments:plan_list', fy_code=fy_code)
                else:
                    for field, errors in upload_form.errors.items():
                        for error in errors:
                            messages.error(request, f"{payment_plan.plan_code} - {field}: {error}")

    # THIS WAS MISSING - Create forms for DRAFT plans and render template
    plan_forms = {}
    upload_forms = {}
    org = OrgInfo.get_solo()  # FIXED: No comma that was causing tuple issue
    
    for plan in all_plans:
        if plan.status == 'DRAFT':
            plan_forms[plan.id] = BankingDetailsForm(instance=plan)
            # Show upload form if banking details are complete but not yet uploaded  
            # NOTE: Removed reference from requirement - ÖH manages this
            if (plan.payee_name and plan.iban and plan.bic and 
                plan.address and not plan.signed_person_at):
                upload_forms[plan.id] = PaymentUploadForm()

    context = {
        'person': person,
        'fiscal_year': fiscal_year,
        'all_plans': all_plans,
        'draft_plans': [p for p in all_plans if p.status == 'DRAFT'],
        'plan_forms': plan_forms,
        'upload_forms': upload_forms,
        'org': org,  # FIXED: Now properly passes the OrgInfo object
        'page_title': _("Your Payment Plans")
    }

    # THIS WAS MISSING - Return the rendered template
    return render(request, 'portal/payments/plan_list.html', context)


@ratelimit(key='ip', rate='60/m', method='GET')
def plan_pdf(request, plan_code):
    """Generate and download payment plan PDF (public access via plan code) - works for all stages."""
    payment_plan = get_object_or_404(PaymentPlan, plan_code=plan_code)
    org = OrgInfo.get_solo()
    
    # Get existing signatures (if any) for this payment plan - shows current workflow status
    signatures = seal_signatures_context(payment_plan)
    
    context = {
        'pp': payment_plan,
        'org': org,
        'signatures': signatures,  # Shows HankoSign status as receipt
        'signers': [
            {'label': payment_plan.person_role.person.last_name},
            {'label': 'WiRef'},
            {'label': 'Chair'},
        ]
    }
    
    # Generate filename with current timestamp for versioning
    date_str = timezone.localtime().strftime("%Y-%m-%d_%H-%M")
    lname = slugify(payment_plan.person_role.person.last_name)[:20]
    rsname = slugify(payment_plan.person_role.role.short_name)[:10]
    filename = f"PaymentPlan_{payment_plan.plan_code}_{rsname}_{lname}_{date_str}.pdf"
    
    return render_pdf_response(
        "finances/paymentplan_pdf.html",
        context,
        request,
        filename
    )


