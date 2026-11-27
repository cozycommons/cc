import React, { useRef, useState } from 'react';
import { Bot, Check, Paperclip, Send, ThumbsUp, X } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { FieldError, FieldLabel } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { boardRequest } from './board.js';

const timestamp = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const markdownComponents = {
  img: ({ src, alt }) => src ? <a href={src} rel="noreferrer">{alt || 'Image'}</a> : null,
};

export function ChatAvatar({ name, src, agent }) {
  const initials = name.trim().split(/\s+/).slice(0, 2).map(word => Array.from(word)[0] || '').join('').toLocaleUpperCase();
  return <Avatar aria-hidden="true" size="lg" className={agent ? 'chat-avatar--agent' : undefined}>
    {src && <AvatarImage src={src} alt="" referrerPolicy="no-referrer" />}
    <AvatarFallback>{initials}</AvatarFallback>
  </Avatar>;
}

function TaskBadge({ task }) {
  const complete = task.state === 'completed';
  return <Badge variant={complete || task.state === 'ready' ? 'default' : 'outline'}>
    {complete && <Check aria-hidden="true" />}
    {task.state.replaceAll('_', ' ')}
  </Badge>;
}

export function Message({ message, replies, threadHref, onOpen, onEdit, onDelete, onUpdate, me, profile, activity }) {
  const [error, setError] = useState('');
  const author = message.author;
  const name = author?.name || author?.handle || 'Unknown';
  const isAgent = author?.kind === 'agent';
  const stars = message.reactions?.thumbs_up ?? [];
  const reacted = stars.includes(me?.actor);
  const canEdit = Boolean(me) && !message.deleted && message.by?.principal === me?.principal
    && (!profile || message.by?.actor === me?.actor);

  async function toggleReaction() {
    try {
      await boardRequest(`/messages/${encodeURIComponent(message.id)}/reactions`, { profile, body: { emoji: 'thumbs_up', remove: reacted } });
      setError('');
      onUpdate();
    } catch (error) {
      setError(error.message);
    }
  }

  async function download(attachment) {
    try {
      const blob = await boardRequest('/attachments/' + encodeURIComponent(attachment.id), { profile });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = attachment.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setError(error.message);
    }
  }

  return <article className="chat-message">
    <ChatAvatar name={name} src={author?.avatar} agent={isAgent} />
    <div className="chat-message__content">
      <div className="chat-message__byline">
        <strong>{name}</strong>
        {isAgent && <Badge title={author?.via?.name ? 'Via ' + author.via.name : undefined}><Bot aria-hidden="true" /> Agent</Badge>}
        <time dateTime={message.createdAt}>{timestamp.format(new Date(message.createdAt))}</time>
        {activity && <span className="chat-message__channel">#{message.channel}</span>}
        {message.task && <TaskBadge task={message.task} />}
      </div>
      {message.deleted ? <p className="chat-muted">Message deleted.</p>
        : <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{message.text}</Markdown></div>}
      {!!message.attachments?.length && !message.deleted && <div className="chat-attachments">
        {message.attachments.map(file => <Button key={file.id} variant="ghost" size="sm" onClick={() => download(file)}><Paperclip size={14} aria-hidden="true" />{file.name}</Button>)}
      </div>}
      {!message.deleted && <div className="chat-message__actions">
        {threadHref && <Button variant="ghost" size="sm" asChild>
          <a href={threadHref} onClick={event => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
            event.preventDefault();
            onOpen(event.currentTarget);
          }}>{replies ? `${replies} ${replies === 1 ? 'reply' : 'replies'}` : 'Open thread'}</a>
        </Button>}
        <Button variant="ghost" size="sm" title={reacted ? 'Remove thumbs up' : 'React with thumbs up'} aria-label={reacted ? 'Remove thumbs up' : 'React with thumbs up'} aria-pressed={reacted} onClick={toggleReaction}>
          <ThumbsUp size={15} aria-hidden="true" />{stars.length || null}
        </Button>
        {canEdit && <><Button variant="ghost" size="sm" onClick={event => onEdit(message, event.currentTarget)}>Edit</Button><Button variant="ghost" size="sm" onClick={event => onDelete(message, event.currentTarget)}>Delete</Button></>}
      </div>}
      {error && <p className="chat-error" role="alert">{error}</p>}
    </div>
  </article>;
}

