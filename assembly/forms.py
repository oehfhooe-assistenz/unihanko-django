from django import forms
from django.utils.translation import gettext_lazy as _
from tinymce.widgets import TinyMCE

from .models import SessionItem


class SessionItemProtocolForm(forms.ModelForm):
    """
    Form for protocol editor with conditional fields based on kind.
    
    Field visibility is handled client-side with Alpine.js based on kind selection.
    """
    
    class Meta:
        model = SessionItem
        fields = [
            'kind', 'title', 'order',
            # PROCEDURAL fields
            'content',
            # RESOLUTION/ELECTION fields
            'subject', 'discussion', 'outcome',
            # Voting fields (RESOLUTION only)
            'voting_mode', 'votes_for', 'votes_against', 'votes_abstain', 'passed',
            # Election fields (ELECTION only)
            'elected_person_role', 'elected_person_text_reference', 'elected_role_text_reference',
            # Notes
            'notes'
        ]
        widgets = {
            'kind': forms.Select(attrs={
                'class': 'protokol-select',
                'x-model': 'currentKind',
                '@change': 'updateFieldVisibility()'
            }),
            'title': forms.TextInput(attrs={
                'class': 'protokol-input',
                'placeholder': _('Item title')
            }),
            'order': forms.NumberInput(attrs={
                'class': 'protokol-input',
                'placeholder': _('Order')
            }),
            # PROCEDURAL
            'content': forms.Textarea(attrs={
                'class': 'protokol-textarea',
                'rows': 6,
                'placeholder': _('Procedural content')
            }),
            # RESOLUTION/ELECTION
            'subject': TinyMCE(attrs={'class': 'protokol-tinymce'}),
            'discussion': TinyMCE(attrs={'class': 'protokol-tinymce'}),
            'outcome': TinyMCE(attrs={'class': 'protokol-tinymce'}),
            # Voting
            'voting_mode': forms.Select(attrs={'class': 'protokol-select'}),
            'votes_for': forms.NumberInput(attrs={'class': 'protokol-input'}),
            'votes_against': forms.NumberInput(attrs={'class': 'protokol-input'}),
            'votes_abstain': forms.NumberInput(attrs={'class': 'protokol-input'}),
            'passed': forms.CheckboxInput(attrs={'class': 'protokol-checkbox'}),
            # Election
            'elected_person_text_reference': forms.TextInput(attrs={
                'class': 'protokol-input',
                'placeholder': _('Elected person (temp reference)')
            }),
            'elected_role_text_reference': forms.TextInput(attrs={
                'class': 'protokol-input',
                'placeholder': _('Elected role (temp reference)')
            }),
            # Notes
            'notes': forms.Textarea(attrs={
                'class': 'protokol-textarea',
                'rows': 3,
                'placeholder': _('Internal notes')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set labels
        self.fields['kind'].label = _("Kind")
        self.fields['title'].label = _("Title")
        self.fields['order'].label = _("Order")
        self.fields['content'].label = _("Content")
        self.fields['subject'].label = _("Subject")
        self.fields['discussion'].label = _("Discussion")
        self.fields['outcome'].label = _("Outcome")
        self.fields['voting_mode'].label = _("Voting Mode")
        self.fields['votes_for'].label = _("Votes For")
        self.fields['votes_against'].label = _("Votes Against")
        self.fields['votes_abstain'].label = _("Abstentions")
        self.fields['passed'].label = _("Passed")
        self.fields['elected_person_role'].label = _("Elected Person (from system)")
        self.fields['elected_person_text_reference'].label = _("Elected Person (temp)")
        self.fields['elected_role_text_reference'].label = _("Elected Role (temp)")
        self.fields['notes'].label = _("Notes")
        
        # Make certain fields not required (conditional based on kind)
        self.fields['content'].required = False
        self.fields['subject'].required = False
        self.fields['discussion'].required = False
        self.fields['outcome'].required = False
        self.fields['voting_mode'].required = False
        self.fields['votes_for'].required = False
        self.fields['votes_against'].required = False
        self.fields['votes_abstain'].required = False
        self.fields['passed'].required = False
        self.fields['elected_person_role'].required = False
        self.fields['elected_person_text_reference'].required = False
        self.fields['elected_role_text_reference'].required = False
        self.fields['notes'].required = False