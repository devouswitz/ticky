# Ticky Apple-style setup window design QA

## Source of visual truth

- Selected structure reference: `/Users/spencermccauley/ticky/design/team-composer-reference.png`
- Apple platform guidance:
  - https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/
  - https://developer.apple.com/design/human-interface-guidelines/settings
  - https://developer.apple.com/design/human-interface-guidelines/windows
  - https://developer.apple.com/design/human-interface-guidelines/sidebars
  - https://developer.apple.com/design/human-interface-guidelines/materials
  - https://developer.apple.com/design/human-interface-guidelines/color
  - https://developer.apple.com/design/human-interface-guidelines/buttons
  - https://developer.apple.com/videos/play/wwdc2025/310/

The selected two-pane team-composer structure remains the visual source of truth. Apple guidance informed the native macOS treatment: a standard auxiliary window, sidebar material, dynamic system colors, SF Symbols, native controls, and restrained use of translucent material.

## Verification environment

- Platform: macOS AppKit
- Viewport: 920 x 720 points
- Appearance: dark mode
- States checked: active window, inactive window, startup pane, advanced pane
- Interaction checks: agent selection, checkbox changes, Add Agent, Advanced, back navigation, repeated table selection, install flow wiring

## Evidence

- Active startup: `/Users/spencermccauley/ticky/design/ticky-apple-live-trimmed.png`
- Inactive startup: `/Users/spencermccauley/ticky/design/ticky-apple-live-inactive-trimmed.png`
- Advanced settings: `/Users/spencermccauley/ticky/design/ticky-apple-advanced-final-trimmed.png`
- Neutral agent state: `/Users/spencermccauley/ticky/design/ticky-agent-selection-neutral.jpeg`
- Terra selected state: `/Users/spencermccauley/ticky/design/ticky-agent-selection-terra.jpeg`
- Luna selected state: `/Users/spencermccauley/ticky/design/ticky-agent-selection-luna.jpeg`
- Full reference comparison: `/Users/spencermccauley/ticky/design/ticky-apple-reference-comparison.png`
- Focused team comparison: `/Users/spencermccauley/ticky/design/ticky-apple-team-focus-comparison.png`
- Before and after comparison: `/Users/spencermccauley/ticky/design/ticky-apple-before-after.png`
- Updated reference and selected-state comparison: `/Users/spencermccauley/ticky/design/ticky-agent-selection-reference-comparison.png`
- Neutral, Terra, and Luna state comparison: `/Users/spencermccauley/ticky/design/ticky-agent-selection-state-comparison.png`

## Fidelity review

### Structure and hierarchy

- The reference composition is preserved: connections in the left pane, team configuration in the right pane, a selected-agent editor, Add Agent, Advanced, and Install Team.
- The startup pane begins with no agent selected or expanded. Selecting an agent moves the tint and reveals the Role and Access controls for that agent only.
- The startup pane has one clear title, one supporting line, and one default action.
- No startup content is clipped at 920 x 720.
- The Advanced pane uses the same structural language as startup and remains navigable without opening another window.

### Typography

- All interface text uses AppKit system typography, which resolves to the macOS system font.
- Titles, section labels, helper copy, and control labels use distinct native size and weight levels.
- Copy is concise and uses familiar macOS title and sentence casing.

### Spacing and shape

- Sidebar width is 286 points.
- Primary content uses a 32-point outer inset.
- Grouped settings surfaces use consistent 12-point corners and internal spacing.
- Fields, checkboxes, symbols, and actions align to stable rows across both panes.

### Color and materials

- The sidebar uses `NSVisualEffectView` with sidebar material and follows window activity.
- Content, labels, separators, selection fills, and controls use dynamic system colors.
- The accent color is reserved for the active default action and selected native controls.
- Inactive-window verification confirms the sidebar, checkboxes, and primary action adapt automatically.

### Assets and controls

- Interface icons are standard SF Symbols.
- There are no handcrafted SVGs, text-symbol substitutes, emoji, fake controls, or raster product assets.
- Text fields, secure fields, checkboxes, buttons, tables, and menus are native AppKit controls.
- Buttons that open another pane use an ellipsis where appropriate.

### Accessibility and interaction

- Startup and Advanced controls are represented in the macOS accessibility tree with usable labels.
- Keyboard-native controls retain standard focus and activation behavior.
- Repeated agent table selection was tested after fixing the form-commit recursion crash.
- Back navigation, selection changes, toggles, and the primary install action remain functional.
- Whole-row clicks were verified for selection, while each include checkbox remains an independent control.

## Comparison history and fixes

1. P2: The previous build looked like a flat custom utility instead of macOS software.
   - Fixed with a real sidebar material, standard window chrome, dynamic system colors, SF Symbols, and native grouped surfaces.
2. P2: The Advanced pane retained a dense legacy form inconsistent with the new startup pane.
   - Fixed with a source-list sidebar, stable grouped settings, and a clearer two-column agent form.
3. P2: Connection status text could clip and credential placeholders were implementation-focused.
   - Fixed with concise `Connected` status labels, detailed tooltips, and friendly service-specific placeholders.
4. P3: Sidebar material brightness varies with wallpaper, system contrast settings, and window activity.
   - Accepted as intentional platform behavior. Active and inactive states remain legible.
5. P1: The selected treatment and inline editor appeared to be permanently attached to Terra instead of representing a real interaction state.
   - Fixed by starting with no overview selection, preserving `-1` as a valid neutral state, and making the non-control area of every agent row selectable.
   - Post-fix evidence shows the neutral state, Terra selected state, and Luna selected state at the same 920 x 720 viewport. Sol, Terra, and Luna were each selected in native UI verification. The include checkbox was toggled independently without moving or clearing the selection.

## Remaining issues

- No remaining P0, P1, or P2 visual issues were found in the checked states.
- No blocking accessibility or core-interaction issues were found.

final result: passed

## 2026-07-10 refresh (post-QA changes)

This pass supersedes parts of the record above:

- Source moved to `widget/macos/TickyWidget.swift`; the widget is now the
  explicitly macOS-only layer of an otherwise platform-neutral core.
- Roster renamed: Sol/Terra/Luna became Rook/Wren/Finch.
- New palette: brass brand color plus per-agent jewel tones (Rook indigo,
  Wren terracotta, Finch olive), each with light and dark variants, applied to
  icon tiles, selection fills, the brand mark, sidebar dots, and primary buttons.
- Selector bug fixes: row selection moved from NSClickGestureRecognizer (which
  hit-tested in the wrong coordinate space and raced the include checkbox) to a
  dedicated row view whose hitTest yields to real controls; shared editor-field
  constraints are created once instead of accumulating per click; focus follows
  the selected row into the Role field; rows are AX buttons (VoiceOver can
  select agents) and accept first mouse.
- Advanced pane: agents table no longer collapses (deterministic sidebar
  layout), routing NSTextView wraps and scrolls correctly, tool-name preview
  updates live while typing, closing the window commits and saves a valid
  roster instead of silently discarding edits.
- Menu bar: template SF Symbol instead of the ❖ text glyph, brass count while
  running, colored ✓/✗ marks in the call list.
- Interaction states re-verified on the live build via accessibility-driven
  clicks with window-level captures: neutral, Wren selected, Rook selected,
  include-checkbox independence, Advanced form for Rook and Finch, and
  Advanced-to-Team round trip.
