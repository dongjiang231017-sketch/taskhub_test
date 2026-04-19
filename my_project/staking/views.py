import os
import uuid

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


@staff_member_required
@require_POST
def upload_image(request):
    uploaded_file = request.FILES.get('file') or request.FILES.get('image')
    if not uploaded_file:
        return JsonResponse({'error': '没有上传文件'}, status=400)

    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
        return JsonResponse({'error': '不支持的图片格式'}, status=400)

    filename = f"staking_{uuid.uuid4().hex}{ext}"
    upload_path = os.path.join('staking_uploads', filename)
    saved_path = default_storage.save(upload_path, ContentFile(uploaded_file.read()))
    url = settings.MEDIA_URL + saved_path.replace('\\', '/')
    return JsonResponse({'location': url})
