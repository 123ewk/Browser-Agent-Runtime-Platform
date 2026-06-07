---
name: AgenticFlow
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#464555'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#684000'
  on-tertiary: '#ffffff'
  tertiary-container: '#885500'
  on-tertiary-container: '#ffd4a4'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '600'
    lineHeight: 38px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 24px
  gutter: 16px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 24px
---

## Brand & Style
The design system is engineered for a high-productivity AI orchestration environment. It balances the complexity of data-dense developer tools with the refined aesthetic of modern enterprise SaaS. The personality is **Professional, Systematic, and Efficient**, prioritizing clarity over decoration to reduce cognitive load during complex task management.

The design style is **Corporate Modern with a Utility-First focus**. It leverages a "Clean-Room" aesthetic—utilizing ample negative space within components to ensure readability despite high information density. Surfaces are defined by crisp borders and subtle tonal shifts rather than heavy shadows, ensuring the interface feels lightweight and responsive.

## Colors
This design system utilizes a structured palette designed for rapid status recognition:
- **Primary (Indigo):** Reserved for primary actions, active states, and focus indicators.
- **Success (Green):** Indicates "Healthy" agent status and completed processes.
- **Warning (Amber):** Signals "Degraded" performance or pending configurations.
- **Danger (Red):** Flags "Down" agents, critical errors, or destructive actions.
- **Neutral/Background:** A sophisticated range of cool grays. The background (#F9FAFB) provides a soft canvas that reduces eye strain, while borders (#E5E7EB) provide the necessary structural definition for data grids and sidebars.

## Typography
**Inter** is the workhorse of the design system, chosen for its exceptional legibility in UI environments. For technical metadata and agent identifiers, **JetBrains Mono** is introduced to provide a distinct "developer-tool" feel, making code snippets and ID strings easily distinguishable from UI labels.

Hierarchy is established through weight and color rather than drastic size changes. Use `body-md` for the majority of interface text to maintain high data density. Headlines use tighter letter-spacing to appear more cohesive at larger scales.

## Layout & Spacing
The layout follows a **Fixed-Fluid hybrid model**. Sidebars and navigation panels occupy fixed widths (240px to 280px), while the central workspace is fluid to allow for expansive data tables and workflow canvases.

- **Grid:** A 12-column grid is used for dashboard layouts, with 16px gutters.
- **Density:** High density is preferred. Use 8px (`stack-sm`) for internal component spacing and 16px (`stack-md`) for spacing between related component groups.
- **Mobile:** On mobile screens (<640px), sidebars collapse into a hamburger menu or bottom bar, and container padding reduces to 16px. Content stacks vertically.

## Elevation & Depth
Depth is conveyed through **Tonal Layering** and **Low-Contrast Outlines**.
- **Level 0 (Background):** #F9FAFB. Used for the main application canvas.
- **Level 1 (Cards/Panels):** Pure White (#FFFFFF) with a 1px border of #E5E7EB. This is the primary surface for content.
- **Level 2 (Popovers/Modals):** Pure White with a subtle ambient shadow (0px 4px 6px -1px rgba(0,0,0,0.1)).
- **Level 3 (Tooltips):** Dark Gray (#1F2937) with high contrast for immediate visibility.

Shadows are rarely used for static elements; they are reserved for temporary overlays to pull them forward in the Z-space.

## Shapes
The shape language is **Rounded**, using an 8px base radius for most components. This softens the technical nature of the platform, making it feel more modern and accessible.
- **Small Components (Buttons, Inputs):** 8px (rounded-md).
- **Large Components (Cards, Modals):** 12px (rounded-lg).
- **Status Pills:** Fully circular (capsule) for quick visual scanning.

## Components
- **Buttons:** Primary buttons use solid Indigo (#4F46E5) with white text. Secondary buttons use a white background with a gray border (#E5E7EB) and text.
- **Status Indicators:** Represented as small filled circles (8px) paired with JetBrains Mono labels. (e.g., ● Healthy in #10B981).
- **Inputs:** Use #FFFFFF background with a 1px #E5E7EB border. On focus, the border changes to Indigo (#4F46E5) with a subtle 2px outer glow.
- **Cards:** White surfaces with a light border. Header sections within cards should have a subtle #F9FAFB background to separate actions from content.
- **Data Tables:** Use a "zebra-stripe" pattern on hover to assist eye-tracking. Cell padding should be tight (12px vertical) to maximize visible rows.
- **Agent Node Cards:** Distinctive workflow components with 12px rounded corners, featuring a left-side accent bar colored by status (Healthy/Degraded/Down).
