import React, { useId } from 'react';
import '../design-utilities.css';
import { ChevronDown } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Skeleton as LoadingBlock } from '@/components/ui/skeleton';
import '../../../../design/cozy-wabi/data-patterns.css';

export function SegmentedControl({ label, options, value, onChange }) {
  const id = useId();
  const selected = Math.max(0, options.findIndex(option => option.value === value));
  return <fieldset className="cc-picker">
    <legend className="cc-label" id={id}>{label}</legend>
    <RadioGroup className="cc-picker__track" aria-labelledby={id} value={value} onValueChange={onChange}
      style={{ '--segments': options.length, '--selected': selected }}>
      <span className="cc-picker__indicator" aria-hidden="true" />
      {options.map(option => (
        <Label className="cc-picker__option" key={option.value}>
          <RadioGroupItem className="cc-picker__radio" aria-label={option.label} value={option.value} />
          <span>{option.label}</span>
        </Label>
      ))}
    </RadioGroup>
  </fieldset>;
}

export function DataRow({ title, subtitle, value, children }) {
  return <Collapsible className="cc-data-row">
    <CollapsibleTrigger className="cc-data-row__trigger">
      <span className="cc-data-row__name"><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}</span>
      <span className="cc-data-row__value">{value}</span>
      <ChevronDown className="cc-data-row__chevron size-4" aria-hidden="true" />
    </CollapsibleTrigger>
    <CollapsibleContent className="cc-data-row__detail">{children}</CollapsibleContent>
  </Collapsible>;
}

export function Skeleton({ label = 'Loading' }) {
  return <div className="grid min-h-[120px] content-center gap-3" role="status">
    <span className="sr-only">{label}</span>
    <LoadingBlock aria-hidden="true" className="h-4 w-full motion-reduce:animate-none" />
    <LoadingBlock aria-hidden="true" className="h-4 w-3/4 motion-reduce:animate-none" />
    <LoadingBlock aria-hidden="true" className="h-4 w-2/5 motion-reduce:animate-none" />
  </div>;
}
