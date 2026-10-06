# ALXPRGS Design Language v1

**Status:** Draft specification  
**Target:** ALXPRGS SSO and future ALXPRGS infrastructure interfaces  
**Primary surfaces:** Authentication, Account, Security, Administration, Developer/Internal Tools  
**Design orientation:** Dark-first  
**Audience:** Primarily the project owner and collaborators; not a commercial SaaS product  
**Implementation target:** React + Tailwind CSS + accessible headless primitives + Motion

---

# 1. Product identity

ALXPRGS interfaces should feel like a serious modern developer platform built for real infrastructure rather than a marketing website.

The visual language combines:

**WorkOS**
for calm authentication flows and interactive technical visuals.

**Linear**
for information density, visual hierarchy, keyboard-first workflows and restrained application chrome.

**Vercel / Geist**
for typography, developer-oriented clarity and reusable design-system discipline.

**Cloudflare**
for practical infrastructure dashboards, semantic theming and subtle everyday motion.

ALXPRGS must not visually imitate any one of these products.

The objective is to create an identifiable ALXPRGS interface language.

---

# 2. Core design statement

> ALXPRGS is a dark-first, motion-rich developer infrastructure interface: calm where users authenticate, dense where operators work, visually technical without looking like a terminal, and animated without becoming decorative noise.

The system should communicate four characteristics simultaneously:

**Technical.**  
It is infrastructure, identity and security software.

**Calm.**  
Authentication must never feel complicated merely because the underlying implementation is sophisticated.

**Alive.**  
Interfaces should respond smoothly and visibly to user actions.

**Fast.**  
Animations must reinforce perceived responsiveness rather than delay interaction.

---

# 3. Design principles

## 3.1 Content before chrome

Application content is more important than containers, borders and decoration.

Do not place every section inside its own card.

Structure should primarily come from:

spacing, hierarchy, typography, background levels and alignment.

Borders are secondary.

---

## 3.2 Motion communicates state

Animation is a core part of ALXPRGS.

It is used to communicate:

state changes, navigation, hierarchy, completion, causality and spatial relationships.

Animation must never exist purely to slow the user down.

---

## 3.3 Authentication must feel simpler than the technology behind it

A normal user should not need to understand:

WebAuthn, Argon2id, RFC numbers, internal capability flags, challenge identifiers, UUIDs or protocol terminology.

Such information belongs in administration, diagnostics or explicitly requested technical details.

---

## 3.4 Security is not negotiable for visual convenience

A redesign must not weaken:

OIDC validation, redirect validation, PKCE, session semantics, CSRF protection, reauthentication, MFA requirements, WebAuthn validation, legal-consent enforcement, account-deletion restrictions or server-side authorization.

The frontend may change radically.

Security contracts must remain intact.

---

## 3.5 Density depends on context

Authentication UI is spacious.

Account settings use moderate density.

Administration is intentionally dense.

The same typography and component language applies to all three, but layout density is contextual.

---

# 4. Existing implementation context

The current project already contains useful foundations such as React, TypeScript, semantic theme colours and some accessible dialog behaviour.

However, the current frontend also uses manually implemented utility-like CSS classes without Tailwind itself, and several classes referenced by JSX do not exist. It also lacks a conventional routing layer and relies on manual pathname/state handling. 

ALXPRGS Design Language v1 therefore assumes that the presentation architecture may be replaced rather than patched indefinitely.

The existing semantic palette is useful inspiration, but it is not treated as a permanent compatibility requirement.

---

# 5. Brand

## 5.1 Official logo

The existing ALXPRGS logo assets are the canonical brand identity.

Use the actual ALXPRGS logo.

Do not recreate the brand as a letter `A` inside an arbitrary blue square.

Approved source assets include the official SVG and corresponding avatar/icon versions hosted under ALXPRGS assets infrastructure.

---

## 5.2 Logo roles

Use the full mark or wordmark when sufficient horizontal space exists.

Use the icon mark for:

