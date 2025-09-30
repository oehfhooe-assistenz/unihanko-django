from __future__ import annotations
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext as _t
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from solo.models import SingletonModel
from simple_history.models import HistoricalRecords

# FK to your assignments
from people.models import PersonRole


def _iban_checksum_ok(iban: str) -> bool:
    """Mod-97 per ISO 13616."""
    if not iban or len(iban) < 4:
        return False
    s = (iban[4:] + iban[:4]).upper()
    digits = "".join(str(ord(c) - 55) if "A" <= c <= "Z" else c for c in s)
    rem = 0
    for ch in digits:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1


class OrgInfo(SingletonModel):
    # --- Names (DE/EN long + short) ----------------------------------------
    org_name_long_de   = models.CharField(_("Org name (DE, long)"),  max_length=200, blank=True)
    org_name_short_de  = models.CharField(_("Org name (DE, short)"), max_length=80,  blank=True)
    org_name_long_en   = models.CharField(_("Org name (EN, long)"),  max_length=200, blank=True)
    org_name_short_en  = models.CharField(_("Org name (EN, short)"), max_length=80,  blank=True)

    uni_name_long_de   = models.CharField(_("University (DE, long)"),  max_length=200, blank=True)
    uni_name_short_de  = models.CharField(_("University (DE, short)"), max_length=120, blank=True)
    uni_name_long_en   = models.CharField(_("University (EN, long)"),  max_length=200, blank=True)
    uni_name_short_en  = models.CharField(_("University (EN, short)"), max_length=120, blank=True)

    # --- Addresses ---------------------------------------------------------
    org_address  = models.TextField(_("Organisation address"), blank=True, help_text=_("Multiline; used in PDFs/letters."))
    bank_address = models.TextField(_("Bank address"), blank=True)

    # --- Bank & Tax --------------------------------------------------------
    IBAN_SHAPE = r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$"
    BIC_SHAPE  = r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$"

    bank_name = models.CharField(_("Bank name"), max_length=120, blank=True)
    bank_iban = models.CharField(
        _("Bank IBAN"),
        max_length=34,
        blank=True,
        validators=[RegexValidator(IBAN_SHAPE, _("Enter a valid IBAN (e.g. AT.., DE..)."))],
    )
    bank_bic  = models.CharField(
        _("Bank BIC"),
        max_length=11,
        blank=True,
        validators=[RegexValidator(BIC_SHAPE, _("Enter a valid BIC (8 or 11 chars)."))],
    )
    org_tax_id = models.CharField(_("VAT/Tax ID"), max_length=40, blank=True)

    # Optional: default reference label used for new payment plans
    default_reference_label = models.CharField(
        _("Default reference label"),
        max_length=80,
        blank=True,
        help_text=_('Used as a default in forms/CSV (e.g. "Rechnung").'),
    )

    # --- Legal signatories (PersonRole FKs) --------------------------------
    org_chair       = models.ForeignKey(
        PersonRole, verbose_name=_("Chair"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    org_dty_chair1  = models.ForeignKey(
        PersonRole, verbose_name=_("1st Deputy Chair"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    org_dty_chair2  = models.ForeignKey(
        PersonRole, verbose_name=_("2nd Deputy Chair"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    org_dty_chair3  = models.ForeignKey(
        PersonRole, verbose_name=_("3rd Deputy Chair"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    org_wiref       = models.ForeignKey(
        PersonRole, verbose_name=_("Financial Officer (WiRef)"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    org_dty_wiref   = models.ForeignKey(
        PersonRole, verbose_name=_("Deputy Financial Officer"), on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    org_public_filing_url = models.CharField(_("Public filing URL"), max_length=128, blank=True, help_text=_("Do not change without permission."))

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Master data")
        verbose_name_plural = _("Master data")

    def __str__(self) -> str:
        # What appears in the admin title bar
        return self.org_name_short_de or self.org_name_short_en or _t("Organisation settings")

    # Normalize & validate bank fields
    def clean(self):
        # Normalize IBAN/BIC if present
        if self.bank_iban:
            self.bank_iban = self.bank_iban.replace(" ", "").upper()
            if not _iban_checksum_ok(self.bank_iban):
                raise ValidationError({"bank_iban": _("IBAN checksum failed.")})
        if self.bank_bic:
            self.bank_bic = self.bank_bic.replace(" ", "").upper()

    # Convenient accessor for code that needs it:
    @classmethod
    def get(cls) -> "OrgInfo":
        return cls.get_solo()
