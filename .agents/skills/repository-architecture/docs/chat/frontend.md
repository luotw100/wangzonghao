# Chat Frontend / Chat 前端

## 入口文件

- `services/chat/web/src/main.tsx`：React root。
- `services/chat/web/src/App.tsx`：应用壳。
- `services/chat/web/src/api.ts`：浏览器 API client。
- `services/chat/web/src/styles.css`：样式。

## API client

`api.ts` 当前行为：

- `API_BASE = '/api'`。
- token 存在 localStorage key `laborster-chat-token`。
- `request<T>()` 自动加 Authorization header。
- 401 时清 token，并抛"登录已失效"。
- `getMessages()` 单独实现 long-poll timeout：server timeout + 5s；timeout=0 时客户端最少 10s。

导出函数：

- `login()`、`me()`、`logout()`。
- `createContact()`、`updateContact()`、`deleteContact()`。
- `listConversations()`。
- `sendMessage()`。
- `getMessages()`。

主要 TS 类型：`Account`、`Contact`、`Conversation`、`Message`、`LoginResponse`。

## Hooks

### `useAuth`

状态：

- `account`
- `loading`
- `error`

流程：

1. mount 时如果 token 存在，调用 `me()`。
2. `login(username, password)` 调 API，保存 token，设置 account。
3. `logout()` best-effort 调 API，清本地 token/account。

### `useWorkspace`

状态：

- `conversations`
- `loaded`

`reload()` 调用 `listConversations()`。只在 `enabled` 为 true 时（即已认证）拉取。

### `useMessages`

状态：

- `messages`

流程：

1. conversationId 变化时清空消息和 `lastIdRef`。
2. 初始拉取：`getMessages(conversationId, 0, 0)`。
3. 进入循环：`getMessages(conversationId, lastId, 30)`。
4. 去重并按 id 排序。
5. 带 cancellation guard，适配 React StrictMode。

暴露：`reload()`、`reset()`。

## App shell

`App.tsx` 当前职责：

- 未登录时渲染 `Login`。
- 登录后加载 workspace。
- 维护 `activeConversationId`、`globalError`、移动端 `list/chat` view。
- 宽屏（≥860px）有 conversations 时自动选择第一个。
- 创建/删除/更新联系人后 reload workspace。
- 组合 `Sidebar` 和 `ChatPanel`。

## Components

### `Login`

用户名/密码表单，提交时调用 `onLogin(username, password)`。

### `Sidebar`

当前职责：

- 显示账号信息和 logout。
- 按 contact name、note 或 last message content 搜索会话。
- 创建联系人（name + note）。
- 显示会话列表和时间预览。
- 支持右键和移动端长按（500ms）菜单：Edit Note、Delete Contact。

### `ChatPanel`

当前职责：

- 显示当前 conversation header（back button、avatar、name、note）。
- 在 localStorage 中保存发送视角 `self | contact`。
- 通过 `api.sendMessage()` 发送。
- 组合 `MessageList` 和 `Composer`。

### `Composer`

- textarea 输入。
- 发送视角 toggle（两个 tab：Me / Counterpart）。
- Enter 发送（非 Shift+Enter、非 IME composing）；Shift+Enter 换行。
- 发送失败时保留未发送文本。

### `MessageList`

- 渲染消息气泡。
- 根据 perspective 决定左右（active perspective 在右侧）。
- 用 `shouldShowSeparator()` 插入时间分隔（gap ≥ 5 分钟）。
- conversation 切换时跳到底部；新消息时仅在接近底部时自动滚动。
- 每条消息旁显示 avatar。

### `Avatar`

- 确定性颜色和 initials。
- CJK 名取最后一字；Latin 名取首尾字母。

### `ContextMenu`

- 定位到 (x, y)，clamp 到 viewport。
- 外部 mousedown、scroll 和 Escape 关闭。
- 渲染 menu items 为 buttons。

### Utilities

- `utils/time.ts`：full time（年月日 时分）、list preview、bubble separator（WeChat 风格）。
- `utils/color.ts`：12 个预定 hue、avatar seed hash 和 initials。
