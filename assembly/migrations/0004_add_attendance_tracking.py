from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('assembly', '0003_remove_composition_notes_and_more'),  # ← Your actual last migration
    ]

    operations = [
        # Step 1: Create the through model
        migrations.CreateModel(
            name='SessionAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('backup_attended', models.BooleanField(default=False, help_text='Check if backup person attended instead of primary mandatary', verbose_name='Backup Attended')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('mandate', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='assembly.mandate', verbose_name='Mandate')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to='assembly.session', verbose_name='Session')),
            ],
            options={
                'verbose_name': 'Session Attendance',
                'verbose_name_plural': 'Session Attendances',
                'ordering': ['mandate__position'],
            },
        ),
        
        # Step 2: Copy existing data to through model
        migrations.RunPython(
            code=lambda apps, schema_editor: migrate_attendance_forward(apps, schema_editor),
            reverse_code=lambda apps, schema_editor: None,
        ),
        
        # Step 3: Remove old M2M field
        migrations.RemoveField(
            model_name='session',
            name='attendees',
        ),
        
        # Step 4: Add new M2M field with through
        migrations.AddField(
            model_name='session',
            name='attendees',
            field=models.ManyToManyField(
                related_name='attended_sessions',
                through='assembly.SessionAttendance',
                to='assembly.mandate',
                verbose_name='Attendees'
            ),
        ),
        
        # Step 5: Add unique constraint
        migrations.AddConstraint(
            model_name='sessionattendance',
            constraint=models.UniqueConstraint(fields=('session', 'mandate'), name='assembly_sessionattendance_unique_session_mandate'),
        ),
    ]


def migrate_attendance_forward(apps, schema_editor):
    """Copy existing attendee data to SessionAttendance"""
    Session = apps.get_model('assembly', 'Session')
    SessionAttendance = apps.get_model('assembly', 'SessionAttendance')
    
    # Get the through table data before we delete the M2M
    db_alias = schema_editor.connection.alias
    
    # Read existing M2M relationships
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT session_id, mandate_id 
            FROM assembly_session_attendees
        """)
        
        for session_id, mandate_id in cursor.fetchall():
            SessionAttendance.objects.using(db_alias).create(
                session_id=session_id,
                mandate_id=mandate_id,
                backup_attended=False  # Default to primary
            )