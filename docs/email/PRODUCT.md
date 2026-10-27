# Cozy Commons email

## Summary

Give our small group of friends addresses such as `jason@cozycommons.dev`,
with a choice of a dedicated inbox or forwarding to an existing address.
Allow members to make selected email available to agents and Cozy Commons
server code, and trigger automations when messages arrive.

Status: proposal, recorded 2026-10-27. No implementation or provisioning yet.
Jason is leaning toward AgentMail; provider selection is not final.
This is for an invited group of friends, not public email hosting for all
Cozy Commons users.

## Provider comparison

Pricing and capabilities below are a research snapshot as of 2026-10-27.
Recheck before purchasing. Domain registration is separate in every option;
free software does not include hosting, backups, or maintenance.

| Option | Hosting | Free offering | Custom-domain cost | Personal email experience | Automation and agent access | Assessment for us |
| --- | --- | --- | --- | --- | --- | --- |
| **AgentMail — preferred candidate** | Managed service | 3 inboxes, 3,000 emails/month, 3 GB storage; no custom domains | Listed Developer plan: $20/month for 10 inboxes, 10,000 emails/month, 10 GB storage, and 10 custom domains | Persistent mailboxes with threads, drafts, attachments, and IMAP/SMTP access; validate everyday mail-client use, forwarding, and independent user access | Inbox APIs, Python/TypeScript SDKs, MCP, and inbox-specific webhooks | Closest match to the programmable inbox idea; validate human account isolation before adopting |
| **Stalwart** | Self-hosted | Community edition is free under AGPL-3.0 | No Community software subscription; infrastructure and operations cost extra | Full mailboxes accessible through compatible clients; choose a webmail interface separately | JMAP mail API, change notifications, and server-event webhooks | Preferred self-hosted alternative if operating email infrastructure is part of the goal |
| **Fastmail** | Managed service | Trial; no ongoing free mailbox plan | Paid subscription; verify plan eligibility and current group pricing | Complete personal email service, custom domains, forwarding, and mail apps | JMAP API and official MCP server with separate read, write, and send access; MCP currently excludes attachments | Strong alternative when the human inbox experience takes priority |
| **Resend** | Managed application email service | Limited free sending/receiving tier; verify current quotas | Subject to plan limits | Do not assume it supplies independent personal mailboxes and a complete daily mail experience | Sending/receiving APIs, inbound webhooks, and attachment retrieval | Useful candidate for application-specific addresses; evaluate separately from personal hosting |
| **Cloudflare Email Routing** | Managed forwarding | Custom-domain forwarding to existing inboxes | Routing can be free; storage and general outbound sending need a separate solution | Members continue using their existing inboxes | Email processing can be added separately; forwarding alone does not grant access to the destination inbox | Simplest free forwarding option, but does not meet the full mailbox requirement alone |

AgentMail's advertised inbox count is not the same as a count of independently
managed human accounts. Its Developer plan currently lists two organization
seats. Confirm whether our intended access model fits the plan rather than
sharing an organization-wide key with friends or agents.

## Why AgentMail is the current preference

Its product centers on creating and managing persistent inboxes through code,
with events that can trigger our own workflows. That aligns with combining
friend-facing addresses and email-powered Cozy Commons features. A free
provider-domain prototype can precede a paid custom-domain pilot.

AgentMail is a commercial, venture-backed developer infrastructure startup,
founded in 2025 and based in San Francisco. It participated in Y Combinator's
Summer 2025 batch. Its founders are Haakam Aujla, Michael Kim, and Adi Singh.
The company announced a $6 million seed round led by General Catalyst in
March 2026. Its core audience is developers building email-capable agents;
suitability as our friends' everyday email provider remains to be demonstrated.

## Proposed behavior

These are draft requirements for review, not approved implementation decisions.

1. Each invited member can have a unique `name@cozycommons.dev` address.
   Address ownership is associated with the member; the group administrator
   manages provisioning. Naming and address reassignment rules remain open.
2. Members can choose a dedicated mailbox, forwarding to a verified existing
   address, or both. The chosen provider must support the selected mode before
   we promise it to a member. Forwarding failures must be observable.