favicon, collapsed navigation, mobile navigation, compact identity elements and loading/transition contexts.

The logo should not be recoloured arbitrarily.

---

## 5.3 Brand colour

Blue remains the primary ALXPRGS interface colour.

Cyan may appear as a secondary visual accent in diagrams, glows and infrastructure visualisations.

Green from the existing identity must not become a competing primary UI colour.

Green remains primarily semantic:

success, healthy state, verified state, active state.

---

# 6. Themes

ALXPRGS supports three user preferences:

`Dark`

`Light`

`System`

Dark is the default visual reference and receives design priority.

Light remains a complete supported theme rather than an afterthought.

---

# 7. Colour system

Colours must be exposed through semantic design tokens.

Components must not depend directly on arbitrary palette values.

## Dark theme

| Token | Value | Purpose |
|---|---:|---|
| `canvas` | `#090A0C` | Main application background |
| `surface-1` | `#0F1115` | Primary surfaces |
| `surface-2` | `#14171D` | Raised/interactive surfaces |
| `surface-3` | `#1A1E26` | Strong elevation/selected surfaces |
| `surface-hover` | `#20252E` | Neutral hover |
| `border-subtle` | `#20242C` | Quiet separators |
| `border-default` | `#2A303A` | Controls and visible boundaries |
| `text-primary` | `#F5F7FA` | Main content |
| `text-secondary` | `#B6BEC9` | Secondary copy |
| `text-tertiary` | `#7E8896` | Metadata |
| `brand` | `#3B82F6` | Primary actions |
| `brand-hover` | `#5594F8` | Primary hover |
| `brand-active` | `#2563EB` | Pressed state |
| `accent-cyan` | `#22D3EE` | Decorative technical visualisation |
| `success` | `#22C55E` | Success |
| `warning` | `#F59E0B` | Warning |
| `danger` | `#EF4444` | Failure/destructive |
| `focus` | `#60A5FA` | Keyboard focus |

The primary canvas is almost black, not absolute `#000000`.

Pure black may only be used for isolated deepest layers or media treatment.

---

## Light theme

| Token | Value | Purpose |
|---|---:|---|
| `canvas` | `#F7F8FA` | Main application background |
| `surface-1` | `#FFFFFF` | Primary surfaces |
| `surface-2` | `#F1F3F5` | Secondary surfaces |
| `surface-3` | `#E9EDF2` | Raised/selected surfaces |
| `surface-hover` | `#E7EBF0` | Hover |
| `border-subtle` | `#E2E6EB` | Separators |
| `border-default` | `#CBD2DA` | Controls |
| `text-primary` | `#111318` | Main content |
| `text-secondary` | `#4B5563` | Secondary copy |
| `text-tertiary` | `#77808C` | Metadata |
| `brand` | `#2563EB` | Primary action |
| `brand-hover` | `#1D4ED8` | Primary hover |
| `brand-active` | `#1E40AF` | Pressed |
| `accent-cyan` | `#0891B2` | Decorative accent |
| `success` | `#16A34A` | Success |
| `warning` | `#D97706` | Warning |
| `danger` | `#DC2626` | Failure |
| `focus` | `#2563EB` | Focus |

---

# 8. Typography

## Primary typeface

**Geist Sans**

Self-hosted with the application.

Do not depend on Google Fonts or another third-party runtime font request.

---

## Technical typeface

**Geist Mono**

Use for:

client IDs, scopes, IP addresses, timestamps where technical alignment matters, audit values, recovery codes, TOTP secrets, hashes, build IDs and code fragments.

Do not use monospace merely to make the application look technical.

---

## Typography scale

| Role | Size | Weight | Line height |
|---|---:|---:|---:|
| Display | 36 px | 600 | 44 px |
| Page title | 28 px | 600 | 36 px |
| Section title | 20 px | 600 | 28 px |
| Card title | 16 px | 600 | 24 px |
| Body | 14 px | 400 | 21 px |
| Body large | 16 px | 400 | 24 px |
| Label | 13 px | 500 | 18 px |
| Metadata | 12 px | 400 | 17 px |
| Mono | 13 px | 400 | 19 px |

