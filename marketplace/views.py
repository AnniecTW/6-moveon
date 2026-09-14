from django.http import HttpResponse
from django.shortcuts import render
from django.template import loader
from django.views import View
from django.views.generic import ListView
from .models import Listing
from .browse import browse_context

# 1. FBV (Manual HttpResponse)
def listing_manual_view(request):
    template = loader.get_template('marketplace/listing_list.html')
    return HttpResponse(template.render(browse_context(request), request))

# 2. FBV (render shortcut)
def listing_render_view(request):
    return render(request, 'marketplace/listing_list.html', browse_context(request))

# 3. Base CBV
class ListingBaseView(View):
    def get(self, request):
        return render(request, 'marketplace/listing_list.html', browse_context(request))

# 4. Generic CBV
class ListingGenericView(ListView):
    model = Listing
    template_name = 'marketplace/listing_list.html'
    context_object_name = 'listings'

    def get_queryset(self):
        self.browse = browse_context(self.request)
        return self.browse['listings']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.browse)
        return context
