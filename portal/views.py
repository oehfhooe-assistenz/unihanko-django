# portal/views.py
"""
Views for the public ECTS filing portal.
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

from academia.models import Semester, InboxRequest, InboxCourse
from academia.utils import validate_ects_total
from organisation.models import OrgInfo
from people.models import PersonRole

from .forms import (
    AccessCodeForm, FileRequestForm, CourseFormSet, UploadFormForm,
    PaymentAccessForm, BankingDetailsForm, PaymentUploadForm
)
from finances.models import FiscalYear, PaymentPlan, paymentplan_status
from people.models import Person


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
    """
    Portal landing page with menu to choose between ECTS Filing and Payment Plans.
    """
    context = {
        'page_title': _("Self Service Portal")
    }
    return render(request, 'portal/home.html', context)


# ============================================================================
# ECTS Filing Portal Views
# ============================================================================

@ratelimit(key='ip', rate='30/m', method='GET')
def semester_list(request):
    """
    Landing page showing available semesters for filing.
    """
    now = timezone.now()

    # Get semesters where filing is currently open
    open_semesters = Semester.objects.filter(
        filing_start__lte=now,
        filing_end__gte=now
    ).order_by('-start_date')

    context = {
        'open_semesters': open_semesters,
        'page_title': _("ECTS Filing Portal")
    }

    return render(request, 'portal/semester_list.html', context)


@ratelimit(key='ip', rate='30/m', method=['GET', 'POST'])
@require_http_methods(["GET", "POST"])
def access_login(request, semester_id):
    """
    Access code entry page. Handles both semester codes (new filing)
    and reference codes (status check).
    """
    semester = get_object_or_404(Semester, pk=semester_id)

    # Check if filing is open for this semester
    if not semester.is_filing_open:
        messages.error(request, _("Filing is not currently open for this semester."))
        return redirect('portal:semester_list')

    if request.method == 'POST':
        form = AccessCodeForm(request.POST, semester=semester)
        if form.is_valid():
            if form.access_type == 'semester':
                # New filing - store semester in session and redirect to file_request
                request.session['semester_id'] = semester.id
                request.session['semester_authenticated'] = True
                return redirect('portal:file_request', semester_id=semester.id)
            elif form.access_type == 'reference':
                # Status check - redirect to status page
                return redirect('portal:status', reference_code=form.inbox_request.reference_code)
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
def file_request(request, semester_id):
    """
    File a new ECTS request: select person role, add courses, confirm affidavit 1.
    """
    semester = get_object_or_404(Semester, pk=semester_id)

    # Check session authentication
    if not request.session.get('semester_authenticated') or request.session.get('semester_id') != semester.id:
        messages.error(request, _("Please enter the access code first."))
        return redirect('portal:access_login', semester_id=semester.id)

    # Check if filing is still open
    if not semester.is_filing_open:
        messages.error(request, _("Filing period has ended for this semester."))
        return redirect('portal:semester_list')

    org = OrgInfo.get()

    if request.method == 'POST':
        form = FileRequestForm(request.POST, semester=semester)
        course_formset = CourseFormSet(request.POST, prefix='courses')

        if form.is_valid() and course_formset.is_valid():
            person_role = form.cleaned_data['person_role']
            student_note = form.cleaned_data['student_note']

            # Check if this person already has a request for this semester
            existing = InboxRequest.objects.filter(
                semester=semester,
                person_role__person=person_role.person
            ).first()

            if existing:
                messages.error(
                    request,
                    _("You already have a request for this semester (%(ref)s). "
                      "Use your reference code to check its status.") % {'ref': existing.reference_code}
                )
                return redirect('portal:access_login', semester_id=semester.id)

            # Collect courses (only non-empty ones)
            courses_data = []
            total_ects = 0
            for course_form in course_formset:
                if course_form.cleaned_data and not course_form.cleaned_data.get('DELETE', False):
                    course_code = course_form.cleaned_data.get('course_code', '').strip()
                    course_name = course_form.cleaned_data.get('course_name', '').strip()
                    ects_amount = course_form.cleaned_data.get('ects_amount')

                    # Only include if at least one field is filled
                    if course_code or course_name or ects_amount:
                        if not (course_code or course_name):
                            messages.error(request, _("Each course must have a code or name."))
                            context = {
                                'form': form,
                                'course_formset': course_formset,
                                'semester': semester,
                                'org': org,
                                'affidavit_1': org.ects_affidavit_1,
                                'page_title': _("File Request")
                            }
                            return render(request, 'portal/file_request.html', context)

                        courses_data.append({
                            'course_code': course_code,
                            'course_name': course_name,
                            'ects_amount': ects_amount
                        })
                        total_ects += ects_amount

            # Validate at least one course
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

            # Validate total ECTS doesn't exceed role cap
            if total_ects > person_role.role.ects_cap:
                messages.error(
                    request,
                    _("Total ECTS (%(total)s) exceeds your role's maximum (%(max)s).") % {
                        'total': total_ects,
                        'max': person_role.role.ects_cap
                    }
                )
                context = {
                    'form': form,
                    'course_formset': course_formset,
                    'semester': semester,
                    'org': org,
                    'affidavit_1': org.ects_affidavit_1,
                    'page_title': _("File Request")
                }
                return render(request, 'portal/file_request.html', context)

            # Create inbox request and courses
            try:
                with transaction.atomic():
                    inbox_request = InboxRequest.objects.create(
                        semester=semester,
                        person_role=person_role,
                        student_note=student_note,
                        filing_source='PUBLIC',
                        submission_ip=get_client_ip(request),
                        affidavit1_confirmed_at=timezone.now()
                    )

                    # Create courses
                    for course_data in courses_data:
                        InboxCourse.objects.create(
                            inbox_request=inbox_request,
                            **course_data
                        )

                # Clear session
                request.session.pop('semester_authenticated', None)
                request.session.pop('semester_id', None)

                messages.success(
                    request,
                    _("Request filed successfully! Your reference code is: %(ref)s") % {
                        'ref': inbox_request.reference_code
                    }
                )
                return redirect('portal:status', reference_code=inbox_request.reference_code)

            except Exception as e:
                messages.error(request, _("An error occurred while filing your request. Please try again."))
                context = {
                    'form': form,
                    'course_formset': course_formset,
                    'semester': semester,
                    'org': org,
                    'affidavit_1': org.ects_affidavit_1,
                    'page_title': _("File Request")
                }
                return render(request, 'portal/file_request.html', context)
        else:
            # Form errors
            messages.error(request, _("Please correct the errors below."))
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
@require_http_methods(["GET", "POST"])
def status(request, reference_code):
    """
    Status page for an existing request.
    Shows current stage, allows PDF download and form upload.
    """
    inbox_request = get_object_or_404(InboxRequest, reference_code__iexact=reference_code)
    org = OrgInfo.get()
    stage = inbox_request.stage

    # Handle form upload
    if request.method == 'POST' and stage in ['DRAFT', 'SUBMITTED']:
        upload_form = UploadFormForm(request.POST, request.FILES)
        if upload_form.is_valid():
            try:
                inbox_request.uploaded_form = upload_form.cleaned_data['uploaded_form']
                inbox_request.affidavit2_confirmed_at = timezone.now()
                inbox_request.uploaded_form_at = timezone.now()
                inbox_request.save()

                messages.success(request, _("Form uploaded successfully!"))
                return redirect('portal:status', reference_code=reference_code)
            except Exception as e:
                messages.error(request, _("An error occurred while uploading the form. Please try again."))
    else:
        upload_form = UploadFormForm() if stage in ['DRAFT', 'SUBMITTED'] else None

    context = {
        'inbox_request': inbox_request,
        'org': org,
        'stage': stage,
        'upload_form': upload_form,
        'affidavit_2': org.ects_affidavit_2,
        'page_title': _("Request Status")
    }

    return render(request, 'portal/status.html', context)


@ratelimit(key='ip', rate='60/m', method='GET')
def request_pdf(request, reference_code):
    """
    Public PDF view - generates PDF for a request without authentication.
    """
    inbox_request = get_object_or_404(InboxRequest, reference_code__iexact=reference_code)
    org = OrgInfo.get()

    context = {
        'request_obj': inbox_request,
        'org': org,
    }

    # Use django-renderpdf or the existing PDF rendering mechanism
    return render(request, 'academia/inboxrequest_form_pdf.html', context, content_type='application/pdf')


# ============================================================================
# Payment Plan Portal Views
# ============================================================================

@ratelimit(key='ip', rate='30/m', method='GET')
def fy_list(request):
    """
    Landing page showing available fiscal years with active payment plans.
    """
    now = timezone.now()

    # Get fiscal years that are active
    active_fys = FiscalYear.objects.filter(
        is_active=True
    ).order_by('-start')

    context = {
        'fiscal_years': active_fys,
        'page_title': _("Payment Plan Portal")
    }

    return render(request, 'portal/payments/fy_list.html', context)


@ratelimit(key='ip', rate='20/m', method=['GET', 'POST'])
@require_http_methods(['GET', 'POST'])
def payment_access(request, fy_code):
    """
    Enter Personal Access Code (PAC) to access payment plans for a fiscal year.
    """
    fiscal_year = get_object_or_404(FiscalYear, code=fy_code)

    if request.method == 'POST':
        form = PaymentAccessForm(request.POST, fiscal_year=fiscal_year)
        if form.is_valid():
            # Store person ID in session
            request.session['payment_person_id'] = form.person.id
            request.session['payment_fiscal_year_id'] = fiscal_year.id

            # Redirect to plan list
            return redirect('portal:plan_list', fy_code=fy_code)
    else:
        form = PaymentAccessForm(fiscal_year=fiscal_year)

    context = {
        'form': form,
        'fiscal_year': fiscal_year,
        'page_title': _("Access Payment Plans")
    }

    return render(request, 'portal/payments/access.html', context)


@ratelimit(key='ip', rate='30/m', method='GET')
def plan_list(request, fy_code):
    """
    Show payment plans for authenticated person in this fiscal year.
    """
    fiscal_year = get_object_or_404(FiscalYear, code=fy_code)

    # Check session authentication
    if 'payment_person_id' not in request.session or \
       request.session.get('payment_fiscal_year_id') != fiscal_year.id:
        messages.warning(request, _("Please enter your access code first."))
        return redirect('portal:payment_access', fy_code=fy_code)

    person = get_object_or_404(Person, id=request.session['payment_person_id'])

    # Get payment plans for this person in this fiscal year
    # Mother decides = they're already created by admin, just need to be completed
    payment_plans = PaymentPlan.objects.filter(
        person_role__person=person,
        fiscal_year=fiscal_year
    ).select_related('person_role', 'person_role__role', 'fiscal_year')

    # Filter to show only DRAFT plans that need completion
    draft_plans = payment_plans.filter(status='DRAFT')

    context = {
        'person': person,
        'fiscal_year': fiscal_year,
        'draft_plans': draft_plans,
        'all_plans': payment_plans,
        'page_title': _("Your Payment Plans")
    }

    return render(request, 'portal/payments/plan_list.html', context)


@ratelimit(key='ip', rate='20/m', method=['GET', 'POST'])
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def complete_plan(request, plan_code):
    """
    Complete banking details for a payment plan.
    """
    payment_plan = get_object_or_404(PaymentPlan, plan_code=plan_code)

    # Check session authentication
    if 'payment_person_id' not in request.session or \
       request.session.get('payment_person_id') != payment_plan.person_role.person.id:
        messages.warning(request, _("Please enter your access code first."))
        return redirect('portal:payment_access', fy_code=payment_plan.fiscal_year.code)

    # Check if plan is in DRAFT status
    if payment_plan.status != 'DRAFT':
        messages.warning(request, _("This payment plan cannot be edited."))
        return redirect('portal:plan_status', plan_code=plan_code)

    # Get org disclaimer
    org = OrgInfo.get()
    disclaimer = org.payment_plan_disclaimer

    if request.method == 'POST':
        form = BankingDetailsForm(request.POST, instance=payment_plan)
        if form.is_valid():
            # Save banking details
            plan = form.save(commit=False)
            plan.submission_ip = get_client_ip(request)
            plan.save()

            messages.success(request, _("Banking details saved! You can now download and sign the form."))
            return redirect('portal:plan_status', plan_code=plan_code)
    else:
        form = BankingDetailsForm(instance=payment_plan)

    context = {
        'form': form,
        'payment_plan': payment_plan,
        'disclaimer': disclaimer,
        'page_title': _("Complete Payment Plan")
    }

    return render(request, 'portal/payments/complete.html', context)


@ratelimit(key='ip', rate='30/m', method=['GET', 'POST'])
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def plan_status(request, plan_code):
    """
    View payment plan status and upload signed form.
    """
    payment_plan = get_object_or_404(PaymentPlan, plan_code=plan_code)

    # Check session authentication
    if 'payment_person_id' not in request.session or \
       request.session.get('payment_person_id') != payment_plan.person_role.person.id:
        messages.warning(request, _("Please enter your access code first."))
        return redirect('portal:payment_access', fy_code=payment_plan.fiscal_year.code)

    # Determine current stage
    stage = paymentplan_status(payment_plan)

    # Show upload form only if banking details are complete but form not yet uploaded
    show_upload_form = (
        payment_plan.payee_name and
        payment_plan.iban and
        payment_plan.bic and
        not payment_plan.signed_person_at
    )

    upload_form = None
    if show_upload_form and request.method == 'POST':
        upload_form = PaymentUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            # Save uploaded file and signature date
            payment_plan.pdf_file = upload_form.cleaned_data['pdf_file']
            payment_plan.signed_person_at = upload_form.cleaned_data['signed_person_at']
            payment_plan.save()

            messages.success(request, _("Form uploaded successfully! The administration will review it soon."))
            return redirect('portal:plan_status', plan_code=plan_code)
    elif show_upload_form:
        upload_form = PaymentUploadForm()

    context = {
        'payment_plan': payment_plan,
        'stage': stage,
        'upload_form': upload_form,
        'page_title': _("Payment Plan Status")
    }

    return render(request, 'portal/payments/status.html', context)


@ratelimit(key='ip', rate='60/m', method='GET')
def plan_pdf(request, plan_code):
    """
    Generate and download payment plan PDF (public access via plan code).
    """
    payment_plan = get_object_or_404(PaymentPlan, plan_code=plan_code)
    org = OrgInfo.get()

    context = {
        'plan': payment_plan,
        'org': org,
    }

    # Use the existing payment plan PDF template
    return render(request, 'finances/paymentplan_pdf.html', context, content_type='application/pdf')
