import React, { useEffect, useRef, useState } from 'react';
import { Archive, RefreshCw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Field, FieldLegend, FieldSet } from '@/components/ui/field';
import { Progress } from '@/components/ui/progress';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const records = {
  week: [18, 6],
  month: [64, 28],
  season: [142, 76],
};
const periods = { week: 'Week', month: 'Month', season: 'Season' };
const members = [
  { id: 'mina', name: 'Mina Tan', initials: 'MT', role: 'Owner', status: 'Active' },
  { id: 'jo', name: 'Jo Alvarez', initials: 'JA', role: 'Editor', status: 'Active' },
  { id: 'kai', name: 'Kai Shah', initials: 'KS', role: 'Viewer', status: 'Invited' },
];
const numberFormatter = new Intl.NumberFormat();

function Completion() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('period');
  const period = Object.hasOwn(records, selected) ? selected : 'week';
  function setPeriod(value) {
    setParams(current => {
      const next = new URLSearchParams(current);
      if (value === 'week') next.delete('period');
      else next.set('period', value);
      return next;
    }, { preventScrollReset: true });
  }

  const [played, remaining] = records[period];
  const total = played + remaining;
  return <Card>
    <CardHeader>
      <CardTitle><h3>Schedule Completion</h3></CardTitle>
      <CardDescription>Compare played and remaining games.</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col gap-5">
      <FieldSet>
        <FieldLegend variant="label" id="record-period">Period</FieldLegend>
        <RadioGroup value={period} onValueChange={setPeriod} aria-labelledby="record-period" className="flex flex-wrap gap-4">
          {Object.entries(periods).map(([value, label]) => (
            <Field orientation="horizontal" className="w-auto" key={value}>
              <RadioGroupItem id={`period-${value}`} value={value} />
              <Label htmlFor={`period-${value}`}>{label}</Label>
            </Field>
          ))}
        </RadioGroup>
      </FieldSet>
      <div className="flex flex-col gap-3" role="group" aria-label="Schedule completion">
        <p className="text-2xl font-semibold tracking-tight tabular-nums">
          {numberFormatter.format(played)} <span className="text-base font-normal text-muted-foreground">of {numberFormatter.format(total)} games</span>
        </p>
        <Progress value={played / total * 100} aria-label="Games played" />
        <div className="flex justify-between gap-2 text-sm text-muted-foreground tabular-nums">
          <span>{numberFormatter.format(played)} played</span>
          <span>{numberFormatter.format(remaining)} remaining</span>
        </div>
      </div>
    </CardContent>
  </Card>;
}

function RefreshExample() {
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState(false);
  const timer = useRef();
  useEffect(() => () => clearTimeout(timer.current), []);

  function refresh() {
    setLoading(true);
    timer.current = setTimeout(() => { setLoading(false); setUpdated(true); }, 1200);
  }

  return <Card>
    <CardHeader>
      <CardTitle><h3>Refresh and Loading</h3></CardTitle>
      <CardDescription>Keep the current value visible during refresh.</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col items-start gap-4">
      <div className="w-full rounded-lg border bg-muted/50 p-4" aria-busy={loading}>
        <p className="text-sm text-muted-foreground">Weekly activity</p>
        <p className="text-xl font-semibold tabular-nums">24 games</p>
        {loading && <div className="mt-3" role="status"><span className="sr-only">Loading sample activity</span><Skeleton className="h-2 w-2/3 motion-reduce:animate-none" /></div>}
      </div>
      <Button variant="outline" type="button" onClick={refresh} disabled={loading}>
        {loading ? <Spinner data-icon="inline-start" aria-hidden="true" /> : <RefreshCw data-icon="inline-start" aria-hidden="true" />}
        {loading ? 'Refreshing…' : 'Preview Refresh'}
      </Button>
      <p className="text-sm text-muted-foreground" role="status">{updated && !loading ? 'Sample updated just now.' : ''}</p>
    </CardContent>
  </Card>;
}

export function MemberTable({ tab, onTabChange }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle><h3>Members</h3></CardTitle>
        <CardDescription>Tabs, avatars, badges, and table rows.</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs value={tab} onValueChange={onTabChange}>
          <TabsList aria-label="Member views">
            <TabsTrigger value="current">Current</TabsTrigger>
            <TabsTrigger value="archived">Archived</TabsTrigger>
          </TabsList>
          <TabsContent value="current">
            <Table>
              <TableCaption className="sr-only">Sample workspace members, roles, and access status</TableCaption>
              <TableHeader><TableRow><TableHead>Member</TableHead><TableHead>Role</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>
                {members.map(member => (
                  <TableRow key={member.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-3">
                        <Avatar aria-hidden="true" className="shrink-0"><AvatarFallback>{member.initials}</AvatarFallback></Avatar>
                        <span>{member.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{member.role}</TableCell>
                    <TableCell><Badge variant={member.status === 'Active' ? 'secondary' : 'outline'}>{member.status}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="archived">
            <Empty className="px-3 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon"><Archive aria-hidden="true" /></EmptyMedia>
                <EmptyTitle>No Archived Members</EmptyTitle>
                <EmptyDescription>Archived members will appear here.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

export default function DataShowcase() {
  return <div className="grid items-start gap-4 lg:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2"><Completion /><RefreshExample /></div>;
}