3. Receiving forwarded mail does not imply the ability to reply as the Cozy
   Commons address. Sending from that address is a separately configured and
   tested capability. Forwarding alone does not expose destination-inbox
   history, replies, sent mail, or deletions to Cozy Commons.
4. Agent and server access is optional per member. Proposed initial default:
   automation is disabled until the member enables it, with selected-message
   access preferred over access to the entire mailbox.
5. Reading, changing mail or creating drafts, and sending are distinct
   permissions. An agent with read access cannot send. Members can revoke
   automation access without losing normal delivery or their mailbox.
6. One member's agents and workflows cannot read or act on another member's
   email without an explicit grant. Provider organization-level credentials
   are never handed directly to individual clients or agents.
7. Listeners can trigger processing for enabled mailboxes or selected messages.
   Duplicate notifications and retries must not cause duplicate product actions.
   Missed notifications must be recoverable through mailbox reconciliation.
8. Workflows can extract information, suggest product updates, or draft replies
   according to the member's permissions. Email content supplies data, not
   authority to change permissions or direct unrelated agent actions.
9. Members can inspect processing results and failures. Logs must not expose
   credentials or email contents to other members. Retention and deletion rules
   must be settled before storing real personal email in Cozy Commons.
10. A possible first workflow is reservation email to a proposed Cozy Trips
    entry. This is a suggested pilot, not a selected or implemented feature.

## Questions to resolve before implementation

| Question | What needs to be established |
| --- | --- |
| AgentMail access model | Can each friend use their mailbox privately through a normal client without access to other inboxes? How do scoped credentials, organization seats, and revocation work? |
| Human email experience | Do sending, receiving, replies, threads, drafts, attachments, search, and forwarding work well in the clients our friends use? |
| Automation scope | Selected messages, a dedicated automation address, or whole-mailbox access? What actions may run without confirmation? |
| Provider events | Which events are available, what do they contain, and how do signatures, retries, ordering, and recovery work? |
| Domain routing | Which provider receives mail for `cozycommons.dev`? If an application email provider is separate, should it use a subdomain? DNS does not route individual people to providers by mailbox name. |
| Data and portability | What are the provider's retention, deletion, export, and backup capabilities? What email data do we keep ourselves, and for how long? |
| Budget | How many friends need stored mailboxes versus forwarding, what usage limits apply, and is the listed $20/month plan sufficient? |
| Pilot scope | Which account and workflow do we test before inviting the rest of the group? |

## Sources

- AgentMail: [pricing](https://www.agentmail.to/pricing), [free-plan custom-domain restriction](https://www.agentmail.to/docs/knowledge-base/agent-sign-up-limits), [inbox capabilities](https://docs.agentmail.to/knowledge-base/inbox-capabilities), [inbox webhooks](https://docs.agentmail.to/api-reference/inboxes/webhooks/create).
- Company background: [Y Combinator profile](https://www.ycombinator.com/companies/agentmail), [AgentMail funding announcement, March 10, 2026](https://www.globenewswire.com/news-release/2026/03/10/3253159/0/en/agentmail-raises-6m-led-by-general-catalyst-to-build-the-first-email-provider-for-ai-agents.html).
- Stalwart: [editions](https://www.stalw.art/compare/), [JMAP](https://stalw.art/docs/http/jmap/), [webhooks](https://stalw.art/docs/telemetry/webhooks/).
- Fastmail: [pricing](https://www.fastmail.com/pricing/us/), [developer API](https://www.fastmail.com/dev/), [MCP access and limitations](https://www.fastmail.help/hc/en-us/articles/15869557281295-Connecting-AI-tools-via-Fastmail-s-MCP-server), [forwarding](https://www.fastmail.help/hc/en-us/articles/360058753434-Set-up-mail-forwarding).
- Resend: [pricing](https://resend.com/pricing), [inbound email](https://resend.com/features/inbound).
- Cloudflare: [Email Service pricing](https://developers.cloudflare.com/email-service/platform/pricing/).
