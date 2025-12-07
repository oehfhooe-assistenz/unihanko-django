"""
Sync HankoSign Actions from a YAML file (idempotent).

Usage:
  python manage.py bootstrap_actions --dry-run
  python manage.py bootstrap_actions
  python manage.py bootstrap_actions --file /custom/actions.yaml
"""
# File: hankosign/management/commands/bootstrap_actions.py
# Version: 1.0.2
# Author: vas
# Modified: 2025-12-06

from pathlib import Path
from typing import Dict, List

import yaml
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from hankosign.models import Action

def get_fixture_path(filename, *, sensitive=False):
    """
    Resolve fixture file location.
    
    - Non-sensitive: always from repo fixtures/
    - Sensitive: from mount in prod, repo in DEBUG
    """
    if sensitive and not settings.DEBUG:
        # Production: sensitive files ONLY from mount
        return settings.BOOTSTRAP_DATA_DIR / filename
    else:
        # Dev OR non-sensitive: use repo fixtures
        return Path(__file__).parent.parent.parent / "fixtures" / filename


def get_model(label: str):
    """
    'people.Person' -> model class
    """
    try:
        app_label, model_name = label.split(".", 1)
    except ValueError:
        raise CommandError(f"Invalid model label '{label}'. Use 'app_label.ModelName'.")
    
    model = apps.get_model(app_label, model_name)
    if not model:
        raise CommandError(f"Model not found: {label}")
    return model


class Command(BaseCommand):
    help = "Create/refresh HankoSign Actions from a YAML file (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            default=None,
            help="Path to YAML file (default: auto-resolved from fixtures)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without applying them.",
        )

    def handle(self, *args, **opts):
        file_path = opts["file"]
        if not file_path:
            file_path = get_fixture_path("hankosign_actions.yaml", sensitive=False)
        else:
            file_path = Path(file_path)
        
        dry = opts["dry_run"]

        if not file_path.exists():
            raise CommandError(f"YAML file not found: {file_path}")

        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        actions_cfg: List[Dict] = data.get("actions", []) or []

        if not actions_cfg:
            self.stdout.write(self.style.WARNING("No actions defined. Nothing to do."))
            return

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for action_def in actions_cfg:
            verb = action_def.get("verb")
            stage = action_def.get("stage", "")
            scope_label = action_def.get("scope")
            human_label = action_def.get("human_label")
            comment = action_def.get("comment", "")
            is_repeatable = action_def.get("is_repeatable", False)
            require_distinct_signer = action_def.get("require_distinct_signer", False)

            # Validate required fields
            if not verb:
                raise CommandError(f"Missing 'verb' in action definition: {action_def}")
            if not scope_label:
                raise CommandError(f"Missing 'scope' in action definition: {action_def}")
            if not human_label:
                raise CommandError(f"Missing 'human_label' in action definition: {action_def}")

            # Get model and ContentType
            model = get_model(scope_label)
            scope_ct = ContentType.objects.get_for_model(model)

            # Check if action exists
            try:
                action = Action.objects.get(verb=verb, stage=stage, scope=scope_ct)
                
                # Check if update needed
                needs_update = False
                updates = {}
                
                if action.human_label != human_label:
                    updates['human_label'] = human_label
                    needs_update = True
                
                if action.comment != comment:
                    updates['comment'] = comment
                    needs_update = True
                
                if action.is_repeatable != is_repeatable:
                    updates['is_repeatable'] = is_repeatable
                    needs_update = True
                
                if action.require_distinct_signer != require_distinct_signer:
                    updates['require_distinct_signer'] = require_distinct_signer
                    needs_update = True
                
                if needs_update:
                    if dry:
                        self.stdout.write(
                            self.style.NOTICE(
                                f"[DRY] Update: {action.action_code} | Changes: {', '.join(updates.keys())}"
                            )
                        )
                    else:
                        for field, value in updates.items():
                            setattr(action, field, value)
                        action.save()
                        self.stdout.write(
                            self.style.SUCCESS(f"Updated: {action.action_code}")
                        )
                    updated_count += 1
                else:
                    unchanged_count += 1
                    
            except Action.DoesNotExist:
                # Create new action
                if dry:
                    action_code = f"{verb}:{stage or '-'}@{scope_ct.app_label}.{scope_ct.model}"
                    self.stdout.write(
                        self.style.NOTICE(f"[DRY] Create: {action_code} — {human_label}")
                    )
                else:
                    action = Action.objects.create(
                        verb=verb,
                        stage=stage,
                        scope=scope_ct,
                        human_label=human_label,
                        comment=comment,
                        is_repeatable=is_repeatable,
                        require_distinct_signer=require_distinct_signer,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"Created: {action.action_code} — {human_label}")
                    )
                created_count += 1

        # Summary
        summary = []
        if created_count:
            summary.append(f"{created_count} created")
        if updated_count:
            summary.append(f"{updated_count} updated")
        if unchanged_count:
            summary.append(f"{unchanged_count} unchanged")
        
        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. {', '.join(summary)}. No changes applied."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Bootstrap complete! {', '.join(summary)}."
                )
            )