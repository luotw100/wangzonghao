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

- `login()`、`me()`、`updateMe({ nickname })`、`logout()`。
- `createContact()`、`updateContact()`、`deleteContact()`。
- `listConversations()`。
- `sendMessage()`：`msg_type` 参数支持 `text | image | audio | video | file`。
- `bulkSendMessages(conversationId, messages)`：批量导入，调 `POST .../messages/bulk`。
- `presignUpload(filename, mimeType)`：请求 presigned PUT URL。
- `uploadPresignedFile(uploadUrl, file)`：PUT 文件到 S3 presigned URL。
- `mediaUrl(storageKey)`：拼接 `/api/media/{key}?token=xxx`，用于 `<img>`/`<audio>`/`<video>` src。
- `getMessages()`。
- `contactDisplayName(contact)`：helper，返回 `contact.remark_name ?? contact.nickname`。

主要 TS 类型：`Account`（`nickname`）、`Contact`（`username`、`nickname`、`remark_name`）、`Conversation`、`Message`、`MessageType`（`'text' | 'image' | 'audio' | 'video' | 'file'`）、`UploadPresignResponse`、`LoginResponse`。

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
4. `updateNickname(nickname)` 调 `PATCH /api/auth/me`，更新本地 account state。

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
6. `loadOlder(beforeId)`：调 `getMessages(conversationId, {before_id, limit})` 拉更早消息，合并去重后置顶。

暴露：`reload()`、`reset()`、`loadOlder(beforeId)`。

## App shell

`App.tsx` 当前职责：

- 未登录时渲染 `Login`。
- 登录后加载 workspace。
- 维护 `activeConversationId`、`globalError`、移动端 `list/chat` view、`showImport`。
- 宽屏（≥860px）有 conversations 时自动选择第一个。
- 创建/删除/更新联系人后 reload workspace。
- `showImport=true` 时渲染 `ImportDialog`，导入完成后跳转到新建会话。
- 组合 `Sidebar` 和 `ChatPanel`。

## Components

### `Login`

用户名/密码表单，提交时调用 `onLogin(username, password)`。

### `Sidebar`

当前职责：

- 显示账号信息（nickname 可点击原地编辑，Enter/blur 保存，Escape 取消）和 logout（独立按钮）。
- 按 contact remark_name/nickname 或 last message content 搜索会话。
- 创建联系人（nickname + remark_name）。
- 显示会话列表和时间预览；联系人展示名由 `contactDisplayName()` 计算（remark_name ?? nickname）。
- 带标签文字的导入按钮，触发 App 层 `setShowImport(true)`。
- 支持右键和移动端长按（500ms）菜单：Edit Remark Name、Delete Contact。

### `ChatPanel`

当前职责：

- 显示当前 conversation header（back button、avatar、展示名由 `contactDisplayName()` 计算）。
- 在 localStorage 中保存发送视角 `self | contact`。
- 通过 `api.sendMessage()` 发送。
- 组合 `MessageList` 和 `Composer`。

### `Composer`

- textarea 输入 + 附件按钮（📎）。
- 发送视角 toggle（两个 tab：Me / Counterpart）。
- Enter 发送文本消息（非 Shift+Enter、非 IME composing）；Shift+Enter 换行。
- 点击 📎 选择文件 → `presignUpload()` → `uploadPresignedFile()` → `sendMessage(msg_type, storage_key)`。`msg_type` 由前端根据文件 MIME 自动推断（image→image, audio→audio, video→video, 其他→file）。
- 发送失败时保留未发送文本。

### `MessageList`

- 渲染消息气泡，根据 `msg_type` 决定渲染方式：
  - `text` → 纯文本。
  - `image` → 默认显示点击加载占位符（media lazy-load），点击后替换为 `<img src={mediaUrl(key)}>`。
  - `audio` → 同上，点击后 `<audio controls>`。
  - `video` → 同上，点击后 `<video controls>`。
  - `file` → `<a href={mediaUrl(key)}>` 下载链接。
- `mediaUrl()` 拼接 `/api/media/{key}?token=xxx`，token 来自 localStorage。
- 根据 perspective 决定左右（active perspective 在右侧）。
- 用 `shouldShowSeparator()` 插入时间分隔（gap ≥ 5 分钟）。
- conversation 切换时跳到底部；新消息时仅在接近底部时自动滚动。
- 每条消息旁显示 avatar。
- 气泡 hover 时显示时间戳 + 来源标签（导入 / 实时），替代原 native title tooltip。
- 列表滚动到顶部时触发 `loadOlder()`，加载更早消息。

### `Avatar`

- 确定性颜色和 initials。
- CJK 名取最后一字；Latin 名取首尾字母。

### `ContextMenu`

- 定位到 (x, y)，clamp 到 viewport。
- 外部 mousedown、scroll 和 Escape 关闭。
- 渲染 menu items 为 buttons。

### `ImportDialog`

3 步流程（ChatLab JSON 导入）：

1. **选文件**：选择 ChatLab 私聊 JSON 文件，在浏览器端解析，展示会话成员列表。
2. **确认身份**：用户选择哪个成员是"自己"（self），并确认对方为新联系人。
3. **导入进度**：调 `api.createContact()` 建联系人，再调 `api.bulkSendMessages()` 一次性批量写入所有消息（取代旧的逐条 send）。

导入完成后通知 App 层，App 跳转到新建会话并 reload workspace。

### Utilities

- `utils/time.ts`：full time（年月日 时分）、list preview、bubble separator（WeChat 风格）。
- `utils/color.ts`：12 个预定 hue、avatar seed hash 和 initials。
