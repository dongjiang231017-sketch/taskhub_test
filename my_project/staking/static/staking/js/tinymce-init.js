function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

document.addEventListener('DOMContentLoaded', function() {
    if (typeof tinymce !== 'undefined') {
        tinymce.init({
            selector: '#id_description',
            menubar: false,
            plugins: 'link lists image table code wordcount',
            toolbar: 'undo redo | bold italic underline strikethrough forecolor backcolor | alignleft aligncenter alignright alignjustify | bullist numlist | table | link image | removeformat | code',
            image_title: true,
            automatic_uploads: true,
            file_picker_types: 'image',
            file_picker_callback: function(callback, value, meta) {
                if (meta.filetype === 'image') {
                    var input = document.createElement('input');
                    input.setAttribute('type', 'file');
                    input.setAttribute('accept', 'image/*');
                    input.onchange = function() {
                        var file = this.files[0];
                        var formData = new FormData();
                        formData.append('file', file);
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/staking/upload-image/');
                        xhr.setRequestHeader('X-CSRFToken', getCookie('csrftoken'));
                        xhr.onload = function() {
                            if (xhr.status !== 200) {
                                alert('图片上传失败: ' + xhr.responseText);
                                return;
                            }
                            var json = JSON.parse(xhr.responseText);
                            if (json.location) {
                                callback(json.location, { alt: file.name });
                            } else {
                                alert('图片上传返回结果不正确');
                            }
                        };
                        xhr.send(formData);
                    };
                    input.click();
                }
            },
            height: 360,
            branding: false,
            content_style: 'body { font-family: Helvetica, Arial, sans-serif; font-size:14px; }'
        });
    }
});