Auth hero headings may use 30–36 px depending on viewport.

Admin interfaces favour 14 px body text.

---

# 9. Spacing

Use a 4 px base grid.

Canonical spacing values:

`4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64`

Arbitrary spacing values should be rare.

Authentication prefers 24–32 px section separation.

Administration commonly uses 12–20 px.

---

# 10. Shape language

ALXPRGS uses moderately soft geometry.

It must not look either excessively corporate-square or toy-like.

| Token | Radius |
|---|---:|
| `radius-xs` | 6 px |
| `radius-sm` | 8 px |
| `radius-md` | 10 px |
| `radius-lg` | 14 px |
| `radius-xl` | 18 px |
| `radius-full` | 9999 px |

Default controls use approximately 10 px.

Normal cards use 12–14 px.

Large auth/dialog surfaces may use 14–18 px.

Pills are reserved for elements that genuinely behave like pills:

status, filters, tags and compact segmented controls.

---

# 11. Borders and elevation

Most hierarchy should not rely on heavy borders.

Use subtle 1 px borders.

Elevation should be created through a combination of:

surface colour, border contrast and restrained shadow.

Dark-mode shadows are intentionally subtle.

Avoid large glowing card shadows.

Strong glow is allowed only in decorative visualisations.

---

# 12. Iconography

Functional icons use **Lucide**.

Default stroke weight should remain visually close to Lucide's native appearance.

Common sizes:

16 px for compact actions.

18 px for normal controls.

20 px for navigation.

24 px for larger state indicators.

System glyph characters such as:

`✓`, `✕`, `⚠`, `+`

must not substitute for a proper icon when Lucide contains an appropriate symbol.

Emoji should not be used as functional UI iconography.

The ALXPRGS logo is brand artwork and is not part of the Lucide system.

---

# 13. Motion system

Motion is a first-class design primitive.

Recommended durations:

| Motion | Duration |
|---|---:|
| Micro interaction | 100–140 ms |
| Hover/state change | 140–180 ms |
| Normal entrance | 180–240 ms |
| Dialog/layout change | 220–320 ms |
| Large contextual transition | 280–360 ms |

Routine UI transitions should almost never exceed 400 ms.

---

## Motion character

ALXPRGS motion should feel:

responsive, smooth, slightly elastic where appropriate and technically precise.

Avoid exaggerated bouncing.

---

## Layout motion

When content height changes, the container should generally resize smoothly.

Example:

Password login → MFA challenge.

The authentication card should not suddenly jump between heights.

---

## Shared state motion

Use shared-element motion where spatial continuity makes interaction clearer.

Examples:

active navigation indicator, selected tab background, expanding account-security item.

---

## Success motion

Success should be visible without becoming celebratory marketing.

Examples:

copy icon morphs to check;

passkey success briefly shows a confirmation state;

saved settings receive a subtle status animation.

No confetti for routine account actions.

---

# 14. Reduced motion

`prefers-reduced-motion` is mandatory.

Reduced-motion mode should remove:

cursor-following visual movement, large translation, parallax, nonessential layout travel and repeated decorative motion.

Opacity changes and immediate state replacement may remain where necessary.

---

# 15. Motion performance

Continuous animation must not behave like a permanently running game renderer.

Interactive backgrounds must:

pause when `document.visibilityState !== "visible"`;

reduce complexity where device capability is limited;

avoid repeated synchronous layout measurement;

avoid expensive large-area blur animation;

avoid unnecessary React rerender loops;

disable or simplify themselves under reduced motion.

Visual quality is not permission to continuously consume significant CPU/GPU resources.

---

# 16. Surfaces

ALXPRGS uses three major application surface families.

## Authentication surface

Spacious, calm, visual.

## Account surface

Moderate information density.

## Administration surface

