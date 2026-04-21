# TaskHub API 文档

本项目已改造成“任务发布平台后端”，接口统一前缀为 `/api/v1/`，返回结构统一为：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

- `code = 0` 表示成功
- 非 `0` 表示业务错误

**前端速查（Telegram 邀请 / Foxi 式链接）**：服务端配置的 **`https://t.me/<Bot>?start=ref_…`** 与响应里的 **`data.invite_link`**（含 `full_url`、`link_style`、`start_param`、可选 **`mini_app_url`**）写在 **§4.5** 环境变量表与 **§4.5.4**；**`start_param` / 注册 `ref` / `ref_<TelegramId>`** 的绑定规则写在 **§2.5** 与 **§2.1**。**§9 接口速查**里 `invite-overview` 一行有入口提示，字段细节以 **§4.5** 为准（勿只在速查表里找长说明）。

## 1. 鉴权规则

登录或注册成功后会返回 `token`。后续接口在 Header 中传：

```http
Authorization: Bearer <token>
```

### 1.1 哪些接口必须带 Bearer（前端核对）

| 类型 | 路径前缀或示例 | 是否需 Bearer |
| --- | --- | --- |
| 健康与文档 | `GET /api/v1/health/`、`GET /api/v1/docs/` | 否 |
| 注册 / 手机号登录 | `POST /api/v1/auth/register/`、`POST /api/v1/auth/login/` | 否 |
| **Telegram 登录** | `POST /api/v1/auth/telegram/` 及 **§2.5** 所列兼容路径 | **否**（POST 登录时） |
| 分类 / 任务列表等 | 见各章节标注「可不登录」的接口 | 按文档 |
| **个人中心 / 排行 / 签到 / 我的任务等** | `GET/POST /api/v1/me/...`（含 **`/me/ranking/`**） | **是**（除登录外几乎全部要） |

未带或 token 错误时：**HTTP 401**，`code` 多为 **4010**，`message` 一般为「未登录或 token 无效」。服务端日志里可能出现 **`Unauthorized: /api/v1/me/center/`** 字样，**属于预期**，不是接口缺失；请在前端确认请求头里已拼上 **`Authorization: Bearer ` + 登录接口返回的 `data.token`**。

## 2. 认证相关

### 2.1 注册

- `POST /api/v1/auth/register/`

请求体：

```json
{
  "phone": "13800138000",
  "username": "alice",
  "password": "123456",
  "pay_password": "123456",
  "membership_level": 1,
  "invite_code": "ABCD1234"
}
```

- **`invite_code`**（可选，也可用 **`ref`**）：可为邀请人的 **`invite_code`**，或与 Bot 深链一致的 **`ref_<TelegramId>`** / 纯数字 Telegram ID；匹配则写入 **`referrer`**；无效则忽略（不报错）。勿对整段载荷做 10 字截断。

### 2.2 登录

- `POST /api/v1/auth/login/`

请求体：

```json
{
  "phone": "13800138000",
  "password": "123456"
}
```

### 2.3 退出登录

- `POST /api/v1/auth/logout/`
- 需要 Bearer Token

### 2.4 当前用户信息

- `GET /api/v1/me/profile/`
- 需要 Bearer Token

返回的 `user` 与登录接口一致，额外字段：

- `telegram_id`：若通过 Telegram 登录过则有值，否则为 `null`
- `telegram_username`：Telegram @用户名（不含 `@`），可能为 `null`
- `phone`：手机号注册的用户有值；**纯 Telegram 注册**的用户为 `null`

### 2.5 Telegram Mini App 登录（推荐用于 TaskFlow / TMA）

在 Telegram Mini App 内使用 **`window.Telegram.WebApp.initData`**（**原样字符串**，不要自己拼 query）。

- **主路径**：`POST /api/v1/auth/telegram/`
- **兼容路径**（与主路径同一处理逻辑，任选其一配置到前端即可）：
  - `POST /api/auth/telegram/`（少一层 `/v1/`，避免 Nginx/前端写成 `/api/auth/...` 时出现 **404 HTML**）
  - `POST /api/v1/telegram/miniapp-login/`（别名）
- `GET` 以上任一地址：返回 JSON，说明须用 **POST** 及路径列表（**不会**返回 Django HTML 调试页）。
- **无需** Bearer；成功后与其它登录方式一样返回 `token`，后续请求带 `Authorization: Bearer <token>` 即可。

请求体（JSON）：

```json
{
  "init_data": "<把 WebApp.initData 整段粘到这里>",
  "include_home": true
}
```

- `init_data`：必填（或驼峰 **`initData`**，二者填一个即可）。
- **`include_home`**（可选，布尔或 `"true"`/`1`）：为 **`true`** 时，登录成功后在**同一响应**的 `data.home` 中附带与 **`GET /api/v1/me/home/`** 完全相同的结构（`user` / `wallet` / `stats` / `check_in`）。**推荐 Mini App 首屏打开时**与 `init_data` 一并 POST，实现「自动注册/登录 + 立即用该账号拉首页数据」一次完成；后续其它接口仍须带 **`Authorization: Bearer <token>`**。
- **`invite_code` / `ref` / `inviter_invite_code`**（可选）：与 **`initData` 内 `start_param`** 作用相同，用于绑定 **`referrer`**；见上文行为说明第 3 点。若前端已从落地 URL 解析出邀请码，也可在 **POST body** 再传一份以防个别客户端未把参数带进 `initData`。

**服务端环境变量**（必填才能校验签名）：

- `TELEGRAM_BOT_TOKEN`：与 Mini App 绑定的 **BotFather 机器人 Token**（与校验 `initData` 用同一机器人）

**行为说明**：

1. 使用 [Telegram Web Apps 校验规则](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app) 校验 `init_data` 的 `hash` 与 `auth_date`（默认允许 86400 秒内）。
2. 按 Telegram `user.id` 查找或创建一条 `FrontendUser`（`telegram_id` 唯一）；新用户会分配 `username`（如 `tg123456789`），`phone` 为空，并自动创建钱包。
3. **推荐关系（自动绑定）**：若该用户 **`referrer` 仍为空**，服务端会依次读取 **`initData` 解析出的 `start_param`**（用户通过 **`https://t.me/<BotUsername>/<MiniAppShortName>?startapp=…`** 打开 Mini App 时，Telegram 把载荷写入签名字段 **`start_param`**）以及 POST body 中的 **`invite_code` / `ref` / `inviter_invite_code`**；解析规则与注册一致：**`invite_code`**、**`ref_<TelegramId>`**（前缀可配置，默认 `ref_`）、或 **纯数字 Telegram ID**（按 **`FrontendUser.telegram_id`** 查邀请人；邀请码仍最长 10 位）。已绑定过的账号**不会**被覆盖。无效或指向自己时静默跳过。
4. 签发/刷新 `ApiToken` 并返回（与手机号登录相同结构）。

**业务错误（未自动注册时优先核对）**

| HTTP | code | 常见原因 |
| --- | --- | --- |
| 400 | 4060 | 未传 `init_data` / 传了 `initDataUnsafe` 或仅展示 `user`；或非 Mini App 环境 `initData` 为空 |
| 503 | 4061 | 服务端未配置 `TELEGRAM_BOT_TOKEN`（无法验签，无法开户） |
| 401 | 4062 | `init_data` 签名校验失败或已过期；**Bot 与 Mini App 绑定的机器人不一致** |

成功时 `data` 至少含 `token`、`user`；若请求里 `include_home: true`，另含 **`home`**（结构同 **§2.6** `me/home` 的 `data`）。

`data` 示例（含 `include_home`）：

```json
{
  "token": "<hex>",
  "user": {
    "id": 1,
    "phone": null,
    "username": "tg123456789",
    "telegram_id": 123456789,
    "telegram_username": "alice",
    "membership_level": 1,
    "invite_code": "ABCD1234",
    "status": true,
    "created_at": "2026-04-15T12:00:00+08:00",
    "telegram_first_name": "Alice"
  },
  "home": {
    "user": { "id": 1, "username": "tg123456789", "telegram_id": 123456789 },
    "wallet": { "usdt": "0.00", "th_coin": "0.00" },
    "stats": {
      "cumulative_earnings_usdt": "0.00",
      "cumulative_earnings_th_coin": "0.00",
      "completed_tasks_count": 0
    },
    "check_in": {}
  }
}
```

（上表 `check_in` 仅为占位；真实字段与 **§2.7.1** 周历一致。）

