# File: config/settings_jazzmin.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from .settings import UNIHANKO_CODENAME, UNIHANKO_VERSION

JAZZMIN_SETTINGS = {
    # Branding
    "site_title": "UniHanko Back Office",
    "site_header": "UniHanko Back Office",
    "site_brand": "UniHanko",
    "welcome_sign": f'Welcome to UniHanko Back Office v{UNIHANKO_VERSION} "{UNIHANKO_CODENAME}"',
    "copyright": f'Sven Várszegi & ÖH FH OÖ • UniHanko {UNIHANKO_VERSION} ',
    "site_logo": "img/unihanko-logo.svg",            
    "login_logo": "img/unihanko-mark.svg",           
    "site_logo_classes": "img-fluid",

    # Quick nav
    "topmenu_links": [
        # examples you can add later:
        # {"app": "people"},                               # jump to the Personnel section
        # {"name": "Public site", "url": "/", "new_window": True},
    ],
    "usermenu_links": [
        {"model": "auth.user"},                         
    ],
    "search_model": ["people.PersonRole", "people.Person",],
    "icons": {
        # Academia - ECTS/Course management
        "academia": "fa-solid fa-graduation-cap",
        "academia.semester": "fa-solid fa-calendar-days",
        "academia.inboxrequest": "fa-solid fa-inbox",
        "academia.inboxcourse": "fa-solid fa-book-bookmark",

        # Academia Audit - Tracking/verification
        "academia_audit": "fa-solid fa-magnifying-glass-chart",
        "academia_audit.auditsemester": "fa-solid fa-table-list",
        "academia_audit.auditentry": "fa-solid fa-list-check",
        
        # Annotations
        "annotations": "fa-solid fa-comments",
        "annotations.annotation": "fa-solid fa-comment-dots",
        
        # Assembly - Parliamentary/governance
        "assembly": "fa-solid fa-landmark-dome",
        "assembly.term": "fa-solid fa-timeline",
        "assembly.composition": "fa-solid fa-diagram-project",
        "assembly.mandate": "fa-solid fa-certificate",
        "assembly.session": "fa-solid fa-gavel",
        "assembly.sessionattendance": "fa-solid fa-clipboard-user",
        "assembly.sessionitem": "fa-solid fa-list-ol",
        "assembly.vote": "fa-solid fa-square-poll-vertical",
        
        # Employees - HR/employment
        "employees": "fa-solid fa-address-book",
        "employees.holidaycalendar": "fa-solid fa-umbrella-beach",
        "employees.employee": "fa-solid fa-id-card",
        "employees.employeeleaveyear": "fa-solid fa-plane-departure",
        "employees.employmentdocument": "fa-solid fa-file-contract",
        "employees.timesheet": "fa-solid fa-clock",
        "employees.timeentry": "fa-solid fa-stopwatch",
        
        # Finances
        "finances": "fa-solid fa-coins",
        "finances.fiscalyear": "fa-solid fa-calendar-check",
        "finances.paymentplan": "fa-solid fa-money-check-dollar",
        
        # HankoSign - Digital signatures
        "hankosign": "fa-solid fa-stamp",
        "hankosign.action": "fa-solid fa-bolt",
        "hankosign.policy": "fa-solid fa-file-shield",
        "hankosign.signatory": "fa-solid fa-user-pen",
        "hankosign.signature": "fa-solid fa-signature",
        
        # Help Pages
        "helppages": "fa-solid fa-circle-question",
        "helppages.helppage": "fa-solid fa-book-open",
        
        # Organisation
        "organisation": "fa-solid fa-building",
        "organisation.orginfo": "fa-solid fa-building-columns",
        
        # People - Core personnel
        "people": "fa-solid fa-users",
        "people.person": "fa-solid fa-user",
        "people.role": "fa-solid fa-user-tag",
        "people.roletransitionreason": "fa-solid fa-arrow-right-arrow-left",
        "people.personrole": "fa-solid fa-user-check",   

        # Django built-ins
        "auth": "fa-solid fa-shield-halved",
        "auth.user": "fa-solid fa-user-lock",
        "auth.group": "fa-solid fa-users-rectangle",

        "sites": "fa-solid fa-network-wired",
        "sites.site": "fa-solid fa-server",

        "flatpages": "fa-solid fa-file-lines",
        "flatpages.flatpage": "fa-solid fa-file-alt",      
    },

    # Sidebar ordering within the app
    "order_with_respect_to": [
        # [potentially invisible]
        # Workables
        # Academia: Inbox > Semester
        "academia",
        "academia.inboxrequest",
        "academia.semester",
        # Academia Audit: [Entries] > Semester
        "academia_audit",
        "academia_audit.auditentry",
        "academia_audit.auditsemester",
        # Assembly: Session > [SessionItem] > Composition > Term
        "assembly", 
        "assembly.session", 
        "assembly.sessionitem",
        "assembly.composition", 
        "assembly.term",
        # Employees: TimeSheet > [TimeEntry] > EmploymentDocument > Employee > HolidayCalendar
        "employees", 
        "employees.timesheet",
        "employees.timeentry",
        "employees.employmentdocument", 
        "employees.employee", 
        "employees.holidaycalendar", 
        # Finances: PaymentPlan > FiscalYear
        "finances", 
        "finances.paymentplan", 
        "finances.fiscalyear", 
        # People: PersonRole > Person > RTR > Role
        "people", 
        "people.personrole", 
        "people.person", 
        "people.roletransitionreason", 
        "people.role", 
        # HankoSign: Signatory > [Signature] > Policy > Action
        "hankosign", 
        "hankosign.signatory", 
        "hankosign.policy", 
        "hankosign.action",

        # Configurables
        # Helppages: Helppage
        "helppages", 
        "helppages.helppage", 
        # Organisation
        "organisation", 
        "organisation.orginfo",

        # Django built-ins (always at the end)
        "flatpages",
        "flatpages.flatpage",
        "sites",
        "sites.site",
        "auth",
        "auth.user",
        "auth.group",
    ],


    # Hide historical models from menu
    "hide_models": [
        "academia.historicalsemester",
        "academia.historicalinboxrequest",
        "academia_audit.historicalauditsemester",
        "academia_audit.historicalauditentry",
        "assembly.historicalterm",
        "assembly.historicalcomposition",
        "assembly.historicalmandate",
        "assembly.historicalsession",
        "assembly.historicalsessionitem",
        "employees.historicalholidaycalendar",
        "employees.historicalemployee",
        "employees.historicalemployeeleaveyear",
        "employees.historicalemploymentdocument",
        "employees.historicaltimesheet",
        "employees.historicaltimeentry",
        "finances.historicalfiscalyear",
        "finances.historicalpaymentplan",
        "hankosign.historicalaction",
        "hankosign.historicalpolicy",
        "hankosign.historicalsignatory",
        "hankosign.historicalsignature",
        "helppages.historicalhelppage",
        "organisation.historicalorginfo",
        "people.historicalperson",
        "people.historicalrole",
        "people.historicalpersonrole",
        "people.historicalroletransitionreason",
    ],

    # Quality of life
    "related_modal_active": True,
    "changeform_format": "collapsible",
    #"changeform_format_overrides": {},
    "language_chooser": True,

    # Custom assets
    "custom_css": "admin/unihanko_neobrutalist_theme.css",
    "custom_js": "admin/custom.js",

    # UI builder
    "show_ui_builder": False,
}

JAZZMIN_UI_TWEAKS = {
    # Theme
    "theme": "darkly",
    "dark_mode_theme": "darkly",

    # Navbar styling
    "navbar": "navbar-dark",
    "no_navbar_border": True,
    "navbar_fixed": False,
    
    # Brand/Logo
    "brand_small_text": False,
    "brand_colour": False,
    
    # Text sizes
    "navbar_small_text": False,
    "footer_small_text": True,
    "body_small_text": False,
    
    # Layout
    "layout_boxed": False,
    "footer_fixed": True,
    "sidebar_fixed": True,
    "navigation_expanded": False,
    
    # Sidebar
    "accent": "accent-orange",
    "sidebar": "sidebar-dark-orange",
    "sidebar_nav_small_text": True,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    
    # Buttons - these work with the theme
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-outline-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    },
    
    # Actions
    "actions_sticky_top": True
}