Dense and operational.

These are variations of one design language rather than independent themes.

---

# 17. Authentication layout

Desktop authentication uses an adaptive split layout.

At sufficiently large widths:

one section contains the authentication flow;

the other contains an interactive ALXPRGS technical visualisation.

At smaller widths, the decorative surface disappears or becomes extremely subtle.

The authentication form remains the primary content.

Recommended split breakpoint:

approximately `1024 px`.

---

# 18. Authentication visualisation

The non-form portion of desktop authentication combines three ideas:

abstract grid/mesh;

infrastructure topology;

interactive WorkOS-style technical composition.

The scene may contain:

an ALXPRGS SSO core node;

connected application nodes;

small authentication/session signals;

subtle animated paths;

status indicators;

abstract request packets;

minimal code/data fragments;

cursor-reactive lighting;

blue/cyan glow.

The scene must suggest that an actual infrastructure system is operating.

It must not resemble:

a marketing hero banner, cryptocurrency dashboard, hacker terminal, cyberpunk game UI or generic AI-generated gradient mesh.

No marketing slogans are required.

---

# 19. Authentication form

The form remains visually quiet.

Typical hierarchy:

ALXPRGS identity.

Context.

Heading.

Short explanation.

Primary authentication options.

Alternative method divider.

Credentials.

Primary action.

Secondary actions.

Legal/footer context where necessary.

---

# 20. Relying-party context

When authentication is initiated by a known OIDC relying party, the UI should clearly indicate where the user is continuing.

Example conceptual copy:

**Continue to School Warehouse**

Application icon.

Application name.

Verified/canonical domain where appropriate.

Do not turn this into an OAuth permission wall unless actual user consent is required by product behaviour.

RP context must come from trusted server-side client metadata.

Never trust arbitrary query parameters for branding or destination information.

---

# 21. Passkeys

Passkeys are a first-class authentication method.

Where available they should not appear as an obscure text link underneath passwords.

A typical hierarchy may use:

**Continue with passkey**

followed by an alternative password path.

Password authentication remains fully supported.

Passkey interaction must make it clear that a browser/platform security dialog will appear.

---

# 22. Authentication state transitions

Major flow changes should animate contextually:

Login → MFA.

Login → Password.

Register → Verification.

Verification → Success.

Reauthentication → Factor challenge.

The interface should retain a sense of spatial continuity.

It should never blink through disconnected screens without explanation.

---

# 23. Human-facing security language

Normal users see:

**Passkey / Ключ доступа**

rather than WebAuthn.

**Two-factor authentication**

rather than factor-policy implementation terminology.

**Recovery codes**

rather than implementation identifiers.

**Security key or device**

rather than FIDO protocol details.

Technical protocol language remains available in admin/developer contexts when useful.

---

# 24. Forms

Every input must have a programmatic label.

Placeholder text does not replace labels.

Default control height:

**44 px**

Auth controls may use 44–46 px.

Admin compact controls may use 36–40 px where appropriate.

Every form supports consistent:

default;

hover;

focus-visible;

filled;

disabled;

loading;

invalid;

success where meaningful.

---

# 25. Password controls

Password inputs provide a visible show/hide action.

Password requirement information should appear contextually.

Do not permanently show implementation information such as password hashing algorithms.

---

# 26. OTP

OTP interfaces should use a dedicated visual pattern rather than treating verification as a generic text box where practical.

The actual accessible implementation may remain one logical input while rendering segmented positions.

Support:

paste;

mobile one-time-code autocomplete where possible;

keyboard entry;

clear invalid feedback.

---

# 27. Validation

Validation errors belong as close as possible to the affected field.

Serious server/page errors additionally use section alerts.

Do not rely on one generic red banner for all possible validation.

Invalid fields receive:

semantic error association;

visible message;

appropriate `aria-invalid`;

appropriate `aria-describedby`.

---

# 28. Feedback hierarchy

Three feedback levels exist.

## Field feedback

Specific to one value.

