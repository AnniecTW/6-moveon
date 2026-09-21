from django import forms

from .models import Bundle
from .space_categories import available_item_types_for_space


class SpaceSelectForm(forms.Form):
    """Screen 1: pick the space being furnished. There's no AI-vs-manual
    shopping choice here - manual browsing isn't built, so this only ever
    covers the AI-assisted path (see decision recorded in the bundle-builder
    plan)."""

    space = forms.ChoiceField(choices=Bundle.Space.choices, widget=forms.RadioSelect)


class CategorySelectForm(forms.Form):
    """Screen 2: pick one or more requested item types for the chosen
    space. Only currently-available item types (status=ACTIVE,
    bundle_eligible=True listings exist) are valid choices - the template
    separately renders unavailable ones as greyed-out/disabled tiles."""

    categories = forms.MultipleChoiceField(
        choices=(), widget=forms.CheckboxSelectMultiple, required=True
    )

    def __init__(self, *args, space=None, **kwargs):
        super().__init__(*args, **kwargs)
        pairs = available_item_types_for_space(space)
        self.available_pairs = pairs
        self.fields["categories"].choices = [
            (item_type.id, item_type.item_type_name)
            for item_type, is_available in pairs
            if is_available
        ]
