from django.urls import path

from . import views

app_name = "bundles"

urlpatterns = [
    path(
        "start-modal/",
        views.BundleStartModalView.as_view(),
        name="start_modal",
    ),
    path("start/", views.BundleStartView.as_view(), name="start"),
    path("select-space/", views.BundleSpaceView.as_view(), name="select_space"),
    path(
        "select-categories/",
        views.BundleCategoryView.as_view(),
        name="select_categories",
    ),
    path("generating/", views.BundleGeneratingView.as_view(), name="generating"),
    path("generate/", views.BundleGenerateView.as_view(), name="generate"),
    path("builder/", views.BundleBuilderView.as_view(), name="builder"),
    path("summary/", views.BundleSummaryView.as_view(), name="summary"),
]
