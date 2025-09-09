# core/management/commands/bootstrap_admin_help.py
from __future__ import annotations

import os
from typing import Any, Dict

from django.contrib import admin
from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.utils.text import capfirst

# YAML is optional; only needed if --file is used.
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def default_title(model) -> str:
    return f"{capfirst(model._meta.verbose_name)} — How to"


def default_content(model) -> str:
    vn = capfirst(model._meta.verbose_name)
    return (
        f"# {vn}\n\n"
        "TBA\n\n"
        "## Typical workflow\n"
        "1. Add\n"
        "2. Edit\n"
        "3. Export / PDF\n\n"
        "## Notes\n"
        "- Prefer archiving over deleting (where available).\n"
    )


def load_yaml(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if yaml is None:
        raise RuntimeError("PyYAML is not installed. Run `pip install pyyaml` or omit --file.")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


class Command(BaseCommand):
    help = "Create/update FlatPages for admin help (/admin/help/<app>/<model>/) from the admin registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            dest="file",
            default=None,
            help="Optional YAML with titles/content (e.g., config/admin_help.yaml).",
        )
        parser.add_argument(
            "--update",
            dest="update",
            action="store_true",
            help="Update title/content even if a page already exists.",
        )
        parser.add_argument(
            "--prune",
            dest="prune",
            action="store_true",
            help="Delete help FlatPages for models no longer registered in admin.",
        )
        parser.add_argument(
            "--set-template",
            dest="set_template",
            action="store_true",
            help="Set FlatPage.template_name to 'admin/help_flatpage.html'.",
        )

    def handle(self, *args, **opts):
        cfg = {}
        try:
            cfg = load_yaml(opts.get("file"))
        except Exception as e:
            self.stderr.write(self.style.WARNING(f"YAML skipped: {e}"))
            cfg = {}

        models_cfg: Dict[str, Any] = (cfg.get("models") or {}) if isinstance(cfg, dict) else {}
        index_cfg: Dict[str, Any] = (cfg.get("index") or {}) if isinstance(cfg, dict) else {}

        update_flag = bool(opts.get("update"))
        prune_flag = bool(opts.get("prune"))
        set_template_flag = bool(opts.get("set_template"))

        site = Site.objects.get_current()

        # 1) Ensure general index
        index_url = "/admin/help/"
        index_title = (index_cfg.get("title") if isinstance(index_cfg, dict) else None) or "Admin Help"
        index_content = (index_cfg.get("content") if isinstance(index_cfg, dict) else None) or "TBA"
        self._ensure_flatpage(
            url=index_url,
            site=site,
            title=index_title,
            content=index_content,
            update=update_flag,
            set_template=set_template_flag,
        )
        self.stdout.write(self.style.SUCCESS(f"Ensured {index_url}"))

        # 2) Per-model pages for everything in the admin registry
        registry = admin.site._registry  # {Model: ModelAdmin}
        wanted_urls = set()

        for model in sorted(registry.keys(), key=lambda m: (m._meta.app_label, m._meta.model_name)):
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            key = f"{app_label}.{model_name}"
            url = f"/admin/help/{app_label}/{model_name}/"
            wanted_urls.add(url)

            ycfg: Dict[str, Any] = models_cfg.get(key, {}) if isinstance(models_cfg, dict) else {}
            title = (ycfg.get("title") if isinstance(ycfg, dict) else None) or default_title(model)
            content = (ycfg.get("content") if isinstance(ycfg, dict) else None) or default_content(model)

            self._ensure_flatpage(
                url=url,
                site=site,
                title=title,
                content=content,
                update=update_flag,
                set_template=set_template_flag,
            )
            self.stdout.write(self.style.SUCCESS(f"Ensured {url}"))

        # 3) Optional prune
        if prune_flag:
            stale_qs = (
                FlatPage.objects.filter(url__startswith="/admin/help/")
                .exclude(url=index_url)
            )
            removed = 0
            for fp in stale_qs:
                if fp.url not in wanted_urls:
                    fp.delete()
                    removed += 1
            self.stdout.write(self.style.WARNING(f"Pruned {removed} stale help page(s)."))

        self.stdout.write(self.style.SUCCESS("Done."))

    # --- helpers -------------------------------------------------------------

    def _ensure_flatpage(
        self,
        *,
        url: str,
        site: Site,
        title: str,
        content: str,
        update: bool,
        set_template: bool,
    ) -> FlatPage:
        fp, created = FlatPage.objects.get_or_create(
            url=url,
            defaults={"title": title, "content": content},
        )
        # attach to current site
        if not fp.sites.filter(pk=site.pk).exists():
            fp.sites.add(site)

        # set template if requested
        if set_template and fp.template_name != "admin/help_flatpage.html":
            fp.template_name = "admin/help_flatpage.html"

        # update title/content if requested and not freshly created
        if update and not created:
            fp.title = title
            fp.content = content

        fp.save()
        return fp