#### 2.5.1 前端联调核对（Telegram 里已能取到用户信息时）

**重要**：后端**不会**仅凭前端「识别到 Telegram 账号」（例如只读了 **`WebApp.initDataUnsafe`** 或 **`WebApp.user`**）就写库；**必须**由前端发起 **`POST`**，body 里传 **`init_data` = `WebApp.initData` 整段**（有签名的字符串），校验通过后才会 **自动创建** `FrontendUser` 并返回 `token`。若从未成功 POST 或 `init_data` 为空，数据库里就不会有新用户。

Mini App / Telegram 客户端里通过 **`Telegram.WebApp`** 取到的 **`user`（id、username 等）只表示在 Telegram 侧的身份**，**不能**代替本后端的登录态。

| 步骤 | 前端应做的事 |
| --- | --- |
| 1 | 取 **`Telegram.WebApp.initData`** 的**完整字符串**（不要自己拼 query、不要只传 user JSON）。 |
| 2 | **`POST`** 登录接口（任选 **§2.5** 中一条 URL），`Content-Type: application/json`，body：`{"init_data":"...","include_home":true}`（`include_home` 可选，见上文）。 |
| 3 | 解析响应 JSON：若 **`code === 0`**，取出 **`data.token`** 持久化（内存 / localStorage / 全局 store 等，按你们安全策略）；若带了 `include_home: true`，可直接用 **`data.home`** 渲染首页。 |
| 4 | 之后请求 **`/api/v1/me/home/`、`/api/v1/me/center/`** 等：每个请求 Header 增加 **`Authorization: Bearer <data.token>`**（注意 **`Bearer` 后有一个空格**）。 |

**Base URL 建议**：例如 `https://你的域名`，路径统一为 **`/api/v1/...`**。若误写成 **`/api/me/...`**（少了 **`v1`**），除 Telegram 登录已提供的 **兼容路径**外，会得到 **HTTP 404**（生产环境若 `DEBUG` 关闭多为简短页；开发环境可能为 Django HTML 说明页）。

**与「已取到用户信息」的关系**：前端展示用的 Telegram `user` 可与后端返回的 **`data.user`**（含 `id`、`telegram_id`、`username` 等）对照；**但调用业务接口必须以 `data.token` 为准**，否则会 **401**。

### 2.6 首页聚合（累计收益 / 余额 / 完成任务数 / 签到周历）

用于 TaskFlow 首页一次拉齐数据（对应设计稿顶部统计 + 签到条）。

- `GET /api/v1/me/home/`
- 需要 Bearer Token

`data` 主要字段：

| 字段 | 说明 |
| --- | --- |
| `user` | 同 `me/profile/` |
| `wallet.usdt` | 当前 **USDT** 可用余额（与后台钱包 `balance` 一致） |
| `wallet.th_coin` | 当前 **TH Coin**（与后台钱包 `frozen` 字段一致，产品命名） |
| `stats.cumulative_earnings_usdt` | 累计「USDT 向」入账：账变里 `amount>0` 且备注 **不含** `TH Coin` 的合计（历史老数据若无备注则可能计入此项） |
| `stats.cumulative_earnings_th_coin` | 累计 TH：`amount>0` 且备注含 `TH Coin` 的合计 |
| `stats.completed_tasks_count` | 已录用报名数：`TaskApplication.status = accepted` |
| `check_in` | 与 `GET /api/v1/me/check-in/` 相同结构，见下节 |

### 2.7 每日签到与补签（前端联调说明）

统一前缀：`https://<host>/api/v1/`（本地多为 `http://127.0.0.1:8000/api/v1/`）。  
鉴权：**除 GET 说明外，以下接口均需 Header**：`Authorization: Bearer <token>`。

自然周为 **周一至周日**（按 `TIME_ZONE` 本地日历日，默认 `Asia/Shanghai`）。

---

#### 2.7.1 查询周历与规则 — `GET /api/v1/me/check-in/`

| 项 | 说明 |
| --- | --- |
| 方法 / 路径 | `GET /api/v1/me/check-in/` |
| 请求体 | 无 |
| 需登录 | 是 |

**成功时 `data` 结构（字段名固定，便于前端绑定 UI）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `today` | string | 今天 `YYYY-MM-DD` |
| `week_start` / `week_end` | string | 本周一、周日 |
| `days` | array | 长度 7，顺序为周一至周日 |
| `days[].date` | string | 该日 `YYYY-MM-DD` |
| `days[].weekday_index` | number | `0`=周一 … `6`=周日 |
| `days[].weekday_label` | string | `Mon` … `Sun` |
| `days[].checked` | boolean | 该日是否已签到 |
| `days[].is_today` | boolean | 是否为今天 |
| `days[].can_make_up` | boolean | 是否**可尝试**补签（早于今天、当周、未签到且本周仍有补签名额；**不**保证 TH 一定够，提交时再以接口返回为准） |
| `streak_days` | number | 从今天往回连续已签到天数 |
| `makeups_used_this_week` | number | 本周已用补签次数 |
| `makeups_remaining_this_week` | number | 本周剩余补签次数 |
| `makeups_limit_per_week` | number | 本周补签上限（来自后台配置） |
| `config` | object | 规则快照，与后台「签到参数配置」一致 |
| `config.daily_reward_usdt` | string | 每日签到奖励 USDT（decimal 字符串） |
| `config.daily_reward_th_coin` | string | 每日签到奖励 TH Coin |
| `config.makeup_cost_th_coin` | string | 每次补签消耗 TH Coin；`"0"` 表示不扣 |
| `config.weekly_makeup_limit` | number | 每周补签次数上限 |

`GET /api/v1/me/home/` 中的 `data.check_in` **与上表结构完全相同**，无需重复请求周历。

---

#### 2.7.2 今日签到 — `POST /api/v1/me/check-in/`

| 项 | 说明 |
| --- | --- |
| 方法 / 路径 | `POST /api/v1/me/check-in/` |
| `Content-Type` | `application/json`（请求体可为 `{}` 或空对象） |
| 请求体 | **无必填字段**；传 `{}` 即可 |
| 需登录 | 是 |

**成功（HTTP 200，`code=0`）**

除与 **2.7.1** 相同的周历字段外，`data` 额外包含：

| 字段 | 说明 |
| --- | --- |
| `last_granted` | object；本次实际发放的奖励，`usdt` / `th_coin` 为字符串；未配置或为 0 时为 `"0"` |

**业务错误（非 0 `code`）**

| HTTP | code | 说明 |
| --- | --- | --- |
| 409 | 4070 | 今日已签到 |

签到成功后会写入钱包（USDT=`balance`，TH=`frozen`）并记账变；前端可在成功后再次请求 `GET /api/v1/me/home/` 刷新余额。

---

#### 2.7.3 补签 — `POST /api/v1/me/check-in/make-up/`

| 项 | 说明 |
| --- | --- |
| 方法 / 路径 | `POST /api/v1/me/check-in/make-up/` |
| `Content-Type` | `application/json` |
| 需登录 | 是 |

**请求体（JSON）**

```json
{
  "date": "2026-04-14"
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `date` | 是 | `YYYY-MM-DD`，须为**今天之前**，且落在**当前自然周**（`week_start`～`week_end`）内 |

**成功（HTTP 200，`code=0`）**

`data` 为更新后的周历（同 2.7.1）。成功时还可能包含：

| 字段 | 说明 |
| --- | --- |
| `last_spent` | object，如 `{ "th_coin": "10.00" }`；配置了补签消耗且实际扣款时才有 |
| `last_granted` | object，与 **2.7.2** 相同；补签成功后也会按后台 **同一套** `daily_reward_usdt` / `daily_reward_th_coin` 发放奖励（账变备注为「补签奖励：…」） |

**业务错误**

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | 4001 | 请求体非合法 JSON |
| 400 | 4071 | 缺少 `date` |
| 400 | 4072 | `date` 格式不是 `YYYY-MM-DD` |
| 400 | 4073 | 补签日期不能是今天或未来 |
| 400 | 4074 | 不在当前自然周内 |
| 409 | 4075 | 该日已有签到记录 |
| 400 | 4076 | 本周补签次数已用完 |
| 400 | 4077 | TH Coin 不足（低于后台配置的 `makeup_cost_th_coin`） |

处理顺序：**先扣** `makeup_cost_th_coin`（若有），**再发**与正常签到相同的每日奖励；若 TH 不足以支付补签消耗，整笔失败（`4077`），不会发奖。

---

#### 2.7.4 联调示例（curl）

```bash
# 周历 + 规则
curl -sS -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:8000/api/v1/me/check-in/"

