/**
 * React 19 + @react-three/fiber v8 compat.
 *
 * R3F v8 augments `JSX.IntrinsicElements` (TS 4.x style). React 19 moves JSX
 * into `React.JSX`, so the augmentation no longer reaches our tsx files.
 * 这里显式地把 R3F 的 ThreeElements 桥接进 React.JSX.IntrinsicElements.
 */
import type { ThreeElements } from '@react-three/fiber'

declare global {
  namespace React {
    namespace JSX {
      interface IntrinsicElements extends ThreeElements {}
    }
  }
}

export {}
