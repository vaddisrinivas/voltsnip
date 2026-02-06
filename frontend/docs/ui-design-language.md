# VoltSnip UI Design Language

## Intent
A theme-first UI where every component is driven by a small set of design tokens.
No hardcoded colors in components. All surfaces, borders, shadows, and text colors
must resolve from tokens.

## Core Principles
- Theme-first: change theme tokens, the entire UI updates.
- Minimal surfaces: one elevation scale, no stacked shadows.
- Calm typography: display font for headings, mono for code, restrained weights.
- Focused interactions: hover = shadow, focus = glow, never both.
- Semantic layout: structure first, then decoration.

## Token System
Define tokens once in `css/themes.css`.

Required tokens:
- --bg
- --surface
- --surface-elevated
- --border
- --text
- --text-muted
- --accent
- --accent-2
- --accent-contrast
- --glow
- --shadow-1
- --shadow-2
- --code-bg
- --code-text
- --code-muted
- --code-accent

Rules:
- Components must only use tokens.
- No inline colors in markup.

## Component Templates

### Navbar
Purpose: brand + navigation + theme toggle.
- Background: --surface
- Border: --border
- Sticky, minimal height

### Search Bar
Purpose: primary input action.
- Surface: --surface
- Focus ring: --glow
- No heavy gradients

### Segmented Tabs
Purpose: feed switching.
- Active: --accent / --accent-contrast
- Inactive: --surface / --text-muted

### Card (Snippet)
Purpose: preview snippets.
- Surface: --surface
- Border: --border
- Hover: --shadow-2
- Title, description, tags, footer stats

### Badge / Tag
Purpose: metadata and language.
- Background: transparent + border
- Text: --text-muted

### Modal
Purpose: focused detail view.
- Surface: --surface-elevated
- Sticky header

### Code Block
Purpose: code readability.
- Background: --code-bg
- Text: --code-text
- Tokens: --code-muted / --code-accent

### Toast
Purpose: feedback.
- Surface: --surface-elevated
- Subtle animation

### Stats Row
Purpose: credibility, low noise.
- Small typography
- Muted colors

## Behavior Rules
- Hover effects must be consistent.
- No animated emoji.
- Avoid stacked gradients or glow + shadow simultaneously.

## File Split

index.html
- Structure only. No inline styles or scripts.

css/base.css
- Resets, typography, layout primitives.

css/themes.css
- Theme tokens (ember/noir).

css/components.css
- Reusable component styles.

js/state.js
- State, constants, metadata.

js/api.js
- Networking, caching.

js/ui.js
- Rendering and view helpers.

js/events.js
- Event handlers and flows.

js/app.js
- Bootstraps DOMContentLoaded and exposes public actions.