export function Composer({ target, label, allowTasks, onPosted, profile }) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState([]);
  const [task, setTask] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const id = useRef(null);
  const filePicker = useRef(null);
  const attachButton = useRef(null);
  const taskId = React.useId();
  const busy = useRef(false);
  const uploaded = useRef(new Map());

  function changeText(value) { id.current = null; setText(value); }
  function changeFiles(value) {
    id.current = null;
    for (const file of uploaded.current.keys()) {
      if (!value.includes(file)) uploaded.current.delete(file);
    }
    setFiles(value);
  }

  function selectFiles(event) {
    const selected = [...event.target.files];
    event.target.value = '';
    const accepted = [...files];
    for (const file of selected) {
      if (accepted.length < 10 && file.size > 0 && file.size <= 4 * 1024 * 1024) accepted.push(file);
    }
    setError(accepted.length - files.length === selected.length ? '' : 'Attach up to 10 files, between 1 byte and 4 MiB each.');
    if (accepted.length > files.length) changeFiles(accepted);
  }
  async function submit(event) {
    event.preventDefault();
    if (busy.current || (!text.trim() && !files.length)) return;
    busy.current = true;
    setPending(true);
    setError('');
    id.current ??= crypto.randomUUID();
    try {
      const attachments = [];
      for (const file of files) {
        if (!uploaded.current.has(file)) {
          const { attachment } = await boardRequest('/attachments', { file, profile });
          uploaded.current.set(file, attachment.id);
        }
        attachments.push(uploaded.current.get(file));
      }
      await boardRequest(task ? '/tasks' : '/messages', {
        profile, body: { ...target, text: text.trim(), attachments, id: id.current },
      });
      changeText('');
      changeFiles([]);
      setTask(false);
      onPosted();
    } catch (error) {
      setError(error.message);
    } finally {
      setPending(false);
      busy.current = false;
    }
  }

  return <form className="chat-composer" onSubmit={submit}>
    <Textarea rows={3} aria-label={label} name="message" placeholder={label + '…'} value={text}
      onChange={event => changeText(event.target.value)} maxLength={10000} readOnly={pending} onKeyDown={event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.currentTarget.form.requestSubmit();
        }
      }} />
    <input ref={filePicker} type="file" name="attachments" hidden multiple disabled={pending} onChange={selectFiles} />
    {files.length > 0 && <ul className="chat-attachments" aria-label="Attachments">
      {files.map((file, index) => <li className="chat-file" key={index}>
        <span>{file.name}</span>
        <Button type="button" size="icon-sm" variant="ghost" aria-label={`Remove ${file.name}`} disabled={pending} onClick={() => {
          changeFiles(files.filter((_, fileIndex) => index !== fileIndex));
          attachButton.current?.focus();
        }}><X aria-hidden="true" /></Button>
      </li>)}
    </ul>}
    <div className="chat-composer__toolbar">
      <Button ref={attachButton} type="button" variant="ghost" size="icon" aria-label="Attach files" title="Attach files"
        onClick={() => filePicker.current?.click()} disabled={pending}><Paperclip aria-hidden="true" /></Button>
      {allowTasks && <FieldLabel htmlFor={taskId} className="chat-task-toggle">
        <Checkbox id={taskId} checked={task} disabled={pending} onCheckedChange={checked => { id.current = null; setTask(checked === true); }} />
        Post as task
      </FieldLabel>}
      <Button type="submit" data-agent-confirm="Posts this message to Cozy Chat" disabled={pending || (!text.trim() && !files.length)}>
        <Send aria-hidden="true" />{pending ? 'Sending…' : target.re ? 'Reply' : 'Send'}
      </Button>
    </div>
    {error && <FieldError>{error}</FieldError>}
  </form>;
}
