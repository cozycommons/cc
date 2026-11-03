import { useEffect, useState } from 'react';
import { diceApi } from './api.js';

export function useDuoLadder(auth, limit = 100, homepageEligible = false) {
  const token = auth?.token;
  const registered = Boolean(token && auth?.profile);
  const [state, setState] = useState({ ladder: null, error: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setState({ ladder: null, error: false });
    if (registered && typeof diceApi.getDuoLadder === 'function') {
      diceApi.getDuoLadder(token, limit, homepageEligible).then(
        (ladder) => { if (active) setState({ ladder, error: false }); },
        () => { if (active) setState({ ladder: null, error: true }); },
      );
    }
    return () => { active = false; };
  }, [token, registered, limit, homepageEligible, attempt]);

  return { ...state, registered, retry: () => setAttempt((value) => value + 1) };
}
