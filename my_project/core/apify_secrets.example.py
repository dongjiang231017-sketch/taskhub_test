# 使用方法：复制本文件为同目录下的 apify_secrets.py，在 apify_secrets.py 里填写真实 Token。
# 切勿在本 example 文件里填写真实 APIFY_API_TOKEN（本文件可能被提交到 git）。
# 文件 apify_secrets.py 已在 .gitignore 中。
# 也可不设 apify_secrets.py，仅用环境变量 APIFY_API_TOKEN。

# Apify 控制台 → Settings → Integrations → API token（勿在 example 中填真实值）
APIFY_API_TOKEN = ""

# 可选；默认使用官方 Store：`apify/instagram-profile-scraper`
APIFY_INSTAGRAM_ACTOR_ID = "apify/instagram-profile-scraper"

# 可选；调用 run-sync 的 timeout 秒数（30–300）
APIFY_INSTAGRAM_TIMEOUT_SEC = 120

# TikTok 绑定「转发指定视频」校验（与上共用 APIFY_API_TOKEN）；默认 clockworks/tiktok-scraper
# APIFY_TIKTOK_ACTOR_ID = "clockworks/tiktok-scraper"
# APIFY_TIKTOK_TIMEOUT_SEC = 180
# APIFY_TIKTOK_RESULTS_PER_PAGE = 60
