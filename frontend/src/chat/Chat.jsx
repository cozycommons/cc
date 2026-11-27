import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Bot, CheckSquare2, ChevronLeft, Hash, LogOut, Menu, Plus, Search, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { boardRequest, viewHref } from './board.js';
import { ChatAvatar, Composer, Message } from './Messages.jsx';
import { readChannels, readThread, readTimeline, useBoardRead, useLiveBoard, useNavigation } from './useBoard.js';

function NavLink({ target, current, icon: Icon, children, onNavigate }) {
  function follow(event) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(target);
  }
  return <Button variant="ghost" asChild className="chat-nav__link">
    <a href={viewHref(target)} aria-current={current ? 'page' : undefined} onClick={follow}>
      <Icon aria-hidden="true" /><span>{children}</span>
    </a>
  </Button>;
}

const wideNavigation = '(min-width: 621px)';

function Navigation({ route, channels, me, onNavigate, onDialog }) {
  const [wide, setWide] = useState(() => window.matchMedia(wideNavigation).matches);
  const [openRoute, setOpenRoute] = useState(null);
  const open = wide || openRoute === route;
  const menu = useRef(null);
  useEffect(() => {
    const desktop = window.matchMedia(wideNavigation);
    const resize = (event) => {
      setWide(event.matches);
      setOpenRoute(null);
    };
    desktop.addEventListener('change', resize);
    return () => desktop.removeEventListener('change', resize);
  }, []);
  function dismiss(event) {
    if (event.key === 'Escape' && open && !wide) {
      event.stopPropagation();
      setOpenRoute(null);
      menu.current?.focus();
    }
  }
  return <Collapsible className="chat-sidebar" open={open} onOpenChange={next => setOpenRoute(next ? route : null)} onKeyDown={dismiss}>
    <header className="chat-brand">
      <div className="chat-brand__mark" aria-hidden="true"><span /><span /><span /></div>
      <div>
        <span className="chat-brand__name" translate="no">Cozy Chat</span>
        <a href="https://cozycommons.dev" translate="no">Cozy Commons</a>
      </div>
      <CollapsibleTrigger asChild>
        <Button ref={menu} variant="ghost" size="icon" className="chat-mobile-menu" aria-label="Toggle navigation">
          <Menu aria-hidden="true" />
        </Button>
      </CollapsibleTrigger>
    </header>
    <CollapsibleContent className="chat-sidebar__panel">
      <nav className="chat-nav" aria-label="Chat">
        <NavLink target={{ view: null }} current={!route.tasks && route.view == null} icon={Activity} onNavigate={onNavigate}>Activity</NavLink>
        <NavLink target={{ tasks: true }} current={route.tasks} icon={CheckSquare2} onNavigate={onNavigate}>Tasks</NavLink>
        <div className="chat-nav__heading">
          <h2>Channels</h2>
          <Button variant="ghost" size="icon" aria-label="Create channel" onClick={event => onDialog({ type: 'channel' }, event.currentTarget)}><Plus aria-hidden="true" /></Button>
        </div>
        {channels.map(channel => <NavLink key={channel.path} target={{ view: channel.path }} current={!route.tasks && route.view === channel.path} icon={Hash} onNavigate={onNavigate}>{channel.path}</NavLink>)}
      </nav>
      <div className="chat-account">
        <ChatAvatar name={me?.name || 'Commons member'} />
        <Button variant="ghost" className="chat-account__identity" onClick={event => onDialog({ type: 'profile' }, event.currentTarget)}>
          <strong>{me?.name || 'Commons member'}</strong><small>{me?.profile ? 'Agent profile' : 'Posting as yourself'}</small>
        </Button>
        <form action="/auth/sign-out" method="post">
          <Button variant="ghost" size="icon" type="submit" aria-label="Sign out"><LogOut aria-hidden="true" /></Button>
        </form>
      </div>
    </CollapsibleContent>
  </Collapsible>;
}

