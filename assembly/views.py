# In your views.py
from django.http import HttpResponse
from django.template.loader import render_to_string

def session_item_fields(request):
    kind = request.GET.get('kind', '')
    
    fields_html = ""
    if kind == 'PROC':
        fields_html = '<div class="form-group field-content"><label>Content:</label><textarea name="content" class="form-control"></textarea></div>'
    elif kind == 'RES':
        fields_html = '''
        <div class="form-group field-subject"><label>Subject:</label><textarea name="subject" class="form-control"></textarea></div>
        <div class="form-group field-discussion"><label>Discussion:</label><textarea name="discussion" class="form-control"></textarea></div>
        <div class="form-group field-outcome"><label>Outcome:</label><textarea name="outcome" class="form-control"></textarea></div>
        <div class="form-group field-voting_mode"><label>Voting Mode:</label><select name="voting_mode" class="form-control"><option value="NONE">No voting</option><option value="COUNT">Counted</option><option value="NAMED">Named</option></select></div>
        '''
    elif kind == 'ELEC':
        fields_html = '''
        <div class="form-group field-subject"><label>Subject:</label><textarea name="subject" class="form-control"></textarea></div>
        <div class="form-group field-discussion"><label>Discussion:</label><textarea name="discussion" class="form-control"></textarea></div>
        <div class="form-group field-outcome"><label>Outcome:</label><textarea name="outcome" class="form-control"></textarea></div>
        <div class="form-group field-voting_mode"><label>Voting Mode:</label><select name="voting_mode" class="form-control"><option value="NONE">No voting</option><option value="COUNT">Counted</option><option value="NAMED">Named</option></select></div>
        <div class="form-group field-elected_person_role"><label>Elected Person:</label><select name="elected_person_role" class="form-control"></select></div>
        '''
    
    return HttpResponse(fields_html)