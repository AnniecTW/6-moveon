from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm

from .auth_backend import has_campus_access
from .models import User


class CampusAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Please enter a correct username or campus email and password.",
        "inactive": "This account is inactive.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username or campus email"
        self.fields["username"].max_length = 254
        self.fields["username"].widget.attrs.update(
            {"placeholder": "Username or you@illinois.edu", "autocomplete": "username", "maxlength": 254}
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Your password", "autocomplete": "current-password"}
        )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not has_campus_access(user):
            raise forms.ValidationError(
                "This account does not have verified campus access."
            )


class ListingSignupForm(UserCreationForm):
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={"placeholder": "you@illinois.edu", "autocomplete": "email"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "choose_a_unique_username", "autocomplete": "username"}
        )
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "Create a password", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Repeat your password", "autocomplete": "new-password"}
        )

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(email__iexact=username).exists():
            raise forms.ValidationError("This username is already used as a campus email.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.endswith("@illinois.edu"):
            raise forms.ValidationError("Use an @illinois.edu email address.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("This email is already used as a username.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.display_name = user.username
        if commit:
            user.save()
        return user