# 今日签到
curl -sS -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "http://127.0.0.1:8000/api/v1/me/check-in/"

# 补签某一天（替换 date）
curl -sS -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-04-14"}' \
  "http://127.0.0.1:8000/api/v1/me/check-in/make-up/"
```

---

#### 2.7.5 后台配置（运营）

在 **任务平台 → 签到参数配置** 维护（全局 **仅一条**；无记录时后台可「新增」一条）：

- `daily_reward_usdt` / `daily_reward_th_coin`：**POST 今日签到**成功时发放  
- `makeup_cost_th_coin`：**POST 补签**每次从用户 TH Coin 扣除；`0` 表示不扣  
- `weekly_makeup_limit`：每自然周最多补签次数

### 2.8 个人中心（提现 / 收益记录 / 提现记录 / 账号管理）

对应 Stitch 设计稿 `_1`～`_5`：提现弹窗、收益记录、提现记录、账号管理、个人中心主页。  
统一前缀 `GET|POST https://<host>/api/v1/me/...`，**除另有说明外一律需 Bearer**（见 **§1.1**）。

**说明**：若服务端日志出现 **`Unauthorized: /api/v1/me/center/`**，表示该次请求**未通过** Bearer 校验（未带、拼错、`Bearer` 后缺空格、token 过期等），与「Telegram 里是否能看到 user」无关；请按 **§2.5.1** 先完成 **POST 登录拿 token**，再在业务请求里带 **`Authorization`**。

**环境变量（可选）**

| 变量 | 说明 |
| --- | --- |
| `WITHDRAW_MIN_USDT` | 最低提现金额（默认 `2.00`） |
| `WITHDRAW_FEE_USDT` | 每笔固定手续费（默认 `0.00`）；**从用户填写的提现总额中扣除**，`预计到账 = amount - fee` |
| `TELEGRAM_COMMUNITY_URL` | Telegram 社区链接，出现在 `me/center/` 的 `links.telegram_community` |

---

#### 2.8.1 个人中心聚合 — `GET /api/v1/me/center/`

- **方法 / 路径**：`GET /api/v1/me/center/`
- **鉴权**：**必须** `Authorization: Bearer <token>`（与 `GET /api/v1/me/home/` 相同）。

在 `GET /api/v1/me/home/` 基础上增加等级/排名、最近收益、提现规则与外链；并包含与首页相同的 **`check_in` 周历**（字段同 **2.7.1**）。

**未登录或 token 无效时**

| HTTP | `code` | 说明 |
| --- | --- | --- |
| 401 | 4010 | 未登录或 token 无效（服务端可能记日志 `Unauthorized`） |

| 字段 | 说明 |
| --- | --- |
| `level` | `tier` / `tier_label` / `title` / `exp_current` / `exp_next` / `progress_percent` / `hint`（经验规则可后续接独立表） |
| `rank` | `position`：按「已录用任务数」全站排名；`label` 展示文案 |
| `recent_rewards` | 最近若干条账变（不含充值、后台拨币、提现） |
| `links.telegram_community` | 未配置时为 `null` |
| `withdraw` | `min_amount_usdt` / `fee_usdt` / `chain_default` / `estimated_arrival_hint` |

---

#### 2.8.2 收益与账单明细 — `GET /api/v1/me/rewards/ledger/`

钱包账变列表（**不含** `admin_adjust`、`recharge`；**不含**提现流水，提现见 **2.8.3**）。

**Query**

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `page` | `1` | 页码 |
| `page_size` | `20` | 最大 `50` |
| `asset` | `all` | `all` / `usdt` / `th_coin`（TH 以备注含 `TH Coin` 为准，与首页统计一致） |
| `days` | 不传=不限 | 仅看最近 N 天；`0` 表示不限 |

**成功 `data`**

| 字段 | 说明 |
| --- | --- |
| `summary.total_usdt` / `summary.total_th_coin` | **历史累计**正向入账（与列表筛选无关，便于顶部「Total」展示） |
| `items[]` | `id` / `asset` / `amount` / `amount_display` / `change_type` / `label` / `remark` / `created_at` |
| `pagination` | `page` / `page_size` / `total` |

---

#### 2.8.3 提现 — `GET|POST /api/v1/me/withdrawals/`

**GET**：提现记录（默认**最近 30 天**，可用 `days` 调整）。

**Query（GET）**

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `page` | `1` |  |
| `page_size` | `20` | 最大 `50` |
| `days` | `30` | `0` 表示不限时间 |

**成功 `data`（GET）**

| 字段 | 说明 |
| --- | --- |
| `summary.total_withdrawn_usdt` | 状态为 **已完成** 的提现金额合计（扣款总额 `amount`） |
| `summary.pending_count` | 状态为 **处理中** 的笔数 |
| `summary.window_days` | 与请求 `days` 一致 |
| `items[]` | `id` / `amount` / `fee` / `net_amount` / `chain` / `to_address` / `status`（`processing`/`completed`/`rejected`）/ `reject_reason` / 时间 |
| `pagination` | 同前 |

**POST**：发起提现。成功时立即从 **USDT 余额**扣除 `amount`，并写入一条 `change_type=withdraw` 的账变；同时创建状态为 **`processing`** 的申请单（运营/后台可在 Django Admin `提现申请` 中标记完成或拒绝；拒绝需自行处理退款逻辑）。

**请求体（JSON）**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `amount` | 是 | 从钱包扣除的 USDT 总额（须 ≥ `WITHDRAW_MIN_USDT`） |
| `to_address` | 是 | BEP20 收款地址；也支持字段名 `address` |
| `chain` | 否 | 默认 `BEP20` |

手续费为服务端配置的 `WITHDRAW_FEE_USDT`：**到账 USDT = amount - fee**，且须 **> 0**。

**业务错误**

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | 4001 | Query/JSON 不合法 |
| 400 | 4080 | USDT 余额不足 |
| 400 | 4081 | `amount` 非数字 |
| 400 | 4082 | 低于最低提现额 |
| 400 | 4083 | 扣费后到账 ≤ 0 |
| 400 | 4084 | 地址格式无效 |

---

#### 2.8.4 账号管理 — `GET /api/v1/me/bindings/accounts/`

按平台返回绑定情况（顺序固定：Twitter → YouTube → Instagram → TikTok → Facebook → Telegram）。

每条 `items[]`：

| 字段 | 说明 |
| --- | --- |
| `platform` / `platform_label` | 与任务模型 `binding_platform` 一致 |
| `linked` | 是否存在该平台的 **已录用** 账号绑定类报名 |
| `display_name` / `bound_username` | 展示用；已绑定时优先 `bound_username` |
| `reward_hint` | 若当前存在对应平台的开放必做绑定任务，展示如 `+2 TH` |
| `task` | 未开放必做任务时为 `null`；否则含 `id` / `title` / `reward_usdt` / `reward_th_coin` / `verify_path_suffix`（用于拼接 `POST .../me/applications/{id}/verify-xxx/`） |

---

#### 2.8.5 通知设置（占位）— `GET|PATCH /api/v1/me/settings/notifications/`

**GET** 返回布尔开关；**PATCH** 当前仅回显请求体，**未写入数据库**（后续可挂 `FrontendUser` 字段）。

## 3. 分类接口

### 3.1 分类列表

- `GET /api/v1/categories/`

返回 `items` 为任务分类数组。

## 4. 任务接口

### 4.0 必做任务列表（首页「必做」卡片）

与 `GET /api/v1/tasks/` 使用同一套 `task` 序列化字段；仅筛选 **`is_mandatory=true` 且 `status=open`**，按 `task_list_order` 降序。已登录时：**仅当**当前用户对该任务为 **`accepted` 且已结奖（`reward_paid_at`）或任务无正数展示奖励** 时本条才从列表剔除；**已录用但未发奖**仍出现在列表中并带 `my_application`，便于继续完成校验。

- `GET /api/v1/tasks/mandatory/`
- **可不登录**。若带 Bearer，则每条任务会多返回 `my_application`（当前用户对该任务的报名，无则为 `null`）。

**前端「开始」按钮**：调用 **`POST /api/v1/tasks/{task_id}/apply/`**（需登录），必做卡片可在 body 里带：

