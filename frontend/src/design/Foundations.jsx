import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const pairs = [
  ['Background', 'bg-background text-foreground'],
  ['Primary', 'bg-primary text-primary-foreground'],
  ['Muted', 'bg-muted text-muted-foreground'],
  ['Accent', 'bg-accent text-accent-foreground'],
];

export default function Foundations() {
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle><h3>Color Roles</h3></CardTitle>
          <CardDescription>Use each surface with its matching text token.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid grid-cols-2 gap-2">
            {pairs.map(([name, colors]) => (
              <li key={name} className={cn('flex min-h-12 items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm font-medium', colors)}>
                {name}<span aria-hidden="true">Aa</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <Card id="typography" className="scroll-mt-20">
        <CardHeader>
          <CardTitle><h3>Typography</h3></CardTitle>
          <CardDescription>Geist for headings, copy, and controls.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-2xl font-semibold tracking-tight text-balance">Workspace Overview</p>
          <p className="text-base">Manage team access and project settings.</p>
          <p className="text-sm text-muted-foreground tabular-nums">Updated 12 minutes ago</p>
        </CardContent>
      </Card>
    </div>
  );
}
