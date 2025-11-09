JAZZMIN_SETTINGS = {
    # Branding
    "site_title": "UniHanko Back Office",
    "site_header": "UniHanko Administration",
    "site_brand": "UniHanko",
    "welcome_sign": "Welcome to UniHanko Back Office",
    "site_logo": "img/unihanko-logo.svg",            # put these under STATIC
    "login_logo": "img/unihanko-mark.svg",           # optional second logo for login
    "site_logo_classes": "img-fluid",

    # Quick nav
    "topmenu_links": [
        {"name": "Cockpit (Beta)", "url": "/admin/cockpit/", "permissions": ["is_staff"]},
        {"name": "Onboarding",  "url": "/admin/people/personrole/add/", "permissions": ["people.add_personrole"]},
        {"name": "Offboarding", "url": "/admin/people/personrole/?active=1", "permissions": ["people.change_personrole"]},
        {"name": "Fiscal Years", "url": "/admin/finances/fiscalyear/", "permissions": ["finances.view_fiscalyear"]},
        {"name": "Add Fiscal Year", "url": "/admin/finances/fiscalyear/add/", "permissions": ["finances.add_fiscalyear"]},
        # examples you can add later:
        # {"app": "people"},                               # jump to the Personnel section
        # {"name": "Public site", "url": "/", "new_window": True},
    ],
    "usermenu_links": [
        # {"model": "auth.user"},                         # profile
        # {"name": "Help", "url": "https://…", "new_window": True},
    ],

    # Icons (Font Awesome 5/6)
    "icons": {
        "organisation.orginfo": "fa-solid fa-building-ngo",
        "people": "fa-solid fa-users-gear",
        "people.person": "fa-solid fa-user",
        "people.personrole": "fa-solid fa-user-check",
        "people.role": "fa-solid fa-id-badge",
        "people.roletransitionreason": "fa-solid fa-flag",
        "finances": "fa-solid fa-calculator",
        "finances.fiscalyear": "fa-solid fa-calendar-check",
        "finances.paymentplan": "fa-solid fa-money-check-dollar",
        "employees": "fa-solid fa-address-book",
        "employees.employee": "fa-solid fa-address-book",
        "employees.employmentdocument": "fa-solid fa-passport",
        "employees.timesheet": "fa-solid fa-business-time",
        "employees.timeentry": "fa-solid fa-calendar-xmark",
        "employees.holidaycalendar": "fa-solid fa-gift",
        "hankosign":"fa-solid fa-key",
        "hankosign.action":"fa-solid fa-layer-group",
        "hankosign.policy":"fa-solid fa-pen-nib",
        "hankosign.signatory":"fa-solid fa-fingerprint",
        "hankosign.signature":"fa-solid fa-receipt",
        "helppages": "fa-solid fa-circle-info",
        "helppages.helppage": "fa-solid fa-note-sticky",
    },

    # Sidebar ordering within the app
    "order_with_respect_to": ["organisation", "organisation.orginfo", "people", "people.personrole", "people.person", "people.roletransitionreason", "people.role", "finances", "finances.paymentplan", "finances.fiscalyear", "employees", "employees.timesheet", "employees.employmentdocument", "employees.employee", "employees.holidaycalendar", "hankosign", "hankosign.signatory", "hankosign.policy", "hankosign.action", "helppages", "helppages.helppage", "assembly", "assembly.session", "assembly.composition", "assembly.term",],


    # Hide historical models from menu
    "hide_models": [
        "organisation.HistoricalOrgInfo",
        "people.HistoricalPerson",
        "people.HistoricalRole",
        "people.HistoricalPersonRole",
        "people.HistoricalRoleTransitionReason",
        "finances.HistoricalFiscalYear",
        "finances.HistoricalPaymentPlan",
        "hankosign.Signature",
        "employees.HistoricalEmployee",
        "employees.HistoricalEmploymentDocument",
        "employees.HistoricalHolidayCalendar",
        "employees.HistoricalTimeSheet",
        "employees.HistoricalTimeEntry",
        "hankosign.HistoricalAction",
        "hankosign.HistoricalPolicy",
        "hankosign.HistoricalSignatory",
        "hankosign.HistoricalSignature",
        "helppages.HistoricalHelpPage",
        "assembly.HistoricalMandate",
        "assembly.HistoricalTerm",
        "assembly.HistoricalSessionItem",
        "assembly.HistoricalSession",
        "assembly.HistoricalComposition",
    ],

    # Quality of life
    "related_modal_active": True,                    # add related objects in a modal
    "changeform_format": "collapsible",            # or "horizontal_tabs" / "collapsible"
    "changeform_format_overrides": {
        "finances.paymentplan": "single",
        "organisation.orginfo": "single",
    },
    "language_chooser": True,                       # header language switcher

    # Custom assets
    # "custom_css": "admin/unihanko.css",
    "custom_css": "admin/uh_new.css",
    "custom_js": "admin/custom.js",

    # Optional: show Jazzmin UI builder (handy for experimenting)
    "show_ui_builder": True,
}

JAZZMIN_UI_TWEAKS = {
    # Bootswatch theme names: flatly, simplex, cosmo, lumen, slate, darkly, etc.
    "theme": "flatly",
    "dark_mode_theme": "darkly",

    # Navbar / sidebar styling
    "navbar": "navbar-light",
    "no_navbar_border": True,
    "brand_small_text": False,
    "navbar_small_text": False,
    "footer_small_text": True,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-orange",
    "navbar": "navbar-orange navbar-light",
    "no_navbar_border": True,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": True,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-orange",
    "sidebar_nav_small_text": True,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-outline-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    },
    "actions_sticky_top": True
}