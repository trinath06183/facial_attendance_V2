"""
apps/audit/templatetags/audit_tags.py
──────────────────────────────────────
Custom template tag: {% url_replace key=value %}

Replaces (or adds) a single query-string parameter while preserving all
other parameters.  Used by the System Logs pagination controls so that
page links preserve the current filter state.

Usage:
    <a href="?{% url_replace page=page_obj.next_page_number %}">Next</a>
"""

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Return the current query string with the given key(s) replaced/added."""
    request = context.get('request')
    if request is None:
        # Fallback: just build a simple query string from kwargs
        return '&'.join(f'{k}={v}' for k, v in kwargs.items())

    params = request.GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()
