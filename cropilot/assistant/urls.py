from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="chat"),
    path("chat/conversations/", views.ConversationListView.as_view(), name="chat-conversations"),
    path("chat/conversations/<int:pk>/", views.ConversationDetailView.as_view(), name="chat-conversation"),
]
