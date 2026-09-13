import React from 'react';
import { Button } from '../components/core/Button';
import { IconButton } from '../components/core/IconButton';
import { Card } from '../components/core/Card';
import { Badge } from '../components/core/Badge';
import { Tag } from '../components/core/Tag';
import { Input } from '../components/forms/Input';
import { Select } from '../components/forms/Select';
import { Checkbox } from '../components/forms/Checkbox';
import { Radio } from '../components/forms/Radio';
import { Switch } from '../components/forms/Switch';
import { Dialog } from '../components/feedback/Dialog';
import { Toast } from '../components/feedback/Toast';
import { Tooltip } from '../components/feedback/Tooltip';
import { Tabs } from '../components/navigation/Tabs';

function Row({ children, wrap = true }) {
  return <div style={{ display: 'flex', gap: '14px', alignItems: 'center', flexWrap: wrap ? 'wrap' : 'nowrap' }}>{children}</div>;
}

function Group({ label, children }) {
  return (
    <div style={{ marginBottom: 'var(--space-8)' }}>
      <p className="ds-eyebrow" style={{ marginBottom: 'var(--space-3)', color: 'var(--text-tertiary)' }}>{label}</p>
      {children}
    </div>
  );
}

function CoreTab() {
  const [activeTag, setActiveTag] = React.useState('Design');
  return (
    <>
      <Group label="Button — primary, accent, secondary, ghost, danger">
        <Row>
          <Button variant="primary">Primary</Button>
          <Button variant="accent">Accent</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" disabled>Disabled</Button>
        </Row>
      </Group>

      <Group label="Sizes">
        <Row>
          <Button variant="accent" size="sm">Small</Button>
          <Button variant="accent" size="md">Medium</Button>
          <Button variant="accent" size="lg">Large</Button>
        </Row>
      </Group>

      <Group label="Icon button — ghost / solid">
        <Row>
          <IconButton label="Add">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </IconButton>
          <IconButton label="Search" variant="solid">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.6" y2="16.6" /></svg>
          </IconButton>
          <IconButton label="Disabled" disabled>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          </IconButton>
        </Row>
      </Group>

      <Group label="Badge — status color chips">
        <Row>
          <Badge color="moss">Design</Badge>
          <Badge color="clay">Code</Badge>
          <Badge color="sky">Writing</Badge>
          <Badge color="blossom">New</Badge>
          <Badge color="gold">Featured</Badge>
          <Badge color="berry">Urgent</Badge>
          <Badge color="neutral">Archived</Badge>
        </Row>
      </Group>

      <Group label="Tag — filters, selectable pills">
        <Row>
          {['All', 'Design', 'Code', 'Writing'].map((t) => (
            <Tag key={t} active={activeTag === t} onClick={() => setActiveTag(t)}>{t}</Tag>
          ))}
        </Row>
      </Group>

      <Group label="Card — with and without the glow-accent window">
        <Row>
          <Card style={{ width: 220 }}>
            <p className="ds-eyebrow" style={{ marginBottom: 6 }}>Standard</p>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)' }}>Hairline border, shadow-sm.</p>
          </Card>
          <Card accent style={{ width: 220 }}>
            <p className="ds-eyebrow" style={{ marginBottom: 6, color: 'var(--accent-moss)' }}>Featured</p>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)' }}>accent=&#123;true&#125; adds glow-accent.</p>
          </Card>
        </Row>
      </Group>
    </>
  );
}

