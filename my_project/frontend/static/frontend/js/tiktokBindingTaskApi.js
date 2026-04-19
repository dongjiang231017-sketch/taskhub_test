/**
 * 必做任务：TikTok 账号绑定（报名 + 站外转发指定视频后校验）
 * 依赖：fetch、Promise。页面中引入后使用 window.TaskhubTikTokBinding。
 *
 * 流程：1) POST /tasks/{taskId}/apply 传 bound_username（用户名或 tiktok.com/@… 链接）
 *       2) 用户转发任务 interaction_config.target_video_url 对应视频
 *       3) POST /me/applications/{applicationId}/verify-tiktok/（须服务端配置 APIFY_API_TOKEN）
 */
(function (global) {
    "use strict";

    function stripLeadingAt(s) {
        if (s == null || s === "") return "";
        return String(s).trim().replace(/^@+/, "");
    }

    function apiBase() {
        return (global.TASKHUB_API_PREFIX || "/api/v1").replace(/\/$/, "");
    }

    function parseJsonResponse(res, rawText) {
        try {
            return JSON.parse(rawText);
        } catch (e) {
            var err = new Error(rawText || res.statusText || "非 JSON 响应");
            err.status = res.status;
            throw err;
        }
    }

    function taskhubFetch(path, options) {
        options = options || {};
        var url = apiBase() + (path.charAt(0) === "/" ? path : "/" + path);
        var headers = Object.assign({ Accept: "application/json" }, options.headers || {});
        if (options.token) {
            headers.Authorization = "Bearer " + options.token;
        }
        if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
            headers["Content-Type"] = "application/json";
        }
        return fetch(url, {
            method: options.method || "GET",
            headers: headers,
            body: options.body,
        }).then(function (res) {
            return res.text().then(function (text) {
                var data = parseJsonResponse(res, text || "{}");
                if (data.code !== 0) {
                    var msg = data.message || "请求失败";
                    var err = new Error(msg);
                    err.code = data.code;
                    err.data = data.data;
                    err.status = res.status;
                    throw err;
                }
                return data.data;
            });
        });
    }

    global.TaskhubTikTokBinding = {
        apiBase: apiBase,

        /**
         * 报名 TikTok 绑定类必做任务
         * @param {number} taskId
         * @param {string} token Bearer
         * @param {string} boundUsername TikTok 用户名，或含 @handle / 完整 profile URL（后端会规范化）
         * @param {{ proposal?: string, quoted_price?: string }} [extra]
         */
        apply: function (taskId, token, boundUsername, extra) {
            extra = extra || {};
            var raw = String(boundUsername || "").trim();
            var body = {
                bound_username: raw.indexOf("tiktok.com") >= 0 ? raw : stripLeadingAt(raw),
                proposal: extra.proposal || "",
                quoted_price: extra.quoted_price != null ? extra.quoted_price : null,
            };
            return taskhubFetch("/tasks/" + taskId + "/apply/", {
                method: "POST",
                token: token,
                body: JSON.stringify(body),
            });
        },

        /**
         * 站外转发完成后调用；成功后报名一般为 accepted
         * @param {number} applicationId
         * @param {string} token Bearer
         * @param {string} [boundUsername] 若报名未写可在此补传
         */
        verify: function (applicationId, token, boundUsername) {
            var body = {};
            if (boundUsername) {
                var r = String(boundUsername).trim();
                body.bound_username = r.indexOf("tiktok.com") >= 0 ? r : stripLeadingAt(r);
            }
            return taskhubFetch("/me/applications/" + applicationId + "/verify-tiktok/", {
                method: "POST",
                token: token,
                body: JSON.stringify(body),
            });
        },

        stripLeadingAt: stripLeadingAt,
    };
})(typeof window !== "undefined" ? window : globalThis);