## Section/page alert

For errors requiring user attention or affecting the entire current operation.

## Toast

For short-lived confirmation such as:

copied;

session revoked;

settings saved;

application created.

Toasts must not contain information the user needs to preserve or act upon later.

---

# 29. Buttons

Canonical variants:

**Primary**

Main action.

Blue filled.

**Secondary**

Neutral elevated/bordered action.

**Ghost**

Low-emphasis control.

**Danger**

Destructive action.

Red emphasis.

**Link**

Navigation embedded in text.

Buttons must never silently change role based only on colour.

---

# 30. Loading

No single loading technique applies everywhere.

Buttons use an inline loading indicator while retaining stable width where practical.

Tables use skeleton rows or structured placeholders.

Large initial areas may use skeletons.

Short local fetches may use subtle progress states.

Avoid blank screens with a centred spinner unless there is genuinely nothing useful to render.

---

# 31. Empty states

Empty states explain:

what is empty;

why that may be expected;

what the user can do next.

Example:

`No passkeys yet`

followed by a short explanation and `Add passkey`.

An empty `<tbody>` is not an acceptable final empty state.

---

# 32. Dialogs

Dialogs use accessible headless primitives.

Required behaviour:

focus trapping;

focus restoration;

Escape where cancellation is allowed;

accessible title and description;

background inertness;

correct nested-dialog handling;

scroll behaviour on short screens.

No new dialog implementation should manually recreate these mechanisms without exceptional reason.

---

# 33. Destructive actions

Browser `alert()` and `confirm()` are not part of ALXPRGS Design Language.

Destructive actions use product dialogs.

Examples:

Delete passkey.

Revoke application secret.

Block user.

Delete client.

Revoke sessions.

Extremely destructive actions may require typing an identifier.

Reauthentication remains a separate security control and must not be confused with confirmation UX.

---

# 34. Reauthentication

Reauthentication dialogs should identify what the user is confirming where safe and appropriate.

Avoid generic copy such as only:

`Confirm operation`.

Prefer:

`Confirm changing the registration policy`

or:

`Confirm deleting passkey "MacBook"`

when that information can safely be displayed.

Do not expose sensitive operation proof material.

---

# 35. Account interface

Account UI should favour sections over excessive cards.

Suggested information architecture:

Profile.

Security.

Passkeys.

Two-factor authentication.

Recovery codes.

Sessions.

Privacy.

Account deletion.

Security actions should visually communicate their relative importance.

---

# 36. Administration shell

Administration uses a left sidebar on desktop.

Suggested primary navigation:

**Overview**

**Users**

**Applications**

**Sessions**

**Audit**

**System**

Sidebar is visually quieter than main content.

Navigation chrome must not compete with operational data.

---

# 37. Sidebar

Normal width approximately:

`232–248 px`

Collapsed mode may use approximately:

`64–72 px`

Desktop may remember collapse preference.

Mobile uses a drawer/sheet rather than permanently consuming horizontal space.

---

# 38. Administration Overview

Overview provides operational situational awareness rather than decorative analytics.

Useful information may include:

SSO health;

registration mode;

user count;

active sessions;

registered applications;

recent security events;

verification/MFA configuration;

recent administrative actions;

system/build identity.

Charts should only exist when a trend is genuinely useful.

Do not add fake analytics merely to make a dashboard appear sophisticated.

---

# 39. Data tables

Tables are operational controls.

They support where meaningful:

search;

sorting;

filters;

pagination;

sticky headers;

column visibility;

row actions;

keyboard access;

loading state;

empty state;

error state.

Row actions usually live behind an ellipsis menu where they are secondary.

Important common actions may remain directly visible.

---

# 40. Table density

Desktop admin rows should generally fall around:

40–48 px.

Information density is intentional.

Large card-like 70–90 px rows should not become the default.

---

# 41. Responsive tables

Do not force every desktop column onto mobile.

Depending on data, mobile may use:

horizontal scroll;

reduced column set;

