/**
 * 必做任务：Twitter 账号绑定（报名 + 站外转发/关注后校验）
 * 依赖：fetch、Promise。在页面中先引入本脚本，使用 window.TaskhubTwitterBinding。
 *
 * 流程：1) POST /tasks/{taskId}/apply 传 bound_username
 *       2) 用户打开 interaction_config.target_tweet_url 并转发（及可选关注）
 *       3) POST /me/applications/{applicationId}/verify-twitter/ 触发服务端调 X API 自动录用
 */
(function (global) {
    "use strict";

    function stripAt(s) {
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

    global.TaskhubTwitterBinding = {
        /** 与后端默认一致，可在页面加载前设置 global.TASKHUB_API_PREFIX = 'https://你的域名/api/v1' */
        apiBase: apiBase,

        /**
         * 报名 Twitter 绑定类必做任务
         * @param {number} taskId
         * @param {string} token Bearer
         * @param {string} twitterUsername 不含 @
         * @param {{ proposal?: string, quoted_price?: string }} [extra]
         */
        apply: function (taskId, token, twitterUsername, extra) {
            extra = extra || {};
            var body = {
                bound_username: stripAt(twitterUsername),
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
         * 站外完成转发/关注后调用；成功后报名一般为 accepted
         * @param {number} applicationId my_application.id 或 apply 返回的 application.id
         * @param {string} token Bearer
         * @param {string} [twitterUsername] 若报名未写用户名可在此补传
         */
        verify: function (applicationId, token, twitterUsername) {
            var body = {};
            if (twitterUsername) {
                body.bound_username = stripAt(twitterUsername);
            }
            return taskhubFetch("/me/applications/" + applicationId + "/verify-twitter/", {
                method: "POST",
                token: token,
                body: JSON.stringify(body),
            });
        },

        stripAt: stripAt,
    };
})(typeof window !== "undefined" ? window : globalThis);
