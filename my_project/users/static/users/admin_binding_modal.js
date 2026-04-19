(function () {
    "use strict";

    function ensureModal() {
        var el = document.getElementById("th-binding-modal");
        if (el) return el;
        el = document.createElement("div");
        el.id = "th-binding-modal";
        el.setAttribute("hidden", "hidden");
        el.innerHTML =
            '<div class="th-binding-modal__backdrop" data-close="1"></div>' +
            '<div class="th-binding-modal__panel" role="dialog" aria-modal="true" aria-labelledby="th-binding-modal-title">' +
            '<button type="button" class="th-binding-modal__close" data-close="1" aria-label="关闭">&times;</button>' +
            '<div class="th-binding-modal__head">' +
            '<span class="th-binding-modal__head-icon" aria-hidden="true">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
            '<path d="M10 13a5 5 0 0 1 7.54.54M14 11a5 5 0 0 0-7.54-.54" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
            '<circle cx="7" cy="8" r="2.2" stroke="currentColor" stroke-width="1.6"/>' +
            '<circle cx="17" cy="16" r="2.2" stroke="currentColor" stroke-width="1.6"/>' +
            "</svg></span>" +
            '<h2 class="th-binding-modal__title" id="th-binding-modal-title">绑定账号</h2></div>' +
            '<div class="th-binding-modal__body" id="th-binding-modal-body"></div></div>';
        document.body.appendChild(el);
        el.addEventListener("click", function (e) {
            if (e.target && e.target.getAttribute("data-close")) hideModal();
        });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && el && !el.hidden) hideModal();
        });
        return el;
    }

    function hideModal() {
        var el = document.getElementById("th-binding-modal");
        if (el) el.hidden = true;
    }

    /** Base64 内容为 UTF-8 编码的 JSON（与后台 json.dumps(...).encode("utf-8") 一致），须先按 UTF-8 解码再 parse，否则中文会乱码。 */
    function base64ToUtf8JsonString(b64) {
        var binary = atob(b64);
        if (typeof TextDecoder !== "undefined") {
            var bytes = new Uint8Array(binary.length);
            for (var i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i) & 0xff;
            }
            return new TextDecoder("utf-8").decode(bytes);
        }
        return decodeURIComponent(escape(binary));
    }

    function esc(s) {
        if (s == null) return "";
        var d = document.createElement("div");
        d.textContent = String(s);
        return d.innerHTML;
    }

    function renderRows(rows) {
        var html = "";
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i] || {};
            var plat = r.platform || "";
            var acc = r.account != null ? r.account : "";
            html += '<div class="th-binding-card">';
            if (plat) {
                html += '<div class="th-binding-card__platform">' + esc(plat) + "</div>";
            }
            html +=
                '<div class="th-binding-row"><span class="th-bind-k">已绑定：</span><span class="th-bind-v"><code>' +
                esc(acc) +
                "</code></span></div>";
            html += "</div>";
        }
        return html;
    }

    function showModal(rows) {
        var modal = ensureModal();
        var body = document.getElementById("th-binding-modal-body");
        if (!body) return;
        body.innerHTML = renderRows(rows);
        modal.hidden = false;
    }

    document.addEventListener("click", function (e) {
        var btn = e.target.closest(".th-bind-modal-trigger");
        if (!btn) return;
        e.preventDefault();
        var b64 = btn.getAttribute("data-binding-b64");
        if (!b64) return;
        try {
            var json = base64ToUtf8JsonString(b64);
            var rows = JSON.parse(json);
            if (!Array.isArray(rows)) rows = [];
            showModal(rows);
        } catch (err) {
            window.alert("无法解析绑定数据，请刷新页面后重试。");
        }
    });
})();