expandable details;

compact record cards.

The choice depends on the semantics of each table.

---

# 42. Command palette

`Ctrl+K` / `Cmd+K` opens the global command palette.

It may provide:

navigation;

user lookup;

application lookup;

audit lookup;

theme control;

safe direct actions;

creation actions;

account actions.

Examples:

`Go to Users`

`Find user`

`Create application`

`Open recent security events`

`Change theme`

`Sign out`

Destructive actions may be discovered from the palette, but must still open the proper confirmation UI.

---

# 43. Command palette interaction

Command palette should feel extremely fast.

Opening transition is brief.

Search responds immediately.

Results support keyboard navigation.

Recent/common commands may appear before input.

Navigation/action categories may be visually separated.

---

# 44. Cards

Cards are not universal containers.

Use cards when information is genuinely a discrete object or group.

Examples:

Passkey.

Session.

Security factor.

Overview metric group.

Do not wrap:

page → card → section → card → field group → card.

---

# 45. Navigation

Navigation uses real routing.

Application state should be representable in URLs where that improves usability.

Administration sections must have dedicated routes.

Expected examples:

`/account`

`/account/security`

`/admin`

`/admin/users`

`/admin/applications`

`/admin/sessions`

`/admin/audit`

`/admin/system`

Exact routing may differ to preserve server integration, but browser history must behave correctly.

Back/Forward must not desynchronise visible UI and URL.

---

# 46. Page transitions

Route transitions are subtle.

Do not animate the entire application off-screen for every navigation.

Preferred techniques:

small opacity;

short translate;

shared active-navigation indicator;

content skeleton where fetching is necessary.

---

# 47. Technical values

Technical identifiers should use dedicated treatments.

Examples:

client ID;

scope;

IP;

session ID;

build ID.

Use mono font with a neutral surface and copy action.

Long technical values must wrap, truncate with accessible expansion, or provide a dedicated viewer.

They must not destroy responsive layout.

---

# 48. Copy actions

Copying should have immediate feedback.

Icon state:

Copy → Check.

Text may temporarily become:

`Copied`

No browser alert.

---

# 49. Status

Statuses use both colour and language/iconography.

Never encode a meaningful status using colour alone.

Examples:

green dot + `Healthy`;

yellow indicator + `Pending`;

red indicator + `Blocked`.

---

# 50. Glass and blur

Glassmorphism is not a general surface style.

Blur may appear selectively in:

command palette backdrop;

modal backdrop;

floating navigation layer;

selected decorative authentication effects.

Normal cards should not all be translucent glass.

---

# 51. Visual effects

Decorative glows may use blue and cyan.

Effects should be soft and spatial.

Avoid:

large rainbow gradients;

permanent neon outlines;

multiple saturated colours competing for attention.

The user should remember the interface rather than the gradient.

---

# 52. Light theme

Light theme preserves the same hierarchy and interaction.

It is not simply an inverted dark palette.

Glows and blur are reduced because they can look excessive against light backgrounds.

Light surfaces rely slightly more on border/elevation contrast.

---

# 53. Theme switching

Theme changes should feel polished.

The primary theme selector belongs in the shared page footer on public, account and administrative pages. Do not reserve a separate top appearance bar for it.

Group the selector with the contact information, aligned to the right on wide screens. Below 640 px, place this group on a separate row after the legal links. Keep the footer in normal document flow, visible at the bottom of short pages and after long content, without overlapping cookie notices.

Keep a visible label and support System, Light and Dark choices with keyboard access and a clear focus indicator. The command palette may provide an additional way to change the theme.

A brief global colour transition may be applied when the change was directly initiated by the user.

Do not animate initial page theme hydration.

Avoid theme flash on startup.

---

# 54. Responsive system

Primary layout thresholds may align approximately with:

`640`

`768`

`1024`

`1280`

but components should be responsive to their actual content rather than blindly assuming desktop behaviour.

---

# 55. Mobile authentication

On mobile:

