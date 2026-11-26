import React from 'react';
import { SegmentedControl as SdkSegments, SegmentedControlItem } from '@ui-sdk/react/segmented-control';
import { Collapsible, CollapsibleTrigger, CollapsiblePanel, Progress, ProgressTrack, ProgressIndicator } from './Controls.jsx';
import '../../../../design/cozy-wabi/data-patterns.css';

export function SegmentedControl({ label, options, value, onChange }) {
  const labelId = React.useId();
  return <div className="cc-picker">
    <span className="cc-label" id={labelId}>{label}</span>
    <SdkSegments className="cc-picker__track" aria-labelledby={labelId} value={value} onValueChange={onChange}
      style={{ '--segments': options.length }}>
      {options.map(option => <SegmentedControlItem className="cc-picker__option" key={option.value} value={option.value}>
        <span>{option.label}</span>
      </SegmentedControlItem>)}
    </SdkSegments>
  </div>;
}

export function DataRow({ title, subtitle, value, children }) {
  return <Collapsible className="cc-data-row">
    <CollapsibleTrigger className="cc-data-row__trigger"><span className="cc-data-row__name"><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}</span><span className="cc-data-row__value">{value}</span><span className="cc-data-row__chevron" aria-hidden="true">+</span></CollapsibleTrigger>
    <CollapsiblePanel className="cc-data-row__detail">{children}</CollapsiblePanel>
  </Collapsible>;
}

export function ComparisonBar({ label, value, total, leftLabel, rightLabel }) {
  const share = total > 0 ? Math.min(100, Math.max(0, value / total * 100)) : 0;
  return <div className="cc-comparison" role="group" aria-label={label}>
    <div className="cc-comparison__labels"><span>{leftLabel}</span><span>{rightLabel}</span></div>
    <Progress value={share} aria-label={label} aria-hidden="true"><ProgressTrack className="cc-comparison__track"><ProgressIndicator render={<span />} /></ProgressTrack></Progress>
  </div>;
}

export function Skeleton({ label = 'Loading' }) {
  return <div className="cc-skeleton" role="status"><span className="cc-sr-only">{label}</span><div aria-hidden="true"><i /><i /><i /></div></div>;
}
