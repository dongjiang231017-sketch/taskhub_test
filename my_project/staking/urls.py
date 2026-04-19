from django.urls import path
from .views import upload_image

urlpatterns = [
    path('upload-image/', upload_image, name='staking-upload-image'),
]