visualisation is removed or greatly simplified;

branding becomes compact;

form consumes the primary viewport;

critical actions remain reachable above or with predictable scrolling;

the keyboard must not trap important controls below inaccessible content.

---

# 56. Short-height displays

Dialogs and auth surfaces must be tested on short-height screens.

Every important dialog requires:

viewport-aware max height;

internal scrolling when necessary;

visible action area.

No dialog may render its confirmation buttons below an unreachable viewport boundary.

---

# 57. Accessibility target

Target **WCAG 2.2 AA** for core application UI.

Requirements include:

visible focus;

keyboard operation;

semantic labels;

correct landmarks;

unique page titles;

accessible validation;

appropriate live announcements;

sufficient contrast;

reduced-motion support;

non-colour status indication.

---

# 58. Focus appearance

Keyboard focus must be immediately visible.

Recommended treatment:

2 px brand/focus outline or ring;

small offset where background distinction requires it.

Focus styling must be consistent across primitives.

---

# 59. Page semantics

Each major page should have one meaningful H1.

Avoid nested main landmarks.

Route changes should update:

document title;

meaningful focus target where appropriate.

---

# 60. Performance philosophy

A premium interface must still feel fast.

Design sophistication is not permission for poor runtime behaviour.

Avoid:

unnecessary dependency weight;

constant full-page rerenders;

huge unoptimised raster assets;

large blur surfaces moving every frame;

layout thrashing;

animations on expensive layout properties when transforms suffice.

---

# 61. Asset loading

Logo and common UI assets should use appropriate caching.

Large decorative assets must be optimised.

Prefer vector assets where suitable.

Authentication must remain usable if decorative visualisation fails to load.

---

# 62. Frontend technical foundation

ALXPRGS Design Language v1 expects the implementation layer to use:

**React**

Existing application foundation.

**Tailwind CSS**

Actual utility generation and semantic theme integration.

**Radix Primitives or equivalent accessible headless primitives**

For interaction-heavy controls.

**Source-owned shadcn-style components**

As architectural inspiration/foundation, not visual identity.

**Motion for React**

For coordinated animation.

**Lucide**

Functional icons.

**Geist / Geist Mono**

Self-hosted typography.

**A real React routing solution**

Rather than manual `pushState`/pathname state synchronisation.

Exact dependency versions must be selected from stable, compatible releases when implementation begins.

---

# 63. Component architecture

Reusable primitives should exist as actual components rather than repeated markup.

Core primitives should include at minimum:

Button, IconButton, Input, PasswordInput, OTPInput, Checkbox, Radio, Select, Textarea, Label, Field, Alert, Toast, Badge, Card, Dialog, DropdownMenu, Tooltip, Tabs, Popover, CommandPalette, Skeleton, Spinner/Progress, Table foundations and CopyButton.

Application-specific components are built on these primitives.

---

# 64. Design tokens

Theme values must be defined centrally.

Token categories include:

colour;

typography;

spacing;

radius;

shadow/elevation;

motion duration;

motion easing;

z-index;

control height;

layout widths.

Components consume semantic tokens.

Do not duplicate literal design values throughout TSX.

---

# 65. Tailwind usage

Tailwind utilities are implementation tools, not the design system itself.

Repeated semantic patterns must become components or variants.

Do not replace the current problem:

undefined handmade utility classes

with a new problem:

five hundred unique unreadable class strings copied between screens.

Use component variants and token conventions.

---

# 66. Variant management

Reusable components should expose clear variants.

Example Button:

`variant="primary"`

`variant="secondary"`

`variant="ghost"`

`variant="danger"`

`size="sm|md|lg"`

Avoid booleans such as:

`blue`

`rounded`

`big`

`isDangerRed`

that encode presentation inconsistently.

---

# 67. Error architecture

The frontend should distinguish:

validation error;

authentication error;

authorization error;

rate limit;

expired challenge;

network failure;

service unavailable;

unexpected failure.

