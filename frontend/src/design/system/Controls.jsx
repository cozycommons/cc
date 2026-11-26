import React from 'react';
import { Button as SdkButton } from '@ui-sdk/react/button';
import { Input as SdkInput } from '@ui-sdk/react/input';
import { Textarea as SdkTextarea } from '@ui-sdk/react/textarea';
import { Avatar, AvatarImage, AvatarFallback } from '@ui-sdk/react/avatar';
import { Checkbox, CheckboxIndicator } from '@ui-sdk/react/checkbox';
import { Select, SelectLabel, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@ui-sdk/react/select';
import { ToastRegion, Toast, ToastTitle, ToastClose, createToaster } from '@ui-sdk/react/toast';
import './controls.css';

export { Dialog, DialogBackdrop, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@ui-sdk/react/dialog';
export { Tabs, TabsList, TabsPanel, TabsTab } from '@ui-sdk/react/tabs';
export { Collapsible, CollapsibleTrigger, CollapsiblePanel } from '@ui-sdk/react/collapsible';
export { Accordion, AccordionItem, AccordionHeader, AccordionTrigger, AccordionPanel } from '@ui-sdk/react/accordion';
export { RadioGroup, Radio, RadioIndicator } from '@ui-sdk/react/radio';
export { Switch, SwitchThumb } from '@ui-sdk/react/switch';
export { Slider, SliderValue, SliderControl, SliderTrack, SliderIndicator, SliderThumb } from '@ui-sdk/react/slider';
export { Progress, ProgressTrack, ProgressIndicator } from '@ui-sdk/react/progress';
export { FileInput, FileInputList, FileInputItem, FileInputItemRemove, FileInputTrigger } from '@ui-sdk/react/file-input';
export { ScrollArea, ScrollAreaViewport, ScrollAreaContent } from '@ui-sdk/react/scroll-area';
export { Field, FieldLabel } from '@ui-sdk/react/field';
export { createToaster };

export function Button({ variant = 'secondary', size, className = '', ...props }) {
  const classes = ['cc-button', `cc-button--${variant}`, size && `cc-button--${size}`, className].filter(Boolean).join(' ');
  return <SdkButton className={classes} {...props} />;
}

export function Input({ className = '', ...props }) {
  return <SdkInput className={`cc-input ${className}`} {...props} />;
}

export function Textarea({ className = '', ...props }) {
  return <SdkTextarea className={`cc-textarea ${className}`} {...props} />;
}

export function Choice({ children, className = '', ...props }) {
  return <label className={`cc-choice ${className}`}>
    <Checkbox className="cc-check" {...props}><CheckboxIndicator aria-hidden="true">✓</CheckboxIndicator></Checkbox>
    {children}
  </label>;
}

export function SelectField({ label, options, placeholder, triggerProps, ...props }) {
  return <Select className="cc-select-field" placeholder={placeholder} {...props}>
    <SelectLabel className="cc-label">{label}</SelectLabel>
    <SelectTrigger className="cc-select" {...triggerProps}><SelectValue /></SelectTrigger>
    <SelectContent className="cc-select-options">
      {options.map(({ value, label }) => <SelectItem className="cc-select-option" key={value} value={value}>{label}</SelectItem>)}
    </SelectContent>
  </Select>;
}

export function PersonAvatar({ name, src, tone = 'clay', decorative = false }) {
  return <Avatar className={`cc-avatar cc-avatar--${tone}`} aria-label={decorative ? undefined : name} aria-hidden={decorative || undefined}>
    {src && <AvatarImage src={src} alt="" referrerPolicy="no-referrer" />}
    <AvatarFallback>{name.trim().slice(0, 1).toUpperCase() || '?'}</AvatarFallback>
  </Avatar>;
}

export function Toasts({ toaster }) {
  return <ToastRegion className="cc-toast-region" toaster={toaster} aria-label="Notifications">
    {() => <Toast className="cc-toast">
      <span className="cc-toast__mark" aria-hidden="true">·</span><ToastTitle />
      <ToastClose className="cc-toast__close" aria-label="Dismiss toast">×</ToastClose>
    </Toast>}
  </ToastRegion>;
}
