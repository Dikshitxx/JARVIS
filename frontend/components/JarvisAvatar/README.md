# JarvisAvatar

## Purpose

3D avatar display and local animation state.

## Files

- `AvatarHead.tsx` - Loads the public GLB and animates facial morph targets.
- `HudRings.tsx` - Animated status rings around the avatar.
- `JarvisAvatar.tsx` - Three.js canvas and component composition.
- `useAvatarState.ts` - React state hook for idle/listening/thinking/speaking UI states.
- `useFakeSpeech.ts` - UI-only mouth animation helper; it does not generate or verify speech.

## Execution and connections

Rendered by frontend/app/page.tsx using React Three Fiber.

JarvisAvatar combines model and HUD; hooks provide UI-only state and speech animation.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
