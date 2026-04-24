"""
apps/audit/templatetags/audit_tags.py

custom template tag: {% url_replace key=value %}

replaces (or adds) a single query-string parameter while preserving all
other parameters.  used by the system logs pagination controls so that
page links preserve the current filter state.

usage:
    <a href="?{% url_replace page=page_obj.next_page_number %}">next</a>
"""

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """return the current query string with the given key(s) replaced/added."""
    request = context.get('request')
    if request is None:
        # fallback: just build a simple query string from kwargs
        return '&'.join(f'{k}={v}' for k, v in kwargs.items())

    params = request.GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()
