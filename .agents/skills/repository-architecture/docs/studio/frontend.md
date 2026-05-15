# Studio Frontend / Studio 前端

## 入口文件

- `src/main.tsx`：React root。
- `src/App.tsx`：routes 和 unauthorized redirect。
- `src/lib/api.ts`：typed API client。
- `src/lib/auth.tsx`：auth context 和 route guards。
- `src/pages/StudioPage.tsx`：主控制台。
- `src/index.css`：Tailwind 和自定义样式。

## API client

`src/lib/api.ts` 当前行为：

- `API_BASE = '/api'`。
- token 存在 localStorage key `laborster-studio-token`。
- `setUnauthorizedHandler()` 注册全局 401 handler。
- `request<T>()` 自动加 bearer token，并设置 timeout。
- 401 时清 token，调用 unauthorized handler，抛 `UnauthorizedError`。

主要类型：

- `Account`
- `ProviderConfig`
- `Persona`（含 `timezone: string`）
- `Bridge`
- `Inbox`
- `Contact`（含 `takeover: boolean`、`reply_policy: 'disabled' | 'autoreply'`）
- `Message`
- `ConversationSummary`
- `DistillJob`

主要函数：

- Auth：`login`、`authLogout`、`authMe`、`changeOwnPassword`。
- Admin overview：`getAdminOverview`（admin-only，返回 `AdminOverview { totals, accounts[] }`）。
- Account admin：`getAccounts`、`createAccount`、`updateAccount`、`resetAccountPassword`。
- Providers：`getProviderConfigs`、`createProviderConfig`、`updateProviderConfig`、`deleteProviderConfig`。
- Personas：`getPersonas`、`getPersona`、`createPersona`（含 `timezone?`）、`updatePersona`（含 `timezone?`）、`deletePersona`。
- Bridges：`getBridges`、`deleteBridge`。
- Inboxes：`getInboxes`、`updateInbox`。
- Contacts：`getConversations`、`getContactMessages`、`updateContact`。
- Distill：`getDistillJobs`、`getDistillJob`、`createDistillJob`。

## Auth context 和 routes

`lib/auth.tsx`：

- `AuthProvider` 在 token 存在时调用 `authMe()` 加载当前账号。
- `useAuth()` 暴露 `account`、`loading`、`refresh`、`logout`。
- `RequireAuth` 保护 `/studio`。
- `RedirectIfAuthed` 当前未被路由使用。

`App.tsx` routes：

- `/` → `HomePage`。
- `/studio` → `StudioPage`，外层是 `RequireAuth`。

`UnauthorizedRedirect` 注册全局 unauthorized handler：401 时 refresh auth state，并跳转 `/`。

## Pages

### HomePage

当前行为：

- 纯 username/password form，仅提供登录功能。
- 调 `api.login()` → `api.setToken()` 保存 token → auth `refresh()` → 跳转 `/studio`。
- 登录失败时显示错误。
- 提示首个 admin 用 CLI 创建（`python -m studio.cli create-account --role admin`），账号管理与密码重置都走 Studio Settings 页。

### StudioPage 顶层

Tab 类型按角色区分：

- Admin：`overview`（默认） · `takeover` · `persona` · `device` · `settings`
- 普通用户：`takeover`（默认） · `persona` · `device` · `settings`

`overview` 是 admin 专属：调 `getAdminOverview()`，渲染全局 totals 卡片 + 跨账号明细表（设备 / 接管号 / 人设 / 粉丝(接管中) / 消息）。其它 tab 的查询在 admin 时不按 account 过滤，因此 admin 也能跨用户穿透排查。

顶层 state：

- `tab`
- `bridges`
- `personas`
- `inboxes`
- `providers`
- `error`

`loadAll()` 并发拉取 bridges、personas、inboxes。当前账号 role 是 admin 时额外拉 providers；普通 user 不拉 ProviderConfig。`loadAll()` 每 10 秒后台静默轮询一次（`setInterval`，不触发 loading 状态）。

## TakeoverView

当前是主要操作 tab。

State：

- `items: ConversationSummary[]`（全量，含接管和未接管）
- `selectedId`
- `messages`
- `loading`

流程：

1. 拉 `/conversations`，每 3 秒后台静默轮询（`setInterval`）。
2. 没有 selected 时选第一个 contact。
3. selected contact 变化时拉 messages；messages 同样每 3 秒静默轮询。
4. 按 `contact.takeover` 分为两组：`takenItems`（已接管）和 `availableItems`（未接管）。
5. 左侧两个分区：
   - **已接管**：`InboxGroup` 组件，富卡片（含消息预览、reply_policy chip），可选中进入 ContactDetail。
   - **未接管**：简化行，每行有"接管"按钮（调 `updateContact(id, { takeover: true })`）；点击行也可以在右侧展示 ContactDetail 以便编辑。
6. 右侧显示 ContactDetail（接管和未接管的 contact 均可选中展示）。

分组：

