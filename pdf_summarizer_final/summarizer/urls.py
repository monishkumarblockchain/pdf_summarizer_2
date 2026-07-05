from django.urls import path
from . import views

urlpatterns = [
    path("", views.upload_pdf, name="upload_pdf"),
    path("chat/<int:doc_id>/", views.chat_with_pdf, name="chat_with_pdf"),
    path("chat/<int:doc_id>/clear/", views.clear_chat_history, name="clear_chat_history"),
]
