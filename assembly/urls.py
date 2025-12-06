# File: assembly/urls.py
# Version: 1.0.0
# Author: vas
# Modified: 2025-11-28

from django.urls import path
from . import views

app_name = 'assembly'

urlpatterns = [
    # Protocol Editor
    path('protocol-editor/', views.protocol_editor, name='protocol_editor'),
    path('protocol-editor/<int:session_id>/', views.protocol_editor, name='protocol_editor_session'),
    
    # AJAX endpoints
    path('protocol-editor/<int:session_id>/save-item/', views.protocol_save_item, name='protocol_save_item'),
    path('protocol-editor/<int:session_id>/save-item/<int:item_id>/', views.protocol_save_item, name='protocol_update_item'),
    path('protocol-editor/<int:session_id>/get-item/<int:item_id>/', views.protocol_get_item, name='protocol_get_item'),
    path('protocol-editor/<int:session_id>/delete-item/<int:item_id>/', views.protocol_delete_item, name='protocol_delete_item'),
    path('protocol-editor/<int:session_id>/reorder-items/', views.protocol_reorder_items, name='protocol_reorder_items'),
    path('protocol-editor/<int:session_id>/insert-at/<int:insert_after_order>/', views.protocol_insert_at, name='protocol_insert_at'),
]