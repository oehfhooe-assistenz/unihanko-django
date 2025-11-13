function toggleSessionItemFields(selectElement) {
    var fieldset = selectElement.closest('fieldset');
    if (!fieldset) return;
    
    var content = fieldset.querySelector('.field-content');
    var subject = fieldset.querySelector('.field-subject');
    var discussion = fieldset.querySelector('.field-discussion');
    var outcome = fieldset.querySelector('.field-outcome');
    var votingMode = fieldset.querySelector('.field-voting_mode');
    var votesFor = fieldset.querySelector('.field-votes_for');
    var votesAgainst = fieldset.querySelector('.field-votes_against');
    var votesAbstain = fieldset.querySelector('.field-votes_abstain');
    var passed = fieldset.querySelector('.field-passed');
    var electedPerson = fieldset.querySelector('.field-elected_person_role');
    var electedPersonText = fieldset.querySelector('.field-elected_person_text_reference');
    var electedRoleText = fieldset.querySelector('.field-elected_role_text_reference');
    
    // Hide everything first
    [content, subject, discussion, outcome, votingMode, votesFor, votesAgainst, votesAbstain, passed, electedPerson, electedPersonText, electedRoleText].forEach(function(field) {
        if (field) field.style.display = 'none';
    });
    
    var kind = selectElement.value;
    
    if (kind === 'PROC') {
        if (content) content.style.display = 'block';
    } else if (kind === 'RES') {
        [subject, discussion, outcome, votingMode, votesFor, votesAgainst, votesAbstain, passed].forEach(function(field) {
            if (field) field.style.display = 'block';
        });
    } else if (kind === 'ELEC') {
        [subject, discussion, outcome, votingMode, votesFor, votesAgainst, votesAbstain, passed, electedPerson, electedPersonText, electedRoleText].forEach(function(field) {
            if (field) field.style.display = 'block';
        });
    }
    // If no value selected, show all fields (for new forms)
    else if (!kind) {
        [content, subject, discussion, outcome, votingMode, votesFor, votesAgainst, votesAbstain, passed, electedPerson, electedPersonText, electedRoleText].forEach(function(field) {
            if (field) field.style.display = 'block';
        });
    }
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('SessionItem admin JS loaded');
    
    // Set up ALL kind selects, including empty ones
    function setupKindSelects() {
        document.querySelectorAll('select[name*="kind"]').forEach(function(select) {
            // Skip the Django template form
            if (select.name.includes('__prefix__')) return;
            
            console.log('Setting up select:', select.name, 'value:', select.value);
            
            // Remove any existing event listeners to avoid duplicates
            select.onchange = null;
            
            // Add the event listener
            select.addEventListener('change', function() {
                console.log('Kind changed:', this.value);
                toggleSessionItemFields(this);
            });
            
            // Run initial setup
            toggleSessionItemFields(select);
        });
    }
    
    // Initial setup
    setupKindSelects();
    
    // Handle when new inline forms are added (when user clicks "Add another")
    document.addEventListener('click', function(e) {
        if (e.target.textContent && e.target.textContent.includes('Add another Session Item')) {
            // Wait a bit for the form to be added to the DOM
            setTimeout(setupKindSelects, 100);
        }
    });
});