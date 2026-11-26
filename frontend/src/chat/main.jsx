import React from 'react';
import { createRoot } from 'react-dom/client';
import '../../../design/cozy-wabi/components.css';
import './chat.css';
import Chat from './Chat.jsx';

function SignIn() {
  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');
  const href = '/auth/google?' + new URLSearchParams({ next: params.get('next') ?? '/' });
  return <main className="chat-login">
    <div className="chat-login__card">
      <a className="chat-home-link" href="https://cozycommons.dev">Cozy Commons</a>
      <h1>Cozy Chat</h1>
      {error && <p className="chat-error" role="alert">{error === 'access' ? 'This Commons account doesn’t have access to Cozy Chat.' : 'Sign-in expired. Please try again.'}</p>}
      <a className="cc-button cc-button--primary" href={href}>Continue with Google</a>
    </div>
  </main>;
}

createRoot(document.getElementById('root')).render(window.location.pathname === '/auth/sign-in' ? <SignIn /> : <Chat />);