- `takenGrouped` / `availableGrouped`：各自按 Inbox id → conversations 的映射。
- `inboxOrder`：有 conversations 的 inbox 在前，再补空 inbox（共用）。

Chip 三态：`takeover=false` → `未接管`；`takeover=true && reply_policy='disabled'` → `已接管`；`takeover=true && reply_policy='autoreply'` → `自动回复`。

## InboxGroup

显示单个 Inbox：

- Inbox display name 和 platform。
- Bridge status。
- Contact list。
- 可展开 settings。

本地 state：`showSettings`。

## InboxDefaults

编辑 Inbox 默认值：

- `default_persona_id`。
- admin 可编辑 `reply_provider_config_id`；普通 user 不展示 Provider 选择。
- `enabled`。

保存时调用 `api.updateInbox()`。

## ContactDetail

显示和编辑 Contact 接管配置：

- display name。
- peer platform id。
- Persona select。
- admin 可看到 Provider override select；普通 user 看到“模型由管理员统一配置”。
- autoreply switch。切换到 `autoreply` 前的 warning gate：若该 contact 没有 persona（或 persona `persona_md` 为空）或 `card_md` 为空，`confirm()` 警告"人设和关系卡缺一不可，自动回复不会真正生效"，取消则不 patch。
- card markdown editor。下方一个「✶ 自动创建关系卡」按钮：调 `api.createDistillJob({ contact_ids: [contact.id], target_persona_id: null })`，后台从该粉丝全部聊天记录提取关系卡、不动人设；提交后显示 note，靠 3s 轮询自动刷新出新 `card_md`。
- recent messages。

Provider 运行时解析：

```text
contact.reply_provider_config_id ?? inbox.reply_provider_config_id ?? global default provider
```

接管 ready 条件在 UI 中由以下因素计算：

- Inbox enabled。
- Bridge online。
- Persona 存在。

保存通过 `onPatch()`，最终调用 `api.updateContact()`。

## BridgesView (DevicesView)

- 顶部固定 `BridgeCommandPanel`：根据当前 username + studio_url + chat base_url + chat username 实时拼出 `docker compose run --rm bridge ...` 启动命令，密码留作占位符；按钮可一键复制。
- 列出非 revoked Bridge。
- 显示 status、machine_id、last seen、承载的 Inboxes。
- revoke 调 `api.deleteBridge()`。

## OverviewView (admin)

- 顶部 `StatCard` 网格：账号 / 设备 / 接管号 / 人设 / 粉丝 / 消息 / Provider / 待发 outbound 全局合计。
- 下方账号明细表：每行一个 Studio Account，列出 role、status、最后登录、设备在线数、接管号、人设、粉丝(其中接管中)、消息总数。
- 数据来自 `getAdminOverview()`；右上角刷新按钮重拉。

## PersonasView

- 列出 Persona。
- 页头两个入口：「✶ 自动创建」（主按钮）和「+ 手动新建」。
- `CreatePersonaModal`（手动）：顶部有醒目提示卡片，引导改用自动创建（按钮回调 `onSwitchToAuto` 切到自动创建 modal）；其余 `name`、`persona_md`、`timezone` 字段调 `api.createPersona()`。
- `AutoCreatePersonaModal`（自动创建即蒸馏入口）：输入人设 `name` + `timezone`；`api.getConversations()` 拉接管列表（`takeover` 的 contact），按 inbox 分组多选，默认全选，可整组全选/取消；提交时先 `api.createPersona({ persona_md: null })` 建空人设，再 `api.createDistillJob({ contact_ids, target_persona_id: persona.id })`。无进度条，后台执行。
- Edit modal 调 `api.updatePersona()`，同样暴露 `timezone` 字段。
- Delete 调 `api.deletePersona()`。
- 设计取舍：persona 不做版本历史（用户建多个 persona 即可），card 单张直接覆盖——二者均可从 source-of-truth 消息重新蒸出，无需快照。

## SettingsView

Settings 当前包含：

- `PasswordPanel`：当前账号输入旧密码和新密码后重置自己的密码。
- `AccountsPanel`：仅 admin 可见，列出账号、创建账号、停用/启用账号、重置任意账号密码。
- `ProviderPanel`：仅 admin 可见，列出 ProviderConfig、创建 ProviderConfig、删除 ProviderConfig。

## ProviderPanel

- 列出 ProviderConfig。
- Create modal 调 `api.createProviderConfig()`。
- Delete 调 `api.deleteProviderConfig()`。
- UI 只有 provider create 和 delete；provider edit 表单未实现（API client 已有 `updateProviderConfig()`）。

## Shared UI helpers

`StudioPage.tsx` 内部 helper：

- `SectionHeader`
- `Empty`
- `FormField`
- `ModalShell`
- `ModalActions`

独立 components：

- `components/Icons.tsx`：SVG icons/logo。
- `components/Modal.tsx`：通用 modal；当前 StudioPage 多数使用内部 `ModalShell`。

Utilities：

- `lib/utils.ts`：`formatDate()`、`formatTime()`、`cn()`。
