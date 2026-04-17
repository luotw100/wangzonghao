import { useState, useCallback } from 'react';
import { useAppStore } from './hooks/useAppStore';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { CreateRobotModal } from './components/CreateRobotModal';
import { EditRobotModal } from './components/EditRobotModal';
import { CreateContactModal } from './components/CreateContactModal';
import { EditContactModal } from './components/EditContactModal';
import { CreateSessionModal } from './components/CreateSessionModal';
import { EditSessionModal } from './components/EditSessionModal';
import { SettingsModal } from './components/SettingsModal';
import type { Robot, Contact, Session } from './lib/api';

export default function App() {
  const store = useAppStore();

  // Modal states
  const [showCreateRobot, setShowCreateRobot] = useState(false);
  const [showEditRobot, setShowEditRobot] = useState(false);
  const [editingRobot, setEditingRobot] = useState<Robot | null>(null);
  const [showCreateContact, setShowCreateContact] = useState(false);
  const [showEditContact, setShowEditContact] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [showCreateSession, setShowCreateSession] = useState(false);
  const [defaultRobotId, setDefaultRobotId] = useState<string | null>(null);
  const [showEditSession, setShowEditSession] = useState(false);
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsReturn, setSettingsReturn] = useState(false);

  const handleError = useCallback((msg: string) => store.setErrorMessage(msg), [store]);

  // Close a sub-modal and return to SettingsModal if it was opened from there
  const returnToSettings = useCallback(() => {
    if (settingsReturn) {
      setSettingsReturn(false);
      setShowSettings(true);
    }
  }, [settingsReturn]);

  const handleEditRobot = useCallback((robot: Robot) => {
    setEditingRobot(robot);
    setShowEditRobot(true);
  }, []);

  const handleEditContact = useCallback((contact: Contact) => {
    setEditingContact(contact);
    setShowEditContact(true);
  }, []);

  const handleCreateSession = useCallback(
    (robotId: string | null) => {
      if (robotId) {
        const robot = store.robots.find((r) => r.id === robotId);
        if (robot?.is_deleted) {
          store.setErrorMessage('已删除的 Robot 不能创建 Session');
          return;
        }
      }
      setDefaultRobotId(robotId);
      setShowCreateSession(true);
    },
    [store]
  );

  const handleEditSession = useCallback((session: Session) => {
    setEditingSession(session);
    setShowEditSession(true);
  }, []);

  const handleSessionCreated = useCallback(
    async (sessionId: string) => {
      await store.loadSessions();
      store.selectSession(sessionId);
      store.setSidebarOpen(false);
    },
    [store]
  );

  const handleRobotSaved = useCallback(async () => {
    store.setErrorMessage('');
    await store.refreshAll();
  }, [store]);

  const handleContactSaved = useCallback(async () => {
    store.setErrorMessage('');
    await store.refreshAll();
  }, [store]);

  const handleSessionSaved = useCallback(async () => {
    store.setErrorMessage('');
    await store.loadSessions();
  }, [store]);

  return (
    <div className="w-full h-dvh overflow-hidden flex bg-bg-primary text-text-primary">
      <Sidebar
        sidebarOpen={store.sidebarOpen}
        setSidebarOpen={store.setSidebarOpen}
        robots={store.robots}
        sessionsByRobot={store.sessionsByRobot}
        collapsedRobots={store.collapsedRobots}
        activeSessionId={store.activeSessionId}
        showDeletedItems={store.showDeletedItems}
        setShowDeletedItems={store.setShowDeletedItems}
        onToggleRobot={store.toggleRobot}
        onSelectSession={store.selectSession}
        onEditRobot={handleEditRobot}
        onCreateSession={handleCreateSession}
        onEditSession={handleEditSession}
        onOpenSettings={() => setShowSettings(true)}
      />

      <ChatArea
        activeSession={store.activeSession}
        activeSessionId={store.activeSessionId}
        isActiveSessionDeleted={store.isActiveSessionDeleted}
        isActiveSessionReadOnly={store.isActiveSessionReadOnly}
        currentMessages={store.currentMessages}
        plannedReplies={store.plannedReplies}
        inputText={store.inputText}
        setInputText={store.setInputText}
        errorMessage={store.errorMessage}
        setErrorMessage={store.setErrorMessage}
        onSendMessage={store.sendTextMessage}
        onOpenSidebar={() => store.setSidebarOpen(true)}
        providerConfigs={store.providerConfigs}
        activeSessionProviderName={store.activeSessionProviderName}
        onSwitchProvider={store.switchSessionProvider}
      />

      {/* Modals */}
      <CreateRobotModal
        open={showCreateRobot}
        onClose={() => { setShowCreateRobot(false); returnToSettings(); }}
        onCreated={handleRobotSaved}
        onError={handleError}
      />
      <EditRobotModal
        open={showEditRobot}
        robot={editingRobot}
        onClose={() => { setShowEditRobot(false); returnToSettings(); }}
        onSaved={handleRobotSaved}
        onError={handleError}
      />
      <CreateContactModal
        open={showCreateContact}
        onClose={() => { setShowCreateContact(false); returnToSettings(); }}
        onCreated={handleContactSaved}
        onError={handleError}
      />
      <EditContactModal
        open={showEditContact}
        contact={editingContact}
        onClose={() => { setShowEditContact(false); returnToSettings(); }}
        onSaved={handleContactSaved}
        onError={handleError}
      />
      <CreateSessionModal
        open={showCreateSession}
        onClose={() => setShowCreateSession(false)}
        onCreated={handleSessionCreated}
        onError={handleError}
        activeRobots={store.activeRobots}
        activeContacts={store.activeContacts}
        providerConfigs={store.providerConfigs}
        defaultRobotId={defaultRobotId}
      />
      <EditSessionModal
        open={showEditSession}
        session={editingSession}
        onClose={() => setShowEditSession(false)}
        onSaved={handleSessionSaved}
        onError={handleError}
      />
      <SettingsModal
        open={showSettings}
        onClose={() => setShowSettings(false)}
        robots={store.robots}
        contacts={store.contacts}
        providerConfigs={store.providerConfigs}
        onEditRobot={(robot) => { setShowSettings(false); setSettingsReturn(true); handleEditRobot(robot); }}
        onCreateRobot={() => { setShowSettings(false); setSettingsReturn(true); setShowCreateRobot(true); }}
        onEditContact={(contact) => { setShowSettings(false); setSettingsReturn(true); handleEditContact(contact); }}
        onCreateContact={() => { setShowSettings(false); setSettingsReturn(true); setShowCreateContact(true); }}
        onRefresh={store.refreshAll}
        onError={handleError}
      />
    </div>
  );
}
