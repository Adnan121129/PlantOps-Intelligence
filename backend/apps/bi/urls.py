from django.urls import path

from . import views

urlpatterns = [
    path("datasets/", views.DatasetListView.as_view()),
    path("datasets/<str:name>/", views.DatasetView.as_view()),
    path("token/", views.TokenView.as_view()),
]
