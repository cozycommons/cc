import React, { useEffect } from 'react';
import './design-utilities.css';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Clipboard, Layers3, Settings2, TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { Toaster } from '@/components/ui/sonner';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import '@fontsource-variable/geist';
import DataShowcase, { MemberTable } from './DataShowcase.jsx';
import DesignForm from './DesignForm.jsx';
import Foundations from './Foundations.jsx';

const sections = [
  ['foundations', 'Foundations'],
  ['buttons', 'Actions'],
  ['controls', 'Forms'],
  ['data-patterns', 'Data Display'],
  ['feedback', 'Feedback'],
  ['overlays', 'Overlays'],
];

function Section({ id, title, children }) {
  return <section className="flex min-w-0 flex-col gap-4" aria-labelledby={id}>
    <h2 id={id} className="scroll-mt-20 text-xl font-semibold tracking-tight text-balance">{title}</h2>
    {children}
  </section>;
}

function ActionExamples() {
  return <Card>
    <CardHeader>
      <CardTitle><h3>Buttons</h3></CardTitle>
      <CardDescription>Use the primary variant for the main action.</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-wrap items-center gap-2">
      <Button type="button" onClick={() => toast.success('Primary action selected.')}>Primary</Button>
      <Button type="button" variant="secondary" onClick={() => toast('Secondary action selected.')}>Secondary</Button>
      <Button type="button" variant="outline" onClick={() => toast('Outline action selected.')}>Outline</Button>
      <Button type="button" variant="ghost" onClick={() => toast('Ghost action selected.')}>Ghost</Button>
      <Button type="button" disabled>Disabled</Button>
    </CardContent>
  </Card>;
}

function FeedbackExamples() {
  return <div className="grid min-w-0 items-start gap-4 md:grid-cols-2">
    <Alert>
      <CheckCircle2 aria-hidden="true" />
      <AlertTitle>Record Saved</AlertTitle>
      <AlertDescription>The sample record is ready.</AlertDescription>
    </Alert>
    <Alert variant="destructive">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Record Needs Attention</AlertTitle>
      <AlertDescription>Enter a valid email address and try again.</AlertDescription>
    </Alert>
  </div>;
}

