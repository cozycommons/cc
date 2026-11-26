import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Bot, CheckSquare2, ChevronLeft, Hash, LogOut, Menu, Plus, Search, X } from 'lucide-react';
import {
  Button, Collapsible, CollapsiblePanel, CollapsibleTrigger, Dialog, DialogBackdrop, DialogClose,
  DialogContent, DialogDescription, DialogTitle, Field, FieldLabel, Input, PersonAvatar,
  ScrollArea, ScrollAreaContent, ScrollAreaViewport, Textarea,
} from '../design/system/Controls.jsx';
import { boardRequest, viewHref } from './board.js';
import { Composer, Message } from './Messages.jsx';
import { readChannels, readThread, readTimeline, useBoardRead, useLiveBoard, useNavigation } from './useBoard.js';

function NavLink({ target, current, icon: Icon, children, onNavigate }) {
  function follow(event) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(target);
  }
  return <Button variant="ghost" className="chat-nav__link" aria-current={current ? 'page' : undefined}
    render={<a href={viewHref(target)} />} onClick={follow}>
    <Icon size={18} aria-hidden="true" /><span>{children}</span>
  </Button>;
}

function Navigation({ route, channels, me, onNavigate, onDialog }) {
  const [open, setOpen] = useState(() => window.matchMedia('(min-width: 621px)').matches);
  useEffect(() => {
    const wide = window.matchMedia('(min-width: 621px)');
    const resize = (event) => setOpen(event.matches);
    wide.addEventListener('change', resize);
    return () => wide.removeEventListener('change', resize);
  }, []);
  const navigate = (target) => {
    if (!window.matchMedia('(min-width: 621px)').matches) setOpen(false);
    onNavigate(target);
  };
  return <Collapsible className="chat-sidebar" open={open} onOpenChange={setOpen}>
    <header className="chat-brand">
      <div className="chat-brand__mark" aria-hidden="true"><span /><span /><span /></div>
      <div><span className="chat-brand__name">Cozy Chat</span><a href="https://cozycommons.dev">Cozy Commons</a></div>
      <CollapsibleTrigger className="cc-button cc-button--ghost chat-mobile-menu" aria-label="Toggle navigation"><Menu size={21} aria-hidden="true" /></CollapsibleTrigger>
    </header>
    <CollapsiblePanel className="chat-sidebar__panel" keepMounted>
      <ScrollArea className="chat-nav-area">
        <ScrollAreaViewport className="chat-nav-viewport">
          <ScrollAreaContent>
            <nav className="chat-nav" aria-label="Chat">
              <NavLink target={{ view: null }} current={!route.tasks && route.view == null} icon={Activity} onNavigate={navigate}>Activity</NavLink>
              <NavLink target={{ tasks: true }} current={route.tasks} icon={CheckSquare2} onNavigate={navigate}>Tasks</NavLink>
              <div className="chat-nav__heading">
                <h2>Channels</h2>
                <Button variant="ghost" size="small" aria-label="Create channel" onClick={() => onDialog({ type: 'channel' })}><Plus size={18} aria-hidden="true" /></Button>
              </div>
              {channels.map(channel => <NavLink key={channel.path} target={{ view: channel.path }} current={!route.tasks && route.view === channel.path} icon={Hash} onNavigate={navigate}>{channel.path}</NavLink>)}
            </nav>
          </ScrollAreaContent>
        </ScrollAreaViewport>
      </ScrollArea>
      <div className="chat-account">
        <PersonAvatar name={me?.name || 'Commons member'} decorative tone="walnut" />
        <Button variant="ghost" className="chat-account__identity" onClick={() => onDialog({ type: 'profile' })}>
          <strong>{me?.name || 'Commons member'}</strong><small>{me?.profile ? 'Agent profile' : 'Posting as yourself'}</small>
        </Button>
        <form action="/auth/sign-out" method="post">
          <Button variant="ghost" size="small" type="submit" aria-label="Sign out"><LogOut size={17} aria-hidden="true" /></Button>
        </form>
      </div>
    </CollapsiblePanel>
  </Collapsible>;
}

