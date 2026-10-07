from decimal import Decimal

from django import forms

from .models import PriceAlert


def _location_choices(locations, blank_label=None):
    choices = [(loc, loc) for loc in locations]
    if blank_label:
        choices.insert(0, ("", blank_label))
    return choices


class SignupForm(forms.Form):
    name = forms.CharField(label="Your name", max_length=120)
    email = forms.EmailField(
        label="Email address",
        error_messages={"invalid": "Please type a full email address, like juan@gmail.com."},
    )
    password = forms.CharField(
        label="Create a password",
        min_length=8,
        widget=forms.PasswordInput(render_value=False),
        help_text="At least 8 letters or numbers.",
        error_messages={"min_length": "Your password needs at least 8 letters or numbers."},
    )
    location = forms.ChoiceField(label="Where do you usually sell?")

    def __init__(self, *args, locations=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].choices = _location_choices(locations, "Choose your province")


class LoginForm(forms.Form):
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", widget=forms.PasswordInput)


class ProfileForm(forms.Form):
    name = forms.CharField(label="Your name", max_length=120)
    email = forms.EmailField(label="Email address")
    location = forms.ChoiceField(label="Where do you usually sell?")
    new_password = forms.CharField(
        label="New password (optional)",
        required=False,
        min_length=8,
        widget=forms.PasswordInput,
        help_text="Leave this empty to keep your current password.",
        error_messages={"min_length": "Your password needs at least 8 letters or numbers."},
    )

    def __init__(self, *args, locations=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].choices = _location_choices(locations)


class PriceAlertForm(forms.Form):
    crop = forms.ChoiceField(
        label="What crop do you want to monitor?",
        widget=forms.RadioSelect,
        error_messages={"required": "Please choose a crop."},
    )
    target_price = forms.DecimalField(
        label="What price are you watching for?",
        min_value=Decimal("0.01"),
        max_value=Decimal("10000"),
        decimal_places=2,
        error_messages={
            "required": "Please type a price.",
            "invalid": "Please type a number, like 40 or 22.50.",
            "min_value": "The price must be more than ₱0.",
            "max_value": "That price looks too high. Please check it.",
            "max_decimal_places": "Please use at most 2 decimal places, like 22.50.",
        },
    )
    condition = forms.ChoiceField(
        label="When should we notify you?",
        widget=forms.RadioSelect,
        choices=[
            (PriceAlert.ABOVE, "When the price goes above my target"),
            (PriceAlert.BELOW, "When the price goes below my target"),
        ],
        error_messages={"required": "Please choose when we should notify you."},
    )

    def __init__(self, *args, crops=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crop"].choices = [(c.slug, c.name) for c in crops]
