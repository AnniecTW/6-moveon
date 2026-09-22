from django.http import HttpResponse
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.template import loader
from django.views import View
from django.views.generic import ListView
from django.views.decorators.http import require_POST
from .auth_forms import ListingSignupForm
from .models import Listing
from .browse import browse_context


def account_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    mode = request.POST.get("mode") if request.method == "POST" else request.GET.get("mode")
    mode = "signup" if mode == "signup" else "login"
    data = request.POST if request.method == "POST" else None
    form = (
        ListingSignupForm(data)
        if mode == "signup"
        else AuthenticationForm(request, data=data)
    )
    if request.method == "POST" and form.is_valid():
        user = form.save() if mode == "signup" else form.get_user()
        login(request, user)
        return redirect("home")

    context = browse_context(request)
    context.update({"auth_form": form, "auth_mode": mode})
    return render(request, "marketplace/account.html", context)


@require_POST
def account_logout_view(request):
    logout(request)
    return redirect("home")


# 1. FBV (Manual HttpResponse)
def listing_manual_view(request):
    template = loader.get_template("marketplace/listing_list.html")
    return HttpResponse(template.render(browse_context(request), request))


# 2. FBV (render shortcut)
def listing_render_view(request):
    return render(request, "marketplace/listing_list.html", browse_context(request))


# 3. Base CBV
class ListingBaseView(View):
    def get(self, request):
        return render(request, "marketplace/listing_list.html", browse_context(request))


# 4. Generic CBV
class ListingListView(ListView):  # Naming Pattern: <Model><Purpose>View
    model = Listing
    template_name = "marketplace/listing_list.html"
    context_object_name = "listings"

    def get_queryset(self):
        self.browse = browse_context(self.request)
        return self.browse["listings"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.browse)
        return context