function ChatDialog({ dialog, profile, onClose, onSave }) {
  const [value, setValue] = useState(dialog.message?.text ?? (dialog.type === 'profile' ? profile : ''));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const titles = { channel: 'Create a channel', edit: 'Edit message', delete: 'Delete message?', profile: 'Posting identity', task: 'Complete task' };
  const labels = { channel: 'Channel name', edit: 'Message', profile: 'Agent profile name', task: 'Result (optional)' };
  const remove = dialog.type === 'delete';
  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try { await onSave(dialog, value.trim()); }
    catch (error) { setError(error.message); setSaving(false); }
  }
  return <Dialog open onOpenChange={open => { if (!open && !saving) onClose(); }}>
    <DialogBackdrop className="cc-sdk-backdrop" />
    <DialogContent className="cc-sdk-dialog chat-dialog">
      <DialogTitle className="cc-h2">{titles[dialog.type]}</DialogTitle>
      {remove && <DialogDescription>The message will be removed from the conversation.</DialogDescription>}
      {dialog.type === 'profile' && <DialogDescription>Leave blank to post as yourself.</DialogDescription>}
      <form onSubmit={submit}>
        {!remove && <Field className="cc-field">
          <FieldLabel className="cc-label">{labels[dialog.type]}</FieldLabel>
          {dialog.type === 'edit' || dialog.type === 'task'
            ? <Textarea value={value} onValueChange={setValue} rows={4} maxLength={10000} required={dialog.type === 'edit'} />
            : <Input value={value} onValueChange={setValue} required={dialog.type === 'channel'} maxLength={dialog.type === 'profile' ? 32 : 100} />}
        </Field>}
        {error && <p className="chat-error" role="alert">{error}</p>}
        <div className="cc-dialog__actions">
          <DialogClose className="cc-button cc-button--ghost" disabled={saving}>Cancel</DialogClose>
          <Button variant={remove ? 'destructive' : 'primary'} type="submit" disabled={saving}
            data-agent-confirm={remove ? 'Deletes this message from Cozy Chat' : undefined}>
            {saving ? 'Saving…' : remove ? 'Delete message' : dialog.type === 'channel' ? 'Create channel' : dialog.type === 'task' ? 'Complete task' : 'Save'}
          </Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>;
}

function TaskActions({ message, claim, onAction }) {
  const task = message.task;
  if (!task) return null;
  if (claim && (task.state === 'claimed' || task.state === 'ready')) {
    return <div className="chat-task-actions">
      <Button size="small" variant="primary" onClick={() => onAction('complete')}>Complete task</Button>
      <Button size="small" onClick={() => onAction('release')}>Release</Button>
      <Button size="small" variant="ghost" onClick={() => onAction('renew')}>Extend claim</Button>
    </div>;
  }
  if (task.state === 'ready') return <div className="chat-task-actions"><Button size="small" onClick={() => onAction('claim')}>Claim task</Button></div>;
  if (task.state === 'claimed') return <p className="chat-task-actions chat-muted">Task claimed</p>;
  return null;
}

function ScrollPane({ children, className = '' }) {
  return <ScrollArea className={`chat-scroll ${className}`}>
    <ScrollAreaViewport className="chat-scroll__viewport"><ScrollAreaContent>{children}</ScrollAreaContent></ScrollAreaViewport>
  </ScrollArea>;
}