- 账号绑定类（`interaction_type=account_binding`）：`bound_username`（如推特 handle、TikTok 用户名）。**Twitter（`binding_platform=twitter`）与 TikTok（`binding_platform=tiktok`）时 `bound_username` 必填**（推特不含 `@`；TikTok 可传用户名或 `tiktok.com/@…` 链接以便解析）。
- 加入社群类（`interaction_type=join_community`）：`interaction_config` 须含 **`invite_link` 或 `telegram_invite_link`**（用户点开的入群链接）。若还配置了 **`telegram_chat_id`**（或 **`telegram_group_id`**，超级群一般为 `-100…`），且未将 **`require_telegram_member`** 设为 `false`，则任务详情中会多返回 **`interaction_verify_action`**：`"verify-telegram-group"`，用户入群后需 **`POST /api/v1/me/applications/{application_id}/verify-telegram-group/`** 完成自动校验（用户须已用 **Telegram 登录** 本产品，且与本站使用同一 **`TELEGRAM_BOT_TOKEN`** 的 Bot 已加入该群并具有查看成员权限）。

**Twitter 绑定 + 自动校验转发/关注**：用户在站外完成操作后，调用 **`POST /api/v1/me/applications/{application_id}/verify-twitter/`**（需登录，body 可省略或再传 `bound_username` 以补全）。服务端使用环境变量 **`TWITTER_BEARER_TOKEN`**（X API v2 只读 Bearer）拉取官方接口；校验通过后**自动将报名置为已录用**（与发布人手点「通过」等效）。任务 `interaction_config` 示例：`{"target_tweet_url":"https://x.com/…/status/数字ID","require_retweet":true}`；若还要校验关注，可加：`"require_follow": true, "target_follow_username": "官方用户名"`。

**TikTok 绑定 + 自动校验「转发指定视频」**：用户转发后台配置的短视频后，调用 **`POST /api/v1/me/applications/{application_id}/verify-tiktok/`**（需登录）。服务端使用 **`APIFY_API_TOKEN`** 调用默认 Actor **`clockworks/tiktok-scraper`**，抓取该用户主页 **Reposts** 分区，匹配视频链接中的 **`/video/数字ID`**。任务 `interaction_config` 示例：`{"target_video_url":"https://www.tiktok.com/@官方号/video/7123456789012345678","require_repost":true}`（键名亦支持 `tiktok_video_url`；若省略 `require_repost` 且配置了视频 URL，则默认要校验转发）。可选环境变量 / `apify_secrets.py`：**`APIFY_TIKTOK_ACTOR_ID`**、**`APIFY_TIKTOK_TIMEOUT_SEC`**、**`APIFY_TIKTOK_RESULTS_PER_PAGE`**。

### 4.0.1 任务中心页（Tab + 必做任务 + 可用任务，推荐前端对接）

与产品「任务中心」一页拉齐数据，避免多次请求拼装。

- **`GET /api/v1/tasks/center/`**
- **可不登录**。若带 Bearer，`mandatory.items` 与 `available.items` 里每条任务可带 **`my_application`**（逻辑同 **§4.0**）。

**查询参数（均可选；作用于「可用任务」列表，必做区不受分页参数影响）**

| 参数 | 说明 |
| --- | --- |
| `category_id` | 任务分类 ID；不传或理解为「全部」时不筛选。**首项「全部」**也可用 `data.categories` 里 `slug=all` 的项对应（不传即全部分类）。 |
| `keyword` | 标题或描述模糊搜索 |
| `binding_platform` | 与 **§4.1.1** 一致：`twitter` / `tiktok` / `youtube` / `instagram` / `facebook` / `telegram`，用于顶部 **X / TikTok / YouTube** 等 Tab；只保留 `binding_platform` 与该值一致的任务（多为账号绑定类）。 |
| `page` | 可用任务页码，默认 `1` |
| `page_size` | 可用任务每页条数，默认 `20`，最大 `50` |

**成功时 `data` 结构**

| 字段 | 说明 |
| --- | --- |
| `categories` | 数组：**首条为虚拟「全部」**（`id: null`, `slug: "all"`, `is_all: true`），其后为后台「任务分类」启用的分类（同 `GET /api/v1/categories/` 单条结构）。 |
| `mandatory` | 对象：`items` 与 **`GET /api/v1/tasks/mandatory/`** 一致（必做、`status=open`；**仅**当前用户对该任务为 **`accepted` 且已结奖或无应付奖励** 时才剔除，接了未完成仍返回卡片并带 `my_application`）；`updated_at` 为服务端生成快照时间（ISO8601）。 |
| `available` | 对象：`items` 为 **非必做**（`is_mandatory=false`）且 **`status=open`** 的任务；`pagination`；`updated_at`。排序：按任务 **`updated_at` 降序**（便于「更新于 x 分钟前」）。 |

**任务对象在以上接口中，在通用 `task` 字段（见 **§4.3**）基础上额外包含（卡片 UI）：**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `platform_key` | string | 用于 Tab 高亮 / 平台图标：`twitter`、`tiktok`、`youtube`、`instagram`、`facebook`、`telegram`、`other` 等；优先自 `binding_platform`，入群类为 `telegram`，否则尝试分类 `slug`。 |
| `accepted_count` | number | 已录用（`accepted`）报名人数 |
| `slot_progress_percent` | number 或 `null` | **名额占用进度** \(min(100, accepted_count × 100 ÷ applicants_limit)\)，用于「当前进度」进度条；`applicants_limit` 为 0 或未配置时为 `null` |
| `application_count` | number | 总报名人数（**「x 人参与」**建议用此字段） |

**说明**：`slot_progress_percent` 表示**任务名额**被占满的比例，不是单个用户个人完成度；个人进度需结合 `my_application.status` 等自行判断。

### 4.1 任务列表

- `GET /api/v1/tasks/`

支持查询参数：

- `status`: 任务状态（`draft/open/in_progress/completed/closed`）
- `category_id`: 分类 ID
- `binding_platform`: 绑定平台筛选，取值同 **§4.1.1**（`twitter` / `tiktok` / …）；与 **§4.0.1** 任务中心 Tab 一致
- `keyword`: 标题或描述关键词
- `mine`: `published` 或 `applied`（需登录）
- `page`: 页码（默认 1）
- `page_size`: 每页条数（默认 20，最大 50）

列表单项默认**不含** `platform_key` / `slot_progress_percent`；若需与任务中心卡片一致，请使用 **`GET /api/v1/tasks/center/`** 或 **`GET /api/v1/tasks/mandatory/`**（必做已含扩展字段）。

### 4.1.1 任务类型：前端如何区分（`interaction_type` + `binding_platform`）

**`GET /api/v1/tasks/`、`GET /api/v1/tasks/mandatory/`、`GET /api/v1/tasks/{task_id}/`** 返回的 **`task`** 对象中，用于区分「绑定推特 / TikTok / YouTube / Ins / Facebook / Telegram **账号**」与「加入 Telegram **群/频道**」等，**不要**依赖单一字段，请按下表用 **`interaction_type`** 与 **`binding_platform`** 组合判断（与后台「必做任务类型」「绑定平台」一致）。

| 前端要识别的场景 | 判断条件（代码里用英文 code 比较） |
| --- | --- |
| 绑定 Twitter / X | `interaction_type === "account_binding"` **且** `binding_platform === "twitter"` |
| 绑定 TikTok | `interaction_type === "account_binding"` **且** `binding_platform === "tiktok"` |
| 绑定 YouTube | `interaction_type === "account_binding"` **且** `binding_platform === "youtube"` |
| 绑定 Instagram | `interaction_type === "account_binding"` **且** `binding_platform === "instagram"` |
| 绑定 Facebook | `interaction_type === "account_binding"` **且** `binding_platform === "facebook"` |
| 绑定 Telegram **账号**（个人账号类绑定，**不是**入群任务） | `interaction_type === "account_binding"` **且** `binding_platform === "telegram"` |
| 加入社群 / Telegram **入群、频道** | `interaction_type === "join_community"`。此类任务后端会清空 **`binding_platform`**，**不要用** `binding_platform` 判断入群；入群链接与群 ID 在 **`interaction_config`**（如 `invite_link` / `telegram_invite_link`、`telegram_chat_id`） |
| 其它玩法 | 见下表 **`interaction_type`** 枚举 |

**`interaction_type` 取值（接口与数据库枚举一致）**

