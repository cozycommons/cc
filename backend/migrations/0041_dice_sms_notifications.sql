-- Lets Dice players opt in to SMS notifications for ranked game results,
-- delivered via Twilio to the phone number they provide in profile settings.
alter table public.dice_profiles
  add column if not exists phone_number text,
  add column if not exists sms_notifications_enabled boolean not null default false;
