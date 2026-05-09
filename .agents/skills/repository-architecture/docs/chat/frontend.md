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
- 401 时清 token，并抛“登录已失效”。
- `getMessages()` 单独实现 long-poll timeout：server timeout + 5s；timeout=0 时客户端最少 10s。

导出函数：

- `login()`、`me()`、`logout()`。
- `listContacts()`、`createContact()`、`deleteContact()`。
- `listConversations()`。
- `sendMessage()`。
- `getMessages()`。
- `bulkImportMessages()`。

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
4. `clearError()` 清 UI error。

### `useWorkspace`

状态：

- `contacts`
- `conversations`
- `loaded`

`reload()` 并发调用 `listContacts()` 和 `listConversations()`。

### `useMessages`

状态：

- `messages`
- `loading`
- `error`

流程：

1. conversation 变化时清空消息和 `lastIdRef`。
2. 初始拉取：`getMessages(conversationId, 0, 0)`。
3. 进入循环：`getMessages(conversationId, lastId, 30)`。
4. 去重并按 id append。
5. 出错后 1.5s backoff。
6. 带 cancellation guard，适配 React StrictMode。

暴露：`reload()`、`prepend()`、`reset()`。

## App shell

`App.tsx` 当前职责：

- 未登录时渲染 `Login`。
- 登录后加载 workspace。
- 维护 `activeConversationId`、`globalError`、移动端 `list/chat` view。
- 有 conversations 时自动选择第一个。
- 创建/删除联系人后 reload workspace。
- 组合 `Sidebar` 和 `ChatPanel`。

## Components

### `Login`

用户名/密码表单，提交时调用 `onLogin(username, password)`。

### `Sidebar`

当前职责：

- 显示账号信息和 logout。
- 按 title、display name、note 搜索会话。
- 创建联系人。
- 显示会话列表和时间预览。
- 支持右键和移动端长按菜单删除联系人。

### `ChatPanel`

当前职责：

- 显示当前 conversation。
- 在 localStorage 中保存发送视角 `self | contact`。
- 通过 `api.sendMessage()` 发送。
- 打开 `ImportModal`，提交时调用 `bulkImportMessages()`。
- 组合 `MessageList` 和 `Composer`。

### `Composer`

- textarea 输入。
- 发送视角 toggle。
- Enter 发送；Shift+Enter 换行。

### `MessageList`

- 渲染消息气泡。
- 根据 perspective 决定左右。
- 用 `shouldShowSeparator()` 插入时间分隔。
- conversation 切换或接近底部时自动滚动。

### `ImportModal`

- 支持拖拽或选择 JSON 文件。
- 要求 JSON 顶层是数组。
- 标准化 `sender_type`、`msg_type`、`content`、`created_at`。
- 展示 preview。
- 提交 filename + parsed messages。

### Utilities

- `Avatar`：确定性颜色和 initials。
- `ContextMenu`：外部点击和 Escape 关闭。
- `utils/time.ts`：full time、list preview、bubble separator。
- `utils/color.ts`：avatar seed hash 和 initials。