| 值 | 含义 |
| --- | --- |
| `none` | 不按必做交互规则（传统悬赏等） |
| `account_binding` | 账号绑定；**具体平台必须再看** `binding_platform` |
| `join_community` | 加入社群（如 Telegram 入群/频道） |
| `follow` | 关注 |
| `comment` | 评论 |
| `watch_video` | 观看视频 |
| `external_vote` | 外部网页投票 |

**`binding_platform` 取值**（**仅当** `interaction_type === "account_binding"` 时有意义；其它类型一般为 `null` 或空字符串）

`twitter` · `youtube` · `instagram` · `tiktok` · `facebook` · `telegram`

**展示用中文**：同一对象中的 **`interaction_type_display`**、**`binding_platform_display`** 可直接给 UI；**路由与分支逻辑请始终用** `interaction_type`、`binding_platform` **英文值**。

**校验动作（由后端根据任务配置计算，前端据此调对应接口）**

- **`binding_verify_action`**：账号绑定类需要用户调用的校验，如 `verify-twitter`；无则为 `null`。
- **`interaction_verify_action`**：非「账号绑定」类、但需要用户主动调接口的校验，如入群 **`verify-telegram-group`**；无则为 `null`。

详见上文 **§4.0** 与各 **`POST …/verify-*/`** 小节。

### 4.2 创建任务

- `POST /api/v1/tasks/`
- 需要 Bearer Token，且 **Token 必须属于「平台发布人」前台用户**（`core/settings.py` 中的 `TASK_PLATFORM_PUBLISHER_ID`，可用环境变量 `TASK_PLATFORM_PUBLISHER_ID` 覆盖；默认 `1`）
- 请求体 **不要**、也 **不能** 指定 `publisher`：后端一律写入上述平台用户

请求体示例：

```json
{
  "title": "设计一个活动海报",
  "description": "需要 2 天内交付 PSD 和 PNG",
  "budget": "800.00",
  "reward_unit": "CNY",
  "deadline": "2026-04-20T18:00:00+08:00",
  "region": "上海",
  "applicants_limit": 1,
  "contact_name": "张三",
  "contact_phone": "13800138000",
  "category_id": 1,
  "status": "open",
  "interaction_type": "none",
  "binding_platform": "",
  "verification_mode": null,
  "interaction_config": {}
}
```

**必做任务（可选）**：`interaction_type` 取值 `none`（默认）、`account_binding`、`join_community`、`follow`、`comment`、`watch_video`、`external_vote`。账号绑定时须带 `binding_platform`：`twitter` / `youtube` / `instagram` / `tiktok` / `facebook` / `telegram`。**加入 Telegram 群**须配 `invite_link` / `telegram_invite_link`；若需服务端校验在群内，再加 `telegram_chat_id`。`verification_mode` 可省略，后端会按类型给默认；也可显式传 `user_self_confirm`、`profile_link_proof`、`screenshot_review`。`interaction_config` 示例：推特 `{"target_tweet_url":"https://…/status/123","require_retweet":true,"require_follow":false,"target_follow_username":""}`（`require_retweet` 省略且配置了 `target_tweet_url` 时默认 `true`）；TikTok `{"target_video_url":"https://www.tiktok.com/@…/video/数字ID","require_repost":true}`；YouTube `{"youtube_proof_link":"https://…"}`；入群校验 `{"invite_link":"https://t.me/+xxxx","telegram_chat_id":"-1001234567890"}`。

**任务详情/列表中的校验字段**：`binding_verify_action` 仅用于 **账号绑定**（如 `verify-twitter`）；**`interaction_verify_action`** 用于其它需用户主动调接口的自动校验（当前为 **`verify-telegram-group`**，对应加入群任务）。无校验时为 `null`。

### 4.3 任务详情

- `GET /api/v1/tasks/{task_id}/`

返回的 **`task`** 字段与列表一致；**如何区分绑定推特 / TikTok / YouTube / Ins / 入群等**，见 **§4.1.1**。

### 4.4 更新任务

- `PATCH /api/v1/tasks/{task_id}/`
- 需要 Bearer Token，且必须是任务发布人（即平台发布人账号，与创建时写入的 `publisher` 一致）

可更新字段：

- `title`
- `description`
- `budget`
- `reward_unit`
- `deadline`
- `region`
- `applicants_limit`
- `contact_name`
- `contact_phone`
- `status`
- `category_id`
- `interaction_type`
- `binding_platform`
- `verification_mode`
- `interaction_config`

### 4.5 排行模块（排行榜页）

对接产品「排行」Tab：**顶部全站统计**与 **§4.5.1** 一致（全网数据）；**佣金榜**按个人做任务获得的 **USDT**（钱包 **`task_reward`** 累计）排行；**邀请榜**仅按 **直接邀请人数** 排行；邀请统计区 / 底栏「我的」为**当前登录用户**数据。金额字段均为 **USDT 字符串**（两位小数）；前端可映射为 ¥ 展示。

**环境变量 / `settings`（可选）**

| 变量 | 说明 |
| --- | --- |
| `TELEGRAM_BOT_USERNAME` | Bot 用户名（**无** `@`）。若配置，**优先**生成 Foxi 式链接：`https://t.me/{username}?start={TELEGRAM_INVITE_START_PREFIX}{邀请人 telegram_id 或 invite_code}`（邀请人已绑定 Telegram 时用数字 id，否则用邀请码）。 |
| `TELEGRAM_INVITE_START_PREFIX` | 默认 `ref_`；与 `?start=` 拼接在 id/码前。 |
| `TELEGRAM_MINI_APP_SHORT_NAME` | 可选；与 `TELEGRAM_BOT_USERNAME` 同时配置时，`invite_link` 会多返回 **`mini_app_url`**：`https://t.me/{bot}/{short}?startapp={invite_code}`，便于用户在 **Mini App** 内登录时 `initData.start_param` 仍带邀请码（`?start=` 先打开 Bot 对话，不会自动把参数交给 WebApp，需 Bot 菜单/按钮再打开 Mini App）。 |
| `INVITE_LINK_BASE_URL` | **未**配置 `TELEGRAM_BOT_USERNAME` 时使用：邀请落地页前缀，**勿**尾斜杠。例 `https://task.example.com`；未配置时 `invite_link.full_url` 为当前站点绝对路径 `/invite/{invite_code}`。 |
| `INVITE_COMMISSION_RATE` | 默认 `0.10`；用于「预计收益」估算与 `commission.label` 文案。 |
| `PLATFORM_STATS_ANCHOR_DATE` | `YYYY-MM-DD`，全站「运营天数」起点；不设则取库内最早用户/任务创建日。 |

#### 4.5.1 全站统计（顶部四卡）

- `GET /api/v1/rankings/platform-stats/`
- **可不登录**

`data`：

| 字段 | 说明 |
| --- | --- |
| `total_tasks` | 任务总数（不含 `draft`） |
| `total_rewards_issued_usdt` | 全站 **`task_reward`** 账变 USDT 正数合计（备注不含 `TH Coin`） |
| `total_users` | 启用用户 `status=true` 人数 |
| `operating_days` | 运营天数（见上表锚点） |
| `currency_display_hint` | 提示前端可自行映射 ¥ |

#### 4.5.2 佣金榜（做任务获得的 USDT 排行）

- **主路径**：`GET /api/v1/rankings/commission-leaderboard/`
- **兼容**：`GET /api/v1/rankings/task-leaderboard/`（与主路径返回相同，便于旧前端）
- **可不登录**

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `page` | 1 |  |
| `page_size` | 20，最大 50 |  |

`data.leaderboard_type` 固定为 `task_commission_usdt`。`data.items[]`：`rank`、`id`、`username`、`membership_level`、`avatar_url`（暂 `null`）、**`task_commission_usdt`**（该用户钱包 **`task_reward`** USDT 正数合计）、**`completed_tasks`**（已录用报名数，便于 UI 副文案）。`pagination` 含 `has_more`。

#### 4.5.3 邀请榜

- `GET /api/v1/rankings/invite-leaderboard/`
- **可不登录**

参数同 **§4.5.2**。`items[]`：`rank`、`invited_count`（**有效**下级 `status=true` 人数）、`id`、`username`、`membership_level`、`avatar_url`。

#### 4.5.4 邀请统计区 + 我的排名摘要（合并）

- `GET /api/v1/me/ranking/invite-overview/`
- **兼容**：`GET /api/v1/me/rankings/invite-overview/`（同义）
- 需要 Bearer Token

