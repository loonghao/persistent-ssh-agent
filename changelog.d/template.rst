{% for section, _ in sections.items() %}
{% if section %}### {{ section }}

{% endif %}
{% if sections[section] %}
{% for category, val in definitions.items() if category in sections[section] %}

#### {{ definitions[category]['name'] }}

{% for text, values in sections[section][category].items() %}
* {{ text }} {{ values|join(', ') }}
{% endfor %}
{% endfor %}
{% else %}
No significant changes.

{% endif %}
{% endfor %}