export default function Chat() {
  const [route, navigate] = useNavigation();
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [profile, setProfile] = useState('');
  const [dialog, setDialog] = useState(null);
  const [threadError, setThreadError] = useState('');
  const [olderRows, setOlderRows] = useState({ key: '', rows: [], next: null });
  const [paging, setPaging] = useState(false);
  const pagination = useRef(null);
  const claims = useRef(new Map());
  const update = useCallback(() => setRevision(value => value + 1), []);
  const live = useLiveBoard(update);
  const identity = useBoardRead(profile, 0, readProfile);
  const channels = useBoardRead('channels', revision, readChannels);
  const thread = useBoardRead(route.thread, revision, readThread);
  const timelineKey = JSON.stringify({ view: route.view, tasks: route.tasks, filter });
  const timeline = useBoardRead(timelineKey, revision, readTimeline);

  useEffect(() => {
    const timer = setTimeout(() => setFilter(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => () => pagination.current?.abort(), [timelineKey]);

  function go(target) {
    if (!target.thread) setSearch('');
    setThreadError('');
    navigate({ view: target.view ?? null, tasks: Boolean(target.tasks), thread: target.thread ?? null });
  }

  function openThread(message) {
    go({ ...route, thread: message.re || message.id });
  }

  async function loadOlder() {
    const active = olderRows.key === timelineKey ? olderRows : { rows: [], next: timeline.value.older };
    const request = new AbortController();
    pagination.current?.abort();
    pagination.current = request;
    setPaging(true);
    try {
      const next = await readTimeline(JSON.stringify({ ...JSON.parse(timelineKey), older: active.next }), request.signal);
      setOlderRows({ key: timelineKey, rows: [...active.rows, ...next.rows], next: next.older });
    } catch (error) {
      if (!request.signal.aborted) setThreadError(error.message);
    } finally {
      if (pagination.current === request) setPaging(false);
    }
  }

  async function actOnTask(type, message, result) {
    const body = type === 'claim' ? {} : { ...claims.current.get(message.id), ...(result ? { result } : {}) };
    const answer = await boardRequest(`/tasks/${encodeURIComponent(message.id)}/${type}`, { body, profile });
    if (type === 'claim') claims.current.set(message.id, { epoch: answer.claim.epoch, token: answer.claim.token });
    if (type === 'release' || type === 'complete') claims.current.delete(message.id);
    update();
  }

  async function saveDialog(action, value) {
    if (action.type === 'channel') {
      const { channel } = await boardRequest('/channels', { body: { path: value }, profile });
      go({ view: channel.path });
    } else if (action.type === 'profile') {
      if (value && !/^[a-z][a-z0-9-]{0,31}$/i.test(value)) throw new Error('Use 1–32 letters, numbers, or hyphens, starting with a letter.');
      await boardRequest('/me', { profile: value });
      setProfile(value);
      claims.current.clear();
    } else if (action.type === 'task') {
      await actOnTask('complete', action.message, value);
    } else {
      const { id, revision } = action.message;
      await boardRequest(`/messages/${encodeURIComponent(id)}/${action.type}`, {
        profile, body: { revision, ...(action.type === 'edit' ? { text: value } : {}) },
      });
    }
    setDialog(null);
    update();
  }

  const title = route.tasks ? 'Tasks' : route.view == null ? 'Activity' : route.view;
  const isChannel = !route.tasks && route.view != null;
  const root = thread.value?.message;
  const firstPage = timeline.value?.rows ?? [];
  const extra = olderRows.key === timelineKey ? olderRows.rows : [];
  const rows = [...new Map([...firstPage, ...extra].map(row => [row.message.id, row])).values()];
  const filtered = route.tasks && filter ? rows.filter(row => row.message.text.toLowerCase().includes(filter.toLowerCase())) : rows;
  const nextPage = olderRows.key === timelineKey ? olderRows.next : timeline.value?.older;
  const messageProps = {
    onEdit: message => setDialog({ type: 'edit', message }),
    onDelete: message => setDialog({ type: 'delete', message }),
    onUpdate: update, me: identity.value, profile,
  };

  return <main className={`chat-layout${route.thread ? ' chat-layout--thread' : ''}`}>
    <Navigation route={route} channels={channels.value ?? []} me={identity.value} onNavigate={go} onDialog={setDialog} />
    <section className="chat-main" aria-labelledby="chat-title">
      <header className="chat-header">
        <div className="chat-header__name">
          {isChannel ? <Hash aria-hidden="true" /> : route.tasks ? <CheckSquare2 aria-hidden="true" /> : <Activity aria-hidden="true" />}
          <h1 id="chat-title">{title}</h1>
        </div>
        <span className={`chat-live${live ? ' is-live' : ''}`} role="status">{live ? 'Live' : 'Connecting'}</span>
      </header>
      <div className="chat-toolbar">
        <div className="chat-search">
          <Search size={17} aria-hidden="true" />
          <Input type="search" aria-label={route.tasks ? 'Search tasks' : 'Search messages'} placeholder={route.tasks ? 'Search tasks' : 'Search messages'} value={search} onValueChange={setSearch} />
        </div>
        {profile && <span className="chat-agent"><Bot size={14} aria-hidden="true" />{profile}</span>}
      </div>
      <ScrollPane className="chat-timeline">
        {(timeline.error || channels.error || identity.error) && <p className="chat-error chat-notice" role="alert">{timeline.error || channels.error || identity.error}</p>}
        {!route.thread && threadError && <p className="chat-error chat-notice" role="alert">{threadError}</p>}
        {!timeline.value && !timeline.error && <p className="chat-empty" role="status">Loading…</p>}
        {timeline.value && !filtered.length && <p className="chat-empty">{filter ? 'No results.' : route.tasks ? 'No open tasks.' : isChannel ? 'No messages in this channel yet.' : 'No recent messages.'}</p>}
        {filtered.map(({ message, replies }) => <Message key={message.id} {...messageProps} message={message} replies={replies}
          activity={!isChannel} onOpen={() => openThread(message)} />)}
        {nextPage && <div className="chat-load-more"><Button variant="ghost" disabled={paging} onClick={loadOlder}>{paging ? 'Loading…' : 'Load older threads'}</Button></div>}
      </ScrollPane>
      {isChannel && !filter && <Composer key={route.view + ':' + profile} target={{ channel: route.view }} label={`Message #${route.view}`} allowTasks onPosted={update} profile={profile} />}
    </section>
    {route.thread && <aside className="chat-thread" aria-labelledby="chat-thread-title">
      <header className="chat-header">
        <Button variant="ghost" size="small" className="chat-thread__back" onClick={() => go({ ...route, thread: null })} aria-label="Back to messages"><ChevronLeft size={20} aria-hidden="true" /></Button>
        <div className="chat-header__name"><h2 id="chat-thread-title">Thread</h2>{root && <span>#{root.channel}</span>}</div>
        <Button variant="ghost" size="small" onClick={() => go({ ...route, thread: null })} aria-label="Close thread"><X size={20} aria-hidden="true" /></Button>
      </header>
      <ScrollPane>
        {(thread.error || threadError) && <p className="chat-error chat-notice" role="alert">{thread.error || threadError}</p>}
        {!root && !thread.error && <p className="chat-empty" role="status">Loading thread…</p>}
        {root && <>
          <Message {...messageProps} message={root} />
          <TaskActions message={root} claim={claims.current.get(root.id)} onAction={type => {
            if (type === 'complete') setDialog({ type: 'task', message: root });
            else actOnTask(type, root).then(() => setThreadError(''), error => setThreadError(error.message));
          }} />
          {thread.value.replies.length > 0 && <p className="chat-reply-count">{thread.value.replies.length} {thread.value.replies.length === 1 ? 'reply' : 'replies'}</p>}
          {thread.value.replies.map(message => <Message key={message.id} {...messageProps} message={message} />)}
        </>}
      </ScrollPane>
      {root && !root.deleted && <Composer key={root.id + ':' + profile} target={{ re: root.id }} label="Reply in thread" onPosted={update} profile={profile} />}
    </aside>}
    {dialog && <ChatDialog dialog={dialog} profile={profile} onClose={() => setDialog(null)} onSave={saveDialog} />}
  </main>;
}

function readProfile(profile, signal) {
  return boardRequest('/me', { profile, signal });
}
