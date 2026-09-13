# Imported Dice account normalization

Direct auth imports can leave NULL values in fields that GoTrue scans as strings.
The September 13 staging login failed with `confirmation_token: converting NULL
 to string is unsupported`. Supabase documents this exact failure:
https://supabase.com/docs/guides/troubleshooting/scan-error-on-column-confirmation_token-converting-null-to-string-is-unsupported-during-auth-login-a0c686

This is a one-time data repair, not an application schema migration or a recurring
release hook. It was applied only to the authorized Cozy Commons target project
`dhjnrnhjghsulbevfhno`, using the existing backend database connection. Never run
it blindly against another project or change an account's ID, password, provider
identity, confirmation state, or non-NULL token.

Before a future import, preserve the source backup and compare these fields on
the imported users. After import, this read-only query must return zero:

```sql
select count(*) as affected_accounts
from auth.users u join public.dice_profiles p on p.user_id = u.id
where u.confirmation_token is null or u.recovery_token is null
   or u.email_change_token_new is null or u.email_change is null;
```

If the same documented failure is present, the following reviewed repair changes
only NULL string fields on users with Dice profiles. It reports whether every
other field is preserved, without returning credentials or account contents:

```sql
with before_rows as materialized (
  select u.id,
    to_jsonb(u) - array['confirmation_token', 'recovery_token',
      'email_change_token_new', 'email_change'] as preserved
  from auth.users u join public.dice_profiles p on p.user_id = u.id
  where u.confirmation_token is null or u.recovery_token is null
     or u.email_change_token_new is null or u.email_change is null
), repaired as (
  update auth.users u set
    confirmation_token = coalesce(u.confirmation_token, ''),
    recovery_token = coalesce(u.recovery_token, ''),
    email_change_token_new = coalesce(u.email_change_token_new, ''),
    email_change = coalesce(u.email_change, '')
  from before_rows b where u.id = b.id
  returning u.id,
    (to_jsonb(u) - array['confirmation_token', 'recovery_token',
      'email_change_token_new', 'email_change']) = b.preserved
      as other_fields_preserved
)
select count(*) as repaired_accounts,
  bool_and(other_fields_preserved) as all_other_fields_preserved
from repaired;
```

Actual result: 19 repaired accounts, all_other_fields_preserved = true.
Independent follow-up audit: zero affected accounts. Real Google sign-in restored
access to the existing mapped profile. No password reset or new account was needed.
Include a real provider-login check in every future identity migration; row counts
and profile foreign keys alone did not catch this import defect.