Not every HTTP error requires a unique page, but errors must be translated into meaningful consistent UX.

---

# 68. Security-state architecture

Auth flows must remain explicit state machines conceptually even if implementation uses route/state composition.

States such as:

password authentication;

MFA challenge;

forced password change;

legal acceptance;

deletion pending;

reauthentication;

email verification

must not be reduced to arbitrary conditional JSX scattered throughout unrelated components.

---

# 69. Progressive disclosure

Normal users see simple descriptions.

Technical detail may be exposed through expandable sections when useful.

Admin users can see substantially more implementation metadata.

The system should not hide operationally important information from administrators merely for aesthetic minimalism.

---

# 70. Content tone

Copy is concise and confident.

Avoid overly corporate language.

Avoid exaggerated marketing wording.

Avoid unnecessary protocol jargon.

Good:

`Use your passkey to continue.`

Bad:

`Leverage next-generation passwordless FIDO2/WebAuthn authentication technology.`

Good:

`This session is active on this device.`

Bad:

`JWT session currently valid according to server-side session revision metadata.`

---

# 71. Do

Use dark neutral surfaces.

Use blue as primary brand/control colour.

Use cyan sparingly for technical visuals.

Use motion to show state continuity.

Use whitespace in authentication.

Use density in administration.

Use real components.

Use keyboard workflows.

Use human language.

Use explicit success/error feedback.

Use technical detail where it helps operators.

---

# 72. Do not

Do not make every panel a card.

Do not use arbitrary gradients everywhere.

Do not make all controls pills.

Do not put glass blur on every surface.

Do not expose protocol jargon to normal users.

Do not use browser alerts.

Do not use emoji as product icons.

Do not duplicate component markup across every page.

Do not let animation delay ordinary interaction.

Do not allow visual redesign to weaken security behaviour.

Do not turn ALXPRGS into a generic shadcn demo.

---

# 73. Desired authentication feeling

The user should feel:

the system is secure;

the system is technically sophisticated;

the system is understandable;

the system responds immediately;

the product belongs to a larger coherent infrastructure.

The user should not feel:

they are filling out a government form;

they are reading protocol documentation;

they are inside a generic template;

their computer is rendering a game while attempting to log in.

---

# 74. Desired administration feeling

The administrator should feel:

information is easy to scan;

actions are easy to discover;

keyboard interaction is fast;

critical operations are clearly differentiated;

technical data is available without visual clutter;

the interface behaves like a professional developer tool.

---

# 75. ALXPRGS signature characteristics

A successful ALXPRGS interface should be recognisable through the combination of:

near-black dark canvas;

ALXPRGS blue identity;

blue/cyan infrastructure visual effects;

Geist typography;

moderately soft geometry;

quiet surfaces;

strong information hierarchy;

smooth spatial motion;

dense but restrained admin tooling;

prominent modern authentication methods;

real ALXPRGS branding.

No individual characteristic is sufficient alone.

The identity is the combination.

---

# 76. Definition of done for Design Language v1 implementation

An implementation conforms to ALXPRGS Design Language v1 when:

the same token system drives dark and light themes;

primary UI primitives are shared components;

authentication uses the new responsive language;

passkeys are first-class;

administration uses the new operational shell;

browser alert/confirm interactions are eliminated from normal product UX;

routing and browser history behave correctly;

loading/error/empty states are deliberately designed;

motion is consistently implemented;

reduced-motion works;

mobile and short-height interfaces are usable;

keyboard navigation works;

core accessibility expectations are met;

the official ALXPRGS logo is used consistently;

technical/security contracts remain intact;

the previous handmade pseudo-utility styling layer is no longer necessary.

---

# 77. Final visual target

ALXPRGS should not look like a personal pet project attempting to imitate an enterprise product.

It should look like a small, intentionally engineered infrastructure platform that happens to be used primarily for personal projects, experiments and hackathons.

The scale of the audience does not determine the quality of the interface.

The interface should feel complete even if only one person ever uses it.