function ConfirmDialog() {
  return <Dialog>
    <DialogTrigger asChild><Button type="button" variant="outline">Open Dialog</Button></DialogTrigger>
    <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto overscroll-contain">
      <DialogHeader>
        <DialogTitle>Keep the Sample Note?</DialogTitle>
        <DialogDescription>This confirmation saves a note to the local demonstration.</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <DialogClose asChild><Button type="button" variant="outline">Cancel</Button></DialogClose>
        <DialogClose asChild><Button type="button" onClick={() => toast.success('Sample note saved.')}>Keep Note</Button></DialogClose>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

async function copyButtonImport() {
  try {
    await navigator.clipboard.writeText('import { Button } from "@/components/ui/button"');
    toast.success('Button import copied.');
  } catch {
    toast.error('Couldn’t copy the Button import. Select and copy it manually.');
  }
}

export default function DesignIndex() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('members') === 'archived' ? 'archived' : 'current';

  useEffect(() => {
    const documentRoot = document.documentElement;
    documentRoot.classList.add('commons-theme');
    return () => documentRoot.classList.remove('commons-theme');
  }, []);

  function setTab(value) {
    setParams(current => {
      const next = new URLSearchParams(current);
      if (value === 'archived') next.set('members', value);
      else next.delete('members');
      return next;
    }, { preventScrollReset: true });
  }

  return <TooltipProvider delayDuration={250}>
    <div className="min-h-screen bg-background text-foreground">
      <a href="#design-main" className="sr-only rounded-md bg-background p-3 focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50">Skip to Content</a>
      <header className="border-b bg-background">
        <div className="mx-auto flex min-h-16 max-w-[86rem] flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2 sm:px-8">
          <Link to="/" className="flex min-h-11 items-center gap-2 rounded-md font-medium tracking-tight hover:text-accent-foreground">
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground"><Layers3 className="size-4" aria-hidden="true" /></span>
            <span translate="no">Cozy Commons</span>
          </Link>
          <Button asChild variant="ghost" className="min-h-11">
            <Link to="/"><ArrowLeft data-icon="inline-start" aria-hidden="true" /> Projects</Link>
          </Button>
        </div>
      </header>

      <div className="mx-auto grid max-w-[86rem] gap-7 px-4 py-6 sm:px-8 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-12 lg:py-10">
        <aside className="min-w-0 self-start md:sticky md:top-6">
          <nav className="flex flex-wrap gap-1 md:flex-col" aria-label="Design System Sections">
            {sections.map(([id, label]) => (
              <Button key={id} variant="ghost" asChild className="min-h-11 justify-start">
                <a href={`#${id}`}>{label}</a>
              </Button>
            ))}
          </nav>
        </aside>

        <main id="design-main" tabIndex={-1} className="flex min-w-0 flex-col gap-9 pb-12">
          <header className="flex flex-col gap-3 border-b pb-7">
            <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">Design System</h1>
            <p className="max-w-[48ch] text-base text-muted-foreground">Shared React components for Cozy Commons, built with shadcn/ui.</p>
          </header>

          <Section id="foundations" title="Foundations"><Foundations /></Section>

          <Section id="buttons" title="Actions">
            <div className="grid gap-4 lg:grid-cols-[1.15fr_1fr]">
              <ActionExamples />
              <Card>
                <CardHeader>
                  <CardTitle><h3>Component Import</h3></CardTitle>
                  <CardDescription>Import components from the shared registry directory.</CardDescription>
                </CardHeader>
                <CardContent className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <code className="min-w-0 flex-1 break-words rounded-md bg-muted p-3 text-sm" translate="no">import {'{ Button }'} from &quot;@/components/ui/button&quot;</code>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button type="button" variant="outline" size="icon" className="size-11" aria-label="Copy Button Import" onClick={copyButtonImport}>
                        <Clipboard aria-hidden="true" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Copy Button import</TooltipContent>
                  </Tooltip>
                </CardContent>
              </Card>
            </div>
          </Section>

          <div className="grid min-w-0 items-start gap-5 xl:grid-cols-2">
            <Section id="controls" title="Forms">
              <Card>
                <CardHeader>
                  <CardTitle><h3>Create a Sample Record</h3></CardTitle>
                  <CardDescription>Form controls with local validation.</CardDescription>
                </CardHeader>
                <CardContent><DesignForm /></CardContent>
              </Card>
            </Section>

            <Section id="data-patterns" title="Data Display">
              <div id="tabs" className="scroll-mt-20"><MemberTable tab={tab} onTabChange={setTab} /></div>
              <DataShowcase />
            </Section>
          </div>

          <Section id="feedback" title="Feedback">
            <FeedbackExamples />
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="default">Published</Badge><Badge variant="secondary">Draft</Badge><Badge variant="outline">Archived</Badge>
              <Button type="button" variant="outline" className="ml-auto" onClick={() => toast('Preview notification')}>Show Toast</Button>
            </div>
          </Section>

          <Section id="overlays" title="Overlays and Disclosure">
            <Card>
              <CardHeader>
                <CardTitle><h3>Review a Change</h3></CardTitle>
                <CardDescription>Dialog confirmation and collapsible settings.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col items-start gap-4">
                <ConfirmDialog />
                <Separator />
                <div id="disclosure" className="w-full scroll-mt-20">
                  <Collapsible className="flex flex-col gap-3">
                    <CollapsibleTrigger asChild>
                      <Button type="button" variant="ghost" className="justify-start"><Settings2 data-icon="inline-start" aria-hidden="true" /> Advanced Settings</Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="text-sm text-muted-foreground">Sample settings apply only to this page.</CollapsibleContent>
                  </Collapsible>
                  <Accordion type="single" collapsible>
                    <AccordionItem value="behavior">
                      <AccordionTrigger>Keyboard Controls</AccordionTrigger>
                      <AccordionContent>Use Tab to move between controls and Escape to dismiss overlays.</AccordionContent>
                    </AccordionItem>
                    <AccordionItem value="theme">
                      <AccordionTrigger>Theme</AccordionTrigger>
                      <AccordionContent>The Commons theme follows your system’s color preference.</AccordionContent>
                    </AccordionItem>
                  </Accordion>
                </div>
              </CardContent>
            </Card>
          </Section>
        </main>
      </div>
      <Toaster closeButton />
    </div>
  </TooltipProvider>;
}
