# Commons roles

## Summary

Cozy Commons owns account roles. Admins manage access from the Users screen in
`/admin`, without editing Supabase Auth metadata. Supabase continues to own identity.

Design: existing admin components; Jason confirmed reusing the existing design.

## Behavior

1. Verified accounts are members by default. Commons admins share administrator
   privileges across analytics, Dice, Trips, Fantasy, and hosted Crowdset.
2. An admin can search existing non-anonymous accounts by name or email and page
   through results. Each account shows its name, email, verification, and role.
3. Admins can promote verified members and demote admins. Unverified accounts
   cannot become admins. No account is created by assigning a role.
4. Changes require an explicit confirmation identifying the account and new role.
   Pending operations disable conflicting controls. Errors retain the current view
   and offer refresh; successful changes refresh the authoritative roles.
5. Members and signed-out visitors cannot list accounts, view role history, or
   change roles. Browser-editable profile metadata never grants permissions.
6. Each protected server request uses the current role. Revocation applies to
   subsequent requests, even when the user still has an existing sign-in session.
7. The last verified admin cannot be demoted. Simultaneous changes cannot leave
   zero admins or allow a newly demoted admin to issue a role change.
8. A stale role edit is rejected with a refresh instruction. Repeating an already
   completed change does not create duplicate history.
9. Role changes record the actor, target, previous role, new role, and timestamp.
   Admins can inspect recent history. Accounts and auth secrets are not editable.
10. A one-time migration preserves existing verified administrators, including
    Jason's account. Old email allowlists and Auth metadata stop granting access
    after migration; registering later with an old allowlisted email grants nothing.
11. Role storage failures deny privileged actions and report unavailable service;
    they never fall back to old administrator flags.