function ChatDialog({ dialog, profile, onClose, onSave, onRestoreFocus }) {
  const [value, setValue] = useState(dialog.message?.text ?? (dialog.type === 'profile' ? profile : ''));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const titles = { channel: 'Create a channel', edit: 'Edit message', delete: 'Delete message?', profile: 'Posting identity', task: 'Complete task' };
  const labels = { channel: 'Channel name', edit: 'Message', profile: 'Agent profile name', task: 'Result (optional)' };
  const descriptions = {
    channel: 'Choose a name for the new conversation.',
    edit: 'Update the message in this conversation.',
    delete: 'The message will be removed from the conversation.',
    profile: 'Leave blank to post as yourself.',
    task: 'Add a result for anyone following this task.',
  };
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
    <DialogContent className="chat-dialog" showCloseButton={false} onCloseAutoFocus={onRestoreFocus}>
      <DialogHeader>
        <DialogTitle>{titles[dialog.type]}</DialogTitle>
        <DialogDescription>{descriptions[dialog.type]}</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="flex flex-col gap-4">
        {!remove && <Field data-invalid={Boolean(error)}>
          <FieldLabel htmlFor="chat-dialog-value">{labels[dialog.type]}</FieldLabel>
          {dialog.type === 'edit' || dialog.type === 'task'
            ? <Textarea id="chat-dialog-value" name="message" value={value} onChange={event => setValue(event.target.value)}
                rows={4} maxLength={10000} required={dialog.type === 'edit'} aria-invalid={Boolean(error)} aria-describedby={error ? 'chat-dialog-error' : undefined} />
            : <Input id="chat-dialog-value" name={dialog.type} value={value} onChange={event => setValue(event.target.value)} autoComplete="off"
                required={dialog.type === 'channel'} maxLength={dialog.type === 'profile' ? 32 : 100}
                aria-invalid={Boolean(error)} aria-describedby={error ? 'chat-dialog-error' : undefined} />}
        </Field>}
        {error && <FieldError id="chat-dialog-error">{error}</FieldError>}
        <DialogFooter>
          <DialogClose asChild><Button type="button" variant="outline" disabled={saving}>Cancel</Button></DialogClose>
          <Button variant={remove ? 'destructive' : 'default'} type="submit" disabled={saving}
            data-agent-confirm={remove ? 'Deletes this message from Cozy Chat' : undefined}>
            {saving ? 'Saving…' : remove ? 'Delete message' : dialog.type === 'channel' ? 'Create channel' : dialog.type === 'task' ? 'Complete task' : 'Save'}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}

function TaskActions({ message, claim, onAction }) {
  const task = message.task;
  if (!task) return null;
  if (claim && (task.state === 'claimed' || task.state === 'ready')) {
    return <div className="chat-task-actions">
      <Button size="sm" onClick={event => onAction('complete', event.currentTarget)}>Complete task</Button>
      <Button size="sm" variant="outline" onClick={() => onAction('release')}>Release</Button>
      <Button size="sm" variant="ghost" onClick={() => onAction('renew')}>Extend claim</Button>
    </div>;
  }
  if (task.state === 'ready') return <div className="chat-task-actions"><Button size="sm" onClick={() => onAction('claim')}>Claim task</Button></div>;
  if (task.state === 'claimed') return <p className="chat-task-actions chat-muted">Task claimed</p>;
  return null;
}

