import React from 'react';
import { createRoot } from 'react-dom/client';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import './chat.css';
import Chat from './Chat.jsx';

function SignIn() {
  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');
  const href = '/auth/google?' + new URLSearchParams({ next: params.get('next') ?? '/' });

  return <main className="chat-login">
    <Card className="chat-login__card">
      <CardHeader>
        <a className="chat-home-link" translate="no" href="https://cozycommons.dev">Cozy Commons</a>
        <CardTitle><h1 translate="no">Cozy Chat</h1></CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-4">
        {error && <Alert variant="destructive" role="alert">
          <AlertDescription>{error === 'access' ? 'This Commons account doesn’t have access to Cozy Chat.' : 'Sign-in expired. Please try again.'}</AlertDescription>
        </Alert>}
        <Button asChild><a href={href}>Continue with Google</a></Button>
      </CardContent>
    </Card>
  </main>;
}

createRoot(document.getElementById('root')).render(window.location.pathname === '/auth/sign-in' ? <SignIn /> : <Chat />);
