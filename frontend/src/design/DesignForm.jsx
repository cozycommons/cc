import React, { useRef, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

export default function DesignForm() {
  const [recordType, setRecordType] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [range, setRange] = useState([60]);
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState('');
  const nameRef = useRef(null);
  const emailRef = useRef(null);
  const typeRef = useRef(null);
  const confirmationRef = useRef(null);

  function clearError(field) {
    setErrors(current => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  function submit(event) {
    event.preventDefault();
    const next = {};
    if (!nameRef.current.value.trim()) next.name = 'Enter your name.';
    if (!emailRef.current.validity.valid) next.email = 'Enter an email such as hello@example.com.';
    if (!recordType) next.type = 'Choose a record type.';
    if (!confirmed) next.confirmation = 'Confirm that this is a sample record.';
    setErrors(next);
    const first = Object.keys(next)[0];
    if (first) {
      const controls = { name: nameRef, email: emailRef, type: typeRef, confirmation: confirmationRef };
      controls[first].current.focus();
      setStatus('Review the highlighted fields.');
      return;
    }
    setStatus('Sample record saved locally.');
    toast.success('Sample record saved locally.');
  }

  return (
    <form noValidate autoComplete="off" onSubmit={submit}>
      <FieldGroup>
        <FieldGroup className="grid grid-cols-1 sm:grid-cols-2">
          <Field data-invalid={Boolean(errors.name)}>
            <FieldLabel htmlFor="sample-name">Name</FieldLabel>
            <Input id="sample-name" name="name" autoComplete="name" required ref={nameRef} placeholder="Mina Tan…"
              aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? 'name-error' : undefined} onChange={() => clearError('name')} />
            <FieldError id="name-error">{errors.name}</FieldError>
          </Field>
          <Field data-invalid={Boolean(errors.email)}>
            <FieldLabel htmlFor="sample-email">Email</FieldLabel>
            <Input id="sample-email" name="email" type="email" autoComplete="email" inputMode="email" spellCheck={false}
              required ref={emailRef} placeholder="mina@example.com…" aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'email-error' : undefined} onChange={() => clearError('email')} />
            <FieldError id="email-error">{errors.email}</FieldError>
          </Field>
        </FieldGroup>

        <Field data-invalid={Boolean(errors.type)}>
          <FieldLabel htmlFor="sample-type">Record Type</FieldLabel>
          <Select name="recordType" required value={recordType} onValueChange={value => { setRecordType(value); clearError('type'); }}>
            <SelectTrigger id="sample-type" className="w-full" ref={typeRef}
              aria-invalid={Boolean(errors.type)} aria-describedby={errors.type ? 'type-error' : undefined}>
              <SelectValue placeholder="Choose a record type…" />
            </SelectTrigger>
            <SelectContent position="popper"><SelectGroup>
              <SelectItem value="round">Round</SelectItem>
              <SelectItem value="rematch">Rematch</SelectItem>
              <SelectItem value="tournament">Tournament</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
          <FieldError id="type-error">{errors.type}</FieldError>
        </Field>

        <Field>
          <FieldLabel htmlFor="sample-notes">Notes</FieldLabel>
          <Textarea id="sample-notes" name="notes" placeholder="Add context for this record…" rows={3} />
        </Field>

        <FieldSet>
          <FieldLegend variant="label" id="sample-visibility">Visibility</FieldLegend>
          <RadioGroup name="visibility" defaultValue="private" aria-labelledby="sample-visibility">
            <Field orientation="horizontal">
              <RadioGroupItem id="sample-private" value="private" />
              <FieldLabel htmlFor="sample-private">Private</FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <RadioGroupItem id="sample-team" value="team" />
              <FieldLabel htmlFor="sample-team">Team</FieldLabel>
            </Field>
          </RadioGroup>
        </FieldSet>

        <Field orientation="horizontal">
          <Switch id="sample-reminders" name="reminders" />
          <FieldLabel htmlFor="sample-reminders">Reminders</FieldLabel>
        </Field>

        <Field>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium">Priority</span>
            <output className="text-sm text-muted-foreground tabular-nums" aria-hidden="true">{range[0]}%</output>
          </div>
          <Slider name="priority" thumbLabel="Priority" value={range} onValueChange={setRange} />
        </Field>

        <Field orientation="horizontal" data-invalid={Boolean(errors.confirmation)}>
          <Checkbox id="sample-confirmation" name="confirmation" required ref={confirmationRef} checked={confirmed}
            aria-invalid={Boolean(errors.confirmation)} aria-describedby={errors.confirmation ? 'confirmation-error' : 'confirmation-help'}
            onCheckedChange={checked => { setConfirmed(checked === true); clearError('confirmation'); }} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <FieldLabel htmlFor="sample-confirmation">Confirm sample data</FieldLabel>
            <FieldDescription id="confirmation-help">Fields are saved only in this demonstration.</FieldDescription>
            <FieldError id="confirmation-error">{errors.confirmation}</FieldError>
          </div>
        </Field>

        <Field orientation="horizontal" className="flex-wrap">
          <Button type="submit" size="lg">Save Sample</Button>
          <p className="text-sm text-muted-foreground" role="status">{status}</p>
        </Field>
      </FieldGroup>
    </form>
  );
}
