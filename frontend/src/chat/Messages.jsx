import React, { useRef, useState } from 'react';
import { Bot, Check, Paperclip, Send, ThumbsUp, X } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Button, Choice, FileInput, FileInputItem, FileInputItemRemove, FileInputList, FileInputTrigger,
  PersonAvatar, Textarea,
} from '../design/system/Controls.jsx';
import { boardRequest } from './board.js';

const timestamp = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const markdownComponents = {
  img: ({ src, alt }) => src ? <a href={src} rel="noreferrer">{alt || 'Image'}</a> : null,
};

export function TaskBadge({ task }) {
  return <span className={`chat-task-state chat-task-state--${task.state}`}>
    {task.state === 'completed' && <Check size={13} aria-hidden="true" />}
    {task.state.replaceAll('_', ' ')}
  </span>;
}

export function Message({ message, replies, onOpen, onEdit, onDelete, onUpdate, me, profile, activity }) {
  const [error, setError] = useState('');
  const author = message.author;
  const name = author?.name || author?.handle || 'Unknown';
  const isAgent = author?.kind === 'agent';
  const stars = message.reactions?.thumbs_up ?? [];
  const reacted = stars.includes(me?.actor);
  const canEdit = !message.deleted && message.by?.principal === me?.principal
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
    <PersonAvatar name={name} src={author?.avatar} tone={isAgent ? 'moss' : 'clay'} decorative />
    <div className="chat-message__content">
      <div className="chat-message__byline">
        <strong>{name}</strong>
        {isAgent && <span className="chat-agent" title={author?.via?.name ? 'Via ' + author.via.name : undefined}><Bot size={13} aria-hidden="true" /> Agent</span>}
        <time dateTime={message.createdAt}>{timestamp.format(new Date(message.createdAt))}</time>
        {activity && <span className="chat-message__channel">#{message.channel}</span>}
        {message.task && <TaskBadge task={message.task} />}
      </div>
      {message.deleted ? <p className="chat-muted">Message deleted.</p>
        : <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{message.text}</Markdown></div>}
      {!!message.attachments?.length && !message.deleted && <div className="chat-attachments">
        {message.attachments.map(file => <Button key={file.id} variant="ghost" size="small" onClick={() => download(file)}><Paperclip size={14} aria-hidden="true" />{file.name}</Button>)}
      </div>}
      {!message.deleted && <div className="chat-message__actions">
        {onOpen && <Button variant="ghost" size="small" onClick={onOpen}>{replies ? `${replies} ${replies === 1 ? 'reply' : 'replies'}` : 'Open thread'}</Button>}
        <Button variant="ghost" size="small" aria-label={reacted ? 'Remove thumbs up' : 'React with thumbs up'} aria-pressed={reacted} onClick={toggleReaction}>
          <ThumbsUp size={15} aria-hidden="true" />{stars.length || null}
        </Button>
        {canEdit && <><Button variant="ghost" size="small" onClick={() => onEdit(message)}>Edit</Button><Button variant="ghost" size="small" onClick={() => onDelete(message)}>Delete</Button></>}
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
  const busy = useRef(false);
  const uploaded = useRef(new Map());

  function changeText(value) { id.current = null; setText(value); }
  function changeFiles(value) { id.current = null; setFiles(value); }
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
      uploaded.current.clear();
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
    <Textarea rows={3} aria-label={label} placeholder={label} value={text} onValueChange={changeText}
      maxLength={10000} readOnly={pending} onKeyDown={event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.currentTarget.form.requestSubmit();
        }
      }} />
    <FileInput multiple value={files} onValueChange={changeFiles} disabled={pending} maxFiles={10} minSize={1} maxSize={4 * 1024 * 1024}
      onReject={() => setError('Attach up to 10 files, between 1 byte and 4 MiB each.')}>
      <FileInputList className="chat-attachments" aria-label="Attachments"><FileInputItem className="chat-file">
        {({ file }) => <><span>{file.name}</span><FileInputItemRemove aria-label={`Remove ${file.name}`}><X size={14} aria-hidden="true" /></FileInputItemRemove></>}
      </FileInputItem></FileInputList>
      <div className="chat-composer__toolbar">
        <FileInputTrigger className="cc-button cc-button--ghost cc-button--small" aria-label="Attach files"><Paperclip size={17} aria-hidden="true" /></FileInputTrigger>
        {allowTasks && <Choice checked={task} disabled={pending} onCheckedChange={checked => { id.current = null; setTask(checked); }}>Post as task</Choice>}
        <Button type="submit" variant="primary" size="small" data-agent-confirm="Posts this message to Cozy Chat" disabled={pending || (!text.trim() && !files.length)}>
          <Send size={15} aria-hidden="true" />{pending ? 'Sending…' : target.re ? 'Reply' : 'Send'}
        </Button>
      </div>
    </FileInput>
    {error && <p className="chat-error" role="alert">{error}</p>}
  </form>;
}