`data.invite`：`total_invited`、`referral_credited_usdt`（当前用户钱包 **`change_type=reward`** 且 USDT 正数累计）、`referral_estimated_display_usdt`（在已入账推荐奖励基础上，叠加「下级 `task_reward` USDT 累计 × `INVITE_COMMISSION_RATE`」的**展示用**估算）、`commission`（`decimal` / `percent` / `label`）、`note`（字段含义说明）。

`data.invite_link`：`invite_code`、`path`、`full_url`（复制用）、`link_style`（`telegram_bot_start` / `custom_base` / `site_absolute`）、`start_param`（仅 Bot 深链形态时有，即 `?start=` 的值）。若配置了 `TELEGRAM_MINI_APP_SHORT_NAME`，另有 **`mini_app_url`**（直接打开 Mini App 并带 `startapp=`）。

`data.me`：`user`（公开卡片字段）、`invite`（`rank` / `invited_count` / `surpassed_users_percent`）、`task`（按**已录用任务数**的全站名次：`rank` / `completed_tasks` / `surpassed_users_percent`）、**`commission`**（按 **`task_reward` USDT 累计** 的佣金榜名次：`rank` / `task_commission_usdt` / `surpassed_users_percent`）、`total_contribution_usdt`（推荐奖励 USDT 累计，与 `referral_credited_usdt` 一致，底栏「总贡献」语境）。

#### 4.5.5 我的邀请明细分页

- `GET /api/v1/me/ranking/invitees/`
- **兼容路径**（与上相同处理）：`GET /api/v1/me/rankings/invitees/`（复数 `rankings`，避免与全站 `rankings/` 混淆时误配前端）
- 需要 Bearer Token

| 参数 | 说明 |
| --- | --- |
| `page` / `page_size` | 同其它分页，最大 50 |

`data`：`total_invited`、`items[]`（`id`、`username`、`membership_level`、`avatar_url`、`completed_tasks`、`contribution_commission_usdt`、`commission_label`、`joined_at`）、`pagination`、`commission_note`（**分摊展示**说明：按全下级已完成任务数占比分摊您钱包内推荐奖励 USDT，非链上真实分笔）。

#### 4.5.6 排行底栏（仅我的条）

- `GET /api/v1/me/ranking/context/`
- **兼容**：`GET /api/v1/me/rankings/context/`
- 需要 Bearer Token

`data`：`user`、`task`、`commission`、`invite`、`total_contribution_usdt`（含义同 **§4.5.4**）。可与 **§4.5.1** 分请求组合，减轻单包体积。

## 5. 报名接口

### 5.1 报名任务

- `POST /api/v1/tasks/{task_id}/apply/`
- 需要 Bearer Token

请求体示例：

```json
{
  "proposal": "我有 5 年相关经验，明晚可交初稿。",
  "quoted_price": "760.00",
  "bound_username": "my_twitter_handle"
}
```

`bound_username`：非 Twitter/TikTok 绑定时可选；**`binding_platform=twitter` 或 `tiktok` 的账号绑定任务必填**（Twitter 不含 `@`；TikTok 可用户名或主页链接）。**同一用户重复 `POST` 报名同一任务**：

- 报名仍为 **`pending`**：幂等同步 body 字段（便于多步页多次点「下一步」）。
- 已为 **`accepted`** 且**已发奖或无应付展示奖励**：返回成功，提示「您已完成该任务」。
- 已为 **`accepted`** 但未结奖、任务仍为 **`open`**、且**尚未产生进度**（无 `self_verified_at`、无 `proof_image`）：将本条报名**重置为 `pending`** 并同步 body，便于任务失效/关单后重新开放时**再次接取**；若已有自检时间或截图凭证，则返回 **409**（`code=4100`），请继续完成校验或等待审核，避免误清凭证。
- **`cancelled`**：若任务当前为 **`open`**、且接取人数未满，同样**重置为 `pending`** 后可再次接取；任务不可报名时仍为 **409**（`code=4093`）。
- **`rejected`**：仍不可再次报名（**409**，`code=4036`）。
- 已接取未完成且任务**已不可报名**：**409**（`code=4097`），待后台将任务重新设为可报名后再 `POST`。

截图凭证目前请在后台「任务报名」中上传 `proof_image`（后续可再接 API 上传）。

### 5.2 校验 Twitter 绑定并完成（用户）

- `POST /api/v1/me/applications/{application_id}/verify-twitter/`
- 需要 Bearer Token，且报名 `applicant` 须为当前用户；报名状态须为 `pending`。

请求体（可选）：

```json
{
  "bound_username": "handle_without_at"
}
```

若报名记录里已有 `bound_username` 可省略 body。服务端根据任务的 `interaction_config` 调用 X API：**转发**（`target_tweet_url` + `require_retweet`）、**关注**（`require_follow` + `target_follow_username`）可单独或同时开启。需配置服务端 **`TWITTER_BEARER_TOKEN`**，否则返回 `503` 与提示文案。成功时返回 `application` 对象（`status` 一般为 `accepted`，`self_verified_at` 有值）。

### 5.2.1 校验 YouTube 绑定并完成（用户）

- `POST /api/v1/me/applications/{application_id}/verify-youtube/`
- 需登录；`interaction_config` 中可配置 `youtube_proof_link`，服务端抓取频道 about 页做子串匹配。

### 5.2.2 校验 Instagram 绑定并完成（用户 · Apify）

- `POST /api/v1/me/applications/{application_id}/verify-instagram/`
- 需登录；任务 `interaction_config` 中可配置 `instagram_proof_link`（或 `proof_link` / `profile_proof_link`）。

**服务端**：在 **`APIFY_API_TOKEN`**（或 `core/apify_secrets.py`）中配置 Apify API Token；可选 **`APIFY_INSTAGRAM_ACTOR_ID`**（默认 `apify/instagram-profile-scraper`）、**`APIFY_INSTAGRAM_TIMEOUT_SEC`**。任务含证明链接时**仅**通过 Apify 校验；**未配置 Token** 时接口返回 `503`（`code=4210`），`message` 为「校验服务暂不可用，请稍后再试。」（不对用户暴露配置细节）。

**用户侧**：报名并填写 `bound_username` 后，在简介/网站中粘贴与后台一致的证明链接，再 `POST verify-instagram/`（body 可再传 `bound_username`）。无需 Meta OAuth 流程。

自检：`GET /api/v1/health/` 中 **`instagram_apify_configured`** 为 `true` 表示当前进程已加载 Apify Token。

### 5.2.3 校验 TikTok 绑定并完成（用户 · Apify Reposts）

- `POST /api/v1/me/applications/{application_id}/verify-tiktok/`
- 需登录；任务须为 `interaction_type=account_binding` 且 `binding_platform=tiktok`，报名为 `pending`。

请求体（可选，与推特一致可再传 `bound_username`）：

```json
{
  "bound_username": "tiktok_handle_or_profile_url"
}
```

**服务端**：配置 **`APIFY_API_TOKEN`**（与 Instagram 校验共用）；可选 **`APIFY_TIKTOK_ACTOR_ID`**（默认 `clockworks/tiktok-scraper`）、超时与抓取条数见 settings。**未配置 Token** 时返回 `503`（`code=4228`），`message` 为「校验服务暂不可用，请稍后再试。」。

**用户侧**：先转发任务 `interaction_config` 中的 **`target_video_url`**（或 **`tiktok_video_url`**）所指向的视频，再调用本接口；服务端在用户 **Reposts** 列表中查找是否出现同一 **`/video/数字ID`**。

自检：`GET /api/v1/health/` 中 **`tiktok_apify_configured`** 与 Instagram 一样依赖是否已加载 Apify Token。

**前端静态封装（可选）**：仓库内 `frontend/static/frontend/js/tiktokBindingTaskApi.js` 暴露 `window.TaskhubTikTokBinding`（`apply` / `verify`），用法与推特脚本 `twitterBindingTaskApi.js` 的 `TaskhubTwitterBinding` 对称；实际 Mini App / H5 也可直接 `fetch` 上述路径。

### 5.2.4 校验已加入 Telegram 群并完成（用户 · Bot getChatMember）

- `POST /api/v1/me/applications/{application_id}/verify-telegram-group/`
- 需登录；任务须为 **`interaction_type=join_community`**，且任务 JSON 中已配置 **`telegram_chat_id`**（或 `telegram_group_id`），且 **`require_telegram_member` 不为 `false`**；报名为 `pending`。

请求体可为空 `{}`。

