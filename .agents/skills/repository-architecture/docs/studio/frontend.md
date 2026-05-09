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
- `Persona`
- `Bridge`
- `Inbox`
- `Contact`
- `Archive`
- `Message`
- `ConversationSummary`
- `DistillJob`

主要函数：

- Auth / bootstrap：`login`、`authLogout`、`authMe`、`changeOwnPassword`、`getBootstrapStatus`、`bootstrapAdmin`。
- Account admin：`getAccounts`、`createAccount`、`updateAccount`、`resetAccountPassword`。
- Providers：`getProviderConfigs`、`createProviderConfig`、`updateProviderConfig`、`deleteProviderConfig`。
- Personas：`getPersonas`、`getPersona`、`createPersona`、`updatePersona`、`deletePersona`。
- Bridges：`getBridges`、`deleteBridge`。
- Inboxes：`getInboxes`、`updateInbox`。
- Contacts：`getConversations`、`getContactMessages`、`updateContact`。
- Archives：`getArchives`、`uploadArchive`。
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

- 进入页面时调用 `getBootstrapStatus()`。
- 如果数据库没有任何账号，显示首次初始化表单，调用 `bootstrapAdmin()` 创建首个 admin 并登录。
- username/password form。
- 调 `api.login()`。
- `api.setToken()` 保存 token。
- 调 auth `refresh()`。
- 跳转 `/studio`。
- 登录失败时显示错误；账号创建和重置密码的主路径在 Studio 设置页。

### StudioPage 顶层

Tab 类型：

- `takeover`
- `persona`
- `device`
- `settings`

顶层 state：

- `tab`
- `bridges`
- `personas`
- `inboxes`
- `providers`
- `error`

`loadAll()` 并发拉取 bridges、personas、inboxes。当前账号 role 是 admin 时额外拉 providers；普通 user 不拉 ProviderConfig。

## TakeoverView

当前是主要操作 tab。

State：

- `items: ConversationSummary[]`
- `selectedId`
- `messages`
- `loading`

流程：

1. 拉 `/conversations`。
2. 没有 selected 时选第一个 contact。
3. selected contact 变化时拉 messages。
4. 按 Inbox 分组 contacts。
5. 左侧显示 Inbox/Contact list，右侧显示 ContactDetail。

分组：

- `grouped`：Inbox id → conversations。
- `inboxOrder`：有 conversations 的 inbox 在前，再补空 inbox。

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
- autoreply switch。
- card markdown editor。
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

## BridgesView

- 列出非 revoked Bridge。
- 显示 status、hostname、last seen、承载的 Inboxes。
- revoke 调 `api.deleteBridge()`。

## PersonasView

- 列出 Persona。
- Create modal 调 `api.createPersona()`。
- Edit modal 调 `api.updatePersona()`。
- Delete 调 `api.deletePersona()`。

## SettingsView

Settings 当前包含：

- `PasswordPanel`：当前账号输入旧密码和新密码后重置自己的密码。
- `AccountsPanel`：仅 admin 可见，列出账号、创建账号、停用/启用账号、重置任意账号密码。
- `ProviderPanel`：仅 admin 可见，列出 ProviderConfig、创建 ProviderConfig、删除 ProviderConfig。

## ProviderPanel

- 列出 ProviderConfig。
- Create modal 调 `api.createProviderConfig()`。
- Delete 调 `api.deleteProviderConfig()`。
- 当前 UI 没有完整 provider edit 表单，虽然 API client 有 `updateProviderConfig()`。

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