function ScrollPane({ children, label, className = '' }) {
  return <div className={`chat-scroll ${className}`} tabIndex={0} role="region" aria-label={label}>{children}</div>;
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
  const dialogTrigger = useRef(null);
  const threadTrigger = useRef(null);
  const titleRef = useRef(null);
  const threadTitleRef = useRef(null);
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
    if ((target.view ?? null) !== route.view || Boolean(target.tasks) !== route.tasks) setSearch('');
    setThreadError('');
    navigate({ view: target.view ?? null, tasks: Boolean(target.tasks), thread: target.thread ?? null });
    requestAnimationFrame(() => {
      if (target.thread) threadTitleRef.current?.focus();
      else {
        if (route.thread) threadTrigger.current?.focus();
        if (!route.thread || document.activeElement !== threadTrigger.current) titleRef.current?.focus();
      }
    });
  }

  function showDialog(action, trigger) {
    dialogTrigger.current = trigger;
    setDialog(action);
  }

  function restoreDialogFocus(event) {
    event.preventDefault();
    dialogTrigger.current?.focus();
    if (document.activeElement !== dialogTrigger.current) {
      (threadTitleRef.current || titleRef.current)?.focus();
    }
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
    onEdit: (message, trigger) => showDialog({ type: 'edit', message }, trigger),
    onDelete: (message, trigger) => showDialog({ type: 'delete', message }, trigger),
    onUpdate: update, me: identity.value, profile,
  };

  return <div className={`chat-layout${route.thread ? ' chat-layout--thread' : ''}`}>
    <a className="chat-skip sr-only focus:not-sr-only" href={route.thread ? '#chat-thread-title' : '#chat-title'}>
      Skip to {route.thread ? 'thread' : 'messages'}
    </a>
    <Navigation route={route} channels={channels.value ?? []} me={identity.value} onNavigate={go} onDialog={showDialog} />
    <main className="chat-main" aria-labelledby="chat-title">
      <header className="chat-header">
        <div className="chat-header__name">
          {isChannel ? <Hash aria-hidden="true" /> : route.tasks ? <CheckSquare2 aria-hidden="true" /> : <Activity aria-hidden="true" />}
          <h1 id="chat-title" ref={titleRef} tabIndex={-1}>{title}</h1>
        </div>
        <span className={`chat-live${live ? ' is-live' : ''}`} role="status">{live ? 'Live' : 'Connecting'}</span>
      </header>
      <div className="chat-toolbar">
        <div className="chat-search">
          <Search size={17} aria-hidden="true" />
          <Input type="search" aria-label={route.tasks ? 'Search tasks' : 'Search messages'} name="search" autoComplete="off" placeholder={route.tasks ? 'Search tasks…' : 'Search messages…'}
            value={search} onChange={event => setSearch(event.target.value)} />
        </div>
        {profile && <Badge><Bot aria-hidden="true" />{profile}</Badge>}
      </div>
      <ScrollPane key={timelineKey} label={route.tasks ? "Task results" : "Messages"}>
        {(timeline.error || channels.error || identity.error) && <p className="chat-error chat-notice" role="alert">{timeline.error || channels.error || identity.error}</p>}
        {!route.thread && threadError && <p className="chat-error chat-notice" role="alert">{threadError}</p>}
        {!timeline.value && !timeline.error && <p className="chat-empty" role="status">Loading…</p>}
        {timeline.value && !filtered.length && <p className="chat-empty">{filter ? 'No results.' : route.tasks ? 'No open tasks.' : isChannel ? 'No messages in this channel yet.' : 'No recent messages.'}</p>}
        {filtered.map(({ message, replies }) => <Message key={message.id} {...messageProps} message={message} replies={replies}
          activity={!isChannel}
          threadHref={viewHref({ ...route, thread: message.re || message.id })}
          onOpen={trigger => {
            threadTrigger.current = trigger;
            go({ ...route, thread: message.re || message.id });
          }} />)}
        {nextPage && <div className="chat-load-more"><Button variant="ghost" disabled={paging} onClick={loadOlder}>{paging ? 'Loading…' : 'Load older threads'}</Button></div>}
      </ScrollPane>
      {isChannel && !filter && <Composer key={route.view + ':' + profile} target={{ channel: route.view }} label={`Message #${route.view}`} allowTasks onPosted={update} profile={profile} />}
    </main>
    {route.thread && <aside className="chat-thread" aria-labelledby="chat-thread-title">
      <header className="chat-header">
        <Button variant="ghost" size="icon" className="chat-thread__back" onClick={() => go({ ...route, thread: null })} aria-label="Back to messages"><ChevronLeft size={20} aria-hidden="true" /></Button>
        <div className="chat-header__name"><h2 id="chat-thread-title" ref={threadTitleRef} tabIndex={-1}>Thread</h2>{root && <span>#{root.channel}</span>}</div>
        <Button variant="ghost" size="icon" className="chat-thread__close" onClick={() => go({ ...route, thread: null })} aria-label="Close thread"><X size={20} aria-hidden="true" /></Button>
      </header>
      <ScrollPane key={route.thread} label="Thread messages">
        {(thread.error || threadError) && <p className="chat-error chat-notice" role="alert">{thread.error || threadError}</p>}
        {!root && !thread.error && <p className="chat-empty" role="status">Loading thread…</p>}
        {root && <>
          <Message {...messageProps} message={root} />
          <TaskActions message={root} claim={claims.current.get(root.id)} onAction={(type, trigger) => {
            if (type === 'complete') showDialog({ type: 'task', message: root }, trigger);
            else actOnTask(type, root).then(() => setThreadError(''), error => setThreadError(error.message));
          }} />
          {thread.value.replies.length > 0 && <p className="chat-reply-count">{thread.value.replies.length} {thread.value.replies.length === 1 ? 'reply' : 'replies'}</p>}
          {thread.value.replies.map(message => <Message key={message.id} {...messageProps} message={message} />)}
        </>}
      </ScrollPane>
      {root && !root.deleted && <Composer key={root.id + ':' + profile} target={{ re: root.id }} label="Reply in thread" onPosted={update} profile={profile} />}
    </aside>}
    {dialog && <ChatDialog dialog={dialog} profile={profile} onClose={() => setDialog(null)}
      onSave={saveDialog} onRestoreFocus={restoreDialogFocus} />}
  </div>;
}

function readProfile(profile, signal) {
  return boardRequest('/me', { profile, signal });
}