**服务端**：使用与 Mini App 登录相同的 **`TELEGRAM_BOT_TOKEN`** 调用 Telegram **`getChatMember`**；**该 Bot 必须先被拉入目标群/频道**，并具备查看成员等必要权限。**当前用户须有 `telegram_id`**（即曾通过 `POST /api/v1/auth/telegram/` 登录过）。未配置 Token 时返回 `503`（`code=4317`）。

**用户侧**：用 `binding_reference_url` 中的邀请链接在 Telegram 客户端入群后，再调用本接口。

自检：`GET /api/v1/health/` 中 **`telegram_bot_configured`** 为 `true` 表示已加载 Bot Token。

### 5.3 查看任务报名列表（发布人）

- `GET /api/v1/tasks/{task_id}/applications/`
- 需要 Bearer Token，且必须是任务发布人

### 5.4 审核报名（发布人）

- `PATCH /api/v1/applications/{application_id}/`
- 或 `POST /api/v1/applications/{application_id}/`
- 需要 Bearer Token，且必须是任务发布人

请求体：

```json
{
  "status": "accepted"
}
```

`status` 允许值：

- `accepted`
- `rejected`
- `cancelled`

## 6. 我的任务

### 6.1 我发布的任务

- `GET /api/v1/me/published-tasks/`
- 需要 Bearer Token

### 6.2 我报名的任务

- `GET /api/v1/me/applied-tasks/`
- 需要 Bearer Token

### 6.3 任务记录（Mini App「任务记录」页）

- `GET /api/v1/me/task-records/`
- 需要 Bearer Token

面向 **当前登录用户** 的报名记录列表，与 UI 上 **全部 / 进行中 / 审核中 / 已完成 / 已失效** 五个 Tab 对齐；时间文案与奖励展示格式便于直接绑定列表卡片。

#### 6.3.1 查询参数

| 参数 | 说明 |
| --- | --- |
| `record_status` | 可选；不传或 `all` = 全部。其它取值见下表（也可用兼容参数 **`tab`**，语义相同）。 |
| `page` | 默认 `1` |
| `page_size` | 默认 `20`，最大 `50` |

**`record_status`（与 Tab 对应）**

| 取值 | Tab |
| --- | --- |
| `all` | 全部 |
| `in_progress` | 进行中 |
| `under_review` | 审核中 |
| `completed` | 已完成 |
| `invalid` | 已失效 |

**服务端归类规则（与列表筛选一致）**

- **已失效**：报名为 `rejected` / `cancelled`；或 **`pending`** 但任务已非「可继续」状态（任务非 `open` / `in_progress`）；或 **`accepted`**、仍有应付展示奖励、尚未 `reward_paid_at`、且任务为 `closed` / `draft`。
- **已完成**：**`accepted`** 且（已写入 **`reward_paid_at`**，或任务未配置正数 **`reward_usdt` / `reward_th_coin`**，视为无需发奖即完结）。
- **审核中**：**`pending`** 且任务仍为 `open` / `in_progress`（待发布人处理报名）；或 **`accepted`**、校验方式为 **上传截图待审核**、已上传 **`proof_image`**、仍有应付奖励且尚未入账。
- **进行中**：其余 **`accepted`** 且未归入上两类的情况（例如已录用待用户完成 / 待自动校验等）。

若传非法 `record_status`，返回 **HTTP 400**，`code=4070`。

#### 6.3.2 成功时 `data`

| 字段 | 说明 |
| --- | --- |
| `items` | 列表项数组，见下表 |
| `pagination` | `page`、`page_size`、`total`、`has_more`（是否还有更早记录，对应「加载更多」） |

**`items[]` 每项**

| 字段 | 说明 |
| --- | --- |
| `id` | 报名记录 ID（`TaskApplication.id`） |
| `task_id` | 任务 ID |
| `title` | 任务标题 |
| `platform_key` | 与 **`GET /api/v1/tasks/center/`** 卡片一致：`youtube` / `twitter` / `telegram` / `tiktok` 等，用于本地图标映射 |
| `icon_url` | 目前固定为 **`null`**（由前端按 `platform_key` 映射资源） |
| `record_status` | `in_progress` / `under_review` / `completed` / `invalid` |
| `record_status_display` | 中文：`进行中` / `审核中` / `已完成` / `已失效` |
| `rewards` | `{"usdt": "+0.022 USDT" \| null, "th_coin": "+0.10 TH" \| null}`，与任务上展示奖励一致；无则对应键为 `null` |
| `time` | `label`（`更新时间` / `提交时间` / `完成时间`）、`at`（ISO8601）、`display`（`YYYY-MM-DD HH:mm`，服务器 `TIME_ZONE`） |

## 7. 新手指南 API

数据来自 **`announcements.Announcement`**：后台 **公告与指南** 中把 **内容类型** 设为 **新手指南**（`post_type=newbie_guide`），正文用 **TinyMCE 富文本**（`content` 字段）；**分类**在 **`announcements.GuideCategory`**（后台「新手指南 → 指南分类」）维护，指南里用外键选用。接口前缀仍为 **`/api/v1/guides/`**，**无需登录**。返回结构与 TaskHub 一致：`{ "code", "message", "data" }`。

### 7.1 分类 Tab

- `GET /api/v1/guides/categories/`

`data.items`：首条为虚拟 **全部指南**（`id=0`, `slug=""`），其后为后台启用的 **`GuideCategory`**（按 `sort_order`）；若仍有历史数据仅填写旧字段 **`category_key`** 而未挂外键，也会追加到 Tab（slug 与后台分类不重复时）。前端用 `slug` 调下列表接口的 `category_slug`；空字符串表示不按分类筛选。

### 7.2 置顶大卡（必看视频位）

- `GET /api/v1/guides/featured/`

`data.item`：优先返回 **`is_featured=true`** 且已发布的一条；若无，则取最新 **`guide_type=video`**；再无则取任意最新已发布。可能为 `null`（尚无内容）。

### 7.3 列表（搜索 + 分页）

- `GET /api/v1/guides/`

| 参数 | 说明 |
| --- | --- |
| `category_slug` | 与 **`GuideCategory.slug`** 或旧版 **`category_key`** 一致；不传或空=全部 |
| `guide_type` | `article` / `video`；不传=不限 |
| `search` | 标题、摘要、正文模糊匹配 |
| `exclude_featured` | 默认 `1`：列表中排除置顶，避免与 `/featured/` 重复；传 `0` 可包含 |
| `page` | 默认 1 |
| `page_size` | 默认 20，最大 50 |

`data.items`：每条为列表项结构（**无** `body` 大字段）。`data.pagination`。

### 7.4 详情

- `GET /api/v1/guides/{id}/`

仅 **`is_active=true`** 且在发布/过期时间窗内可见。成功后会 **`view_count` +1** 并返回最新计数。`data.guide` 含完整 **`body`**（与后台 **正文** 同源，为 **HTML 富文本**）。

### 7.5 列表项 / 详情字段说明

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `title` / `slug` | 标题与 URL 标识 |
| `excerpt` | 列表副文案，可 null |
| `guide_type` | `article` 图文 / `video` 视频 |
| `cover_url` | 封面图 URL，可 null |
| `video_url` | 播放地址：后台若上传了视频文件则为 **媒体绝对 URL**；否则为外链；`video` 类型使用 |
| `duration_display` | 如 `12:45`，纯展示 |
| `read_minutes` | 约读分钟 |
| `view_count` | 浏览量 |
| `is_featured` | 是否置顶推荐 |
| `author_name` | 作者展示名 |
| `published_at` | ISO8601，可 null |
| `category` | `{ id, name, slug }` 或 null |
| `body` | **仅详情接口**返回 |

---

## 8. 文档与健康检查

- **`GET /docs/taskhub-api/`**：**完整 HTML 接口文档页**（独立页面；正文为本文 + **第 9 节接口速查表**，速查表由 `taskhub/api_endpoints.py` 实时生成，无需手改表格）
- **`GET /docs/`**：重定向到 **`/docs/taskhub-api/`**（避免前端误请求根路径 `/docs/` 出现 404）
- **`GET /openapi.json`**：返回带 `endpoints` 的发现用 JSON（与 `GET /api/v1/docs/` 同源列表；**非**完整 OpenAPI paths，仅供工具探测）
- `GET /api/v1/docs/`：接口目录（JSON，与速查同源；含 `doc_page_url`、`doc_sync_command`）
- `GET /api/v1/health/`：服务健康检查；`data` 中含 **`instagram_apify_configured`**、**`tiktok_apify_configured`**、**`telegram_bot_configured`** 等布尔开关，便于前端判断校验能力是否就绪。

