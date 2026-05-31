# UX Improvements - Message Actions Position Update

## Changes Made

### 1. Moved Action Buttons Position
**File**: `frontend/src/views/ChatView.vue`

**Before**: Action buttons were positioned ABOVE message bubbles
**After**: Action buttons are now positioned BELOW message bubbles (following PageIndex design)

**Changes**:
- User messages: MessageActions component moved from before message bubble to after
- Assistant messages: MessageActions component moved from before AI response container to after

### 2. Fixed Hover Area
**File**: `frontend/src/views/ChatView.vue`

**Before**: Hover area used absolute positioning with `top: -45px`, only triggering when hovering the small action button area
**After**: Hover area now uses relative positioning with proper margins, triggering when hovering anywhere on the entire message (including thinking, tools, and content)

**CSS Updates**:
```css
/* Before */
.message-actions-container {
  position: absolute;
  top: -45px;
  /* ... */
}

/* After */
.message-actions-container {
  position: relative;
  margin-top: 4px;
  margin-bottom: 4px;
  /* ... */
}
```

### 3. Alignment Improvements
- User message actions: Aligned to the right (flex-end)
- Assistant message actions: Aligned to the left (flex-start)

## Verification
- ✅ Build passes without TypeScript errors
- ✅ All message operations (copy, retry, rollback) still functional
- ✅ Hover states work across entire message area
- ✅ Action buttons appear below messages as per design spec

## Files Modified
- `frontend/src/views/ChatView.vue`

## No Breaking Changes
All existing functionality remains intact:
- Copy button works for all messages
- Retry button works for AI messages
- Rollback button works for user messages
- Keyboard shortcuts (Ctrl+N, Ctrl+Enter) still functional
- Citation click handler still works