function FormsTab() {
  const [text, setText] = React.useState('');
  const [select, setSelect] = React.useState('moss');
  const [checked, setChecked] = React.useState(true);
  const [radio, setRadio] = React.useState('a');
  const [on, setOn] = React.useState(true);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--space-8)' }}>
      <Group label="Input">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 320 }}>
          <Input label="Name" placeholder="Your name" value={text} onChange={(e) => setText(e.target.value)} />
          <Input label="Email" type="email" placeholder="you@example.com" helper="We'll never share this." />
          <Input label="With error" placeholder="you@example.com" error="That doesn't look right" />
        </div>
      </Group>

      <Group label="Select">
        <div style={{ maxWidth: 320 }}>
          <Select
            label="Accent color"
            value={select}
            onChange={(e) => setSelect(e.target.value)}
            options={[
              { value: 'moss', label: 'Moss' },
              { value: 'clay', label: 'Clay' },
              { value: 'sky', label: 'Sky' },
              { value: 'gold', label: 'Gold' },
            ]}
          />
        </div>
      </Group>

      <Group label="Checkbox / Radio / Switch">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Checkbox label="Email me updates" checked={checked} onChange={setChecked} />
          <Radio label="Option A" checked={radio === 'a'} onChange={() => setRadio('a')} />
          <Radio label="Option B" checked={radio === 'b'} onChange={() => setRadio('b')} />
          <Switch label="Available for freelance" checked={on} onChange={setOn} />
        </div>
      </Group>
    </div>
  );
}

function FeedbackTab() {
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [toastOpen, setToastOpen] = React.useState(false);

  return (
    <>
      <Group label="Dialog">
        <Button variant="secondary" onClick={() => setDialogOpen(true)}>Open dialog</Button>
        <Dialog
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          title="Delete Project?"
          actions={[
            <Button key="cancel" variant="ghost" onClick={() => setDialogOpen(false)}>Cancel</Button>,
            <Button key="confirm" variant="danger" onClick={() => setDialogOpen(false)}>Delete</Button>,
          ]}
        >
          This can&rsquo;t be undone — the project and its history will be gone for good.
        </Dialog>
      </Group>

      <Group label="Toast">
        <Row>
          <Button variant="secondary" onClick={() => { setToastOpen(true); setTimeout(() => setToastOpen(false), 3200); }}>
            Trigger toast
          </Button>
        </Row>
        {toastOpen && (
          <div style={{ position: 'fixed', bottom: 28, right: 28, zIndex: 200 }}>
            <Toast tone="moss" message="Message sent — I'll reply soon." onDismiss={() => setToastOpen(false)} />
          </div>
        )}
      </Group>

      <Group label="Tooltip">
        <Row>
          <Tooltip label="Copies to clipboard" side="top">
            <Button variant="ghost" size="sm">Hover me</Button>
          </Tooltip>
        </Row>
      </Group>
    </>
  );
}

function NavigationTab() {
  const [tab, setTab] = React.useState('home');
  return (
    <Group label="Tabs">
      <Tabs
        tabs={[
          { value: 'home', label: 'Home' },
          { value: 'work', label: 'Work' },
          { value: 'about', label: 'About' },
          { value: 'contact', label: 'Contact' },
        ]}
        active={tab}
        onChange={setTab}
      />
      <p style={{ marginTop: 16, fontSize: 14, color: 'var(--text-secondary)' }}>
        Active panel: <strong style={{ color: 'var(--text-primary)' }}>{tab}</strong>
      </p>
    </Group>
  );
}

const CATEGORIES = [
  { value: 'core', label: 'Core', render: CoreTab },
  { value: 'forms', label: 'Forms', render: FormsTab },
  { value: 'feedback', label: 'Feedback', render: FeedbackTab },
  { value: 'navigation', label: 'Navigation', render: NavigationTab },
];

export function ComponentGallery() {
  const [cat, setCat] = React.useState('core');
  const Active = CATEGORIES.find((c) => c.value === cat)?.render || CoreTab;

  return (
    <section id="components" className="ds-section">
      <span className="ds-eyebrow" style={{ color: 'var(--accent-sky)' }}>// 02 — Components</span>
      <h2 style={{ margin: '14px 0 10px' }}>The Primitive Set</h2>
      <p style={{ color: 'var(--text-secondary)', maxWidth: 620, fontSize: 'var(--text-body-md)', marginBottom: 'var(--space-8)' }}>
        Everything below is the real, live component — not a picture of one. Compose these, don&rsquo;t reinvent them.
      </p>

      <Tabs
        tabs={CATEGORIES.map(({ value, label }) => ({ value, label }))}
        active={cat}
        onChange={setCat}
      />

      <div style={{ marginTop: 'var(--space-8)' }}>
        <Active />
      </div>
    </section>
  );
}