**部署 / 拉代码后务必执行数据库迁移**（否则会出现 `Unknown column 'frontend_user.telegram_id'` 等 500）：

```bash
python manage.py migrate
```

若曾中断迁移导致 **`task_check_in` 表已存在** 但 Django 未记录 `taskhub.0004`，可执行（慎用，确认表结构已是签到表后再 fake）：

```bash
python manage.py migrate taskhub 0004 --fake
```

**MySQL 报错 `OperationalError (1785)`（GTID 与 MyISAM 混用）**：签到、钱包等接口若在终端出现该错误，请在库里把 Django 系统表改为 InnoDB（与业务表一致），例如：

```sql
ALTER TABLE django_admin_log ENGINE=InnoDB;
ALTER TABLE django_session ENGINE=InnoDB;
```

代码侧已对 `Wallet.save(create_transaction=False)` 去掉多余嵌套事务以降低触发概率；若仍报 1785，以上 ALTER 为根治。

维护约定：**新增对外接口时**请同时改路由（`core/urls.py` 或 `taskhub/api_urls.py`）、实现视图、更新 **`taskhub/api_endpoints.py`** 中的 `PUBLIC_ENDPOINTS`，并补充上文各节的请求/响应说明（若需要）。可选执行 `python manage.py sync_taskhub_api_docs` 把第 9 节写回本文件便于提交仓库。

<!-- API_QUICKREF_BEGIN -->
## 9. 接口速查（自动生成）

> 数据源：`taskhub/api_endpoints.py`。开放 HTML 文档页会附带本表最新内容。
> 若需把本表写进仓库中的 `docs/taskhub_api.md`，请执行：`python manage.py sync_taskhub_api_docs`

| 方法 | 路径 | 说明 | 需登录 |
| --- | --- | --- | --- |
| GET | `/api/v1/health/` | 服务健康检查 | 否 |
| GET | `/api/v1/docs/` | 接口目录（JSON） | 否 |
| POST | `/api/v1/auth/register/` | 用户注册并返回 token | 否 |
| POST | `/api/v1/auth/login/` | 用户登录并返回 token | 否 |
| GET / POST | `/api/v1/auth/telegram/` | Telegram 登录：POST init_data；可选 include_home；start_param/ref 绑定 referrer（见文档 §2.5）；GET 说明；另见 POST /api/auth/telegram/ | 否 |
| GET / POST | `/api/v1/telegram/miniapp-login/` | Telegram 登录别名，与 auth/telegram/ 相同 | 否 |
| POST | `/api/v1/auth/logout/` | 退出登录 | 是 |
| GET | `/api/v1/me/home/` | 首页聚合（用户/钱包/累计收益/签到周历） | 是 |
| GET | `/api/v1/me/center/` | 个人中心聚合（等级/排名/最近收益/提现规则/外链/含 check_in） | 是 |
| GET | `/api/v1/me/rewards/ledger/` | 收益与账单明细（钱包账变分页；summary 为累计入账） | 是 |
| GET / POST | `/api/v1/me/withdrawals/` | 提现：GET 记录与汇总；POST 发起（扣 USDT、BEP20 地址） | 是 |
| GET | `/api/v1/me/bindings/accounts/` | 账号管理：各平台绑定状态与开放必做绑定任务 | 是 |
| GET / PATCH | `/api/v1/me/settings/notifications/` | 通知设置（占位，PATCH 暂未持久化） | 是 |
| GET / POST | `/api/v1/me/check-in/` | 签到：GET 周历+规则；POST 今日签到（发奖，data 含 last_granted） | 是 |
| POST | `/api/v1/me/check-in/make-up/` | 补签：body.date；先扣 makeup TH，再发与签到相同奖励；data 可有 last_spent/last_granted | 是 |
| GET | `/api/v1/me/profile/` | 当前登录用户信息 | 是 |
| GET | `/api/v1/categories/` | 任务分类列表 | 否 |
| GET | `/api/v1/guides/categories/` | 新手指南：分类 Tab（GuideCategory + 兼容旧 category_key；含虚拟「全部」） | 否 |
| GET | `/api/v1/guides/featured/` | 新手指南：置顶大卡/首条推荐（Announcement post_type=newbie_guide） | 否 |
| GET | `/api/v1/guides/` | 新手指南：列表（category_slug=外键 slug 或旧 key；guide_type；分页；正文在详情） | 否 |
| GET | `/api/v1/guides/{pk}/` | 新手指南：详情（body=富文本 HTML；video_url 优先本地上传地址） | 否 |
| GET | `/api/v1/tasks/mandatory/` | 首页必做（open+is_mandatory）；仅已录用且已结奖/无奖励时对当前用户隐藏 | 否 |
| GET | `/api/v1/tasks/center/` | 任务中心：分类 Tab + 必做 + 可用；必做区剔除规则同 tasks/mandatory/ | 否 |
| GET | `/api/v1/rankings/platform-stats/` | 排行页全站统计：任务总数、任务奖励 USDT 发放合计、用户数、运营天数 | 否 |
| GET | `/api/v1/rankings/commission-leaderboard/` | 佣金榜：按个人做任务 task_reward USDT 累计分页 | 否 |
| GET | `/api/v1/rankings/task-leaderboard/` | 与 commission-leaderboard 相同（兼容旧路径） | 否 |
| GET | `/api/v1/rankings/invite-leaderboard/` | 邀请榜：按直接邀请人数分页 | 否 |
| GET | `/api/v1/me/ranking/invite-overview/` | 排行邀请区：data.invite_link（full_url 可为 t.me?start=ref_…，见 §4.5）+ 邀请统计 + me 排名 | 是 |
| GET | `/api/v1/me/rankings/invite-overview/` | 同 me/ranking/invite-overview/（复数 rankings 别名） | 是 |
| GET | `/api/v1/me/ranking/invitees/` | 我的邀请明细分页（下级完成数+贡献返佣展示） | 是 |
| GET | `/api/v1/me/rankings/invitees/` | 同 me/ranking/invitees/（复数别名） | 是 |
| GET | `/api/v1/me/ranking/context/` | 排行底栏：invite/task/commission 排名与推荐奖励累计 USDT | 是 |
| GET | `/api/v1/me/rankings/context/` | 同 me/ranking/context/（复数别名） | 是 |
| GET | `/api/v1/tasks/` | 任务列表（分页、筛选） | 否 |
| POST | `/api/v1/tasks/` | 发布任务 | 是 |
| GET | `/api/v1/tasks/{task_id}/` | 任务详情 | 否 |
| PATCH | `/api/v1/tasks/{task_id}/` | 更新任务（发布人） | 是 |
| POST | `/api/v1/tasks/{task_id}/apply/` | 报名任务 | 是 |
| POST | `/api/v1/me/applications/{application_id}/verify-twitter/` | Twitter 绑定类：站外转发/关注后自动校验并录用（需 TWITTER_BEARER_TOKEN） | 是 |
| POST | `/api/v1/me/applications/{application_id}/verify-youtube/` | YouTube 绑定类：简介含 youtube_proof_link 时拉取 about 页校验后自动录用 | 是 |
| POST | `/api/v1/me/applications/{application_id}/verify-instagram/` | Instagram 绑定：含证明链接时仅 Apify 校验（须配 APIFY_API_TOKEN） | 是 |
| POST | `/api/v1/me/applications/{application_id}/verify-tiktok/` | TikTok 绑定：转发指定视频后 Apify 拉 Reposts 校验（须配 APIFY_API_TOKEN，默认 clockworks/tiktok-scraper） | 是 |
| POST | `/api/v1/me/applications/{application_id}/verify-telegram-group/` | 加入 Telegram 群任务：Bot getChatMember 校验已入群（须 TELEGRAM_BOT_TOKEN + 任务配置 telegram_chat_id） | 是 |
| GET | `/api/v1/tasks/{task_id}/applications/` | 发布人查看报名列表 | 是 |
| PATCH / POST | `/api/v1/applications/{application_id}/` | 发布人审核报名 | 是 |
| GET | `/api/v1/me/published-tasks/` | 我发布的任务 | 是 |
| GET | `/api/v1/me/applied-tasks/` | 我报名的任务 | 是 |
| GET | `/api/v1/me/task-records/` | 任务记录：分页 + record_status 筛选（与 Tab 进行中/审核中/已完成/已失效 对齐） | 是 |
<!-- API_QUICKREF_END -->
