// Deterministic hue from a string. Used to colour avatars by display name / id.
// Saturation + lightness are fixed so all avatars share the same chroma.

const HUES = [4, 22, 38, 54, 96, 168, 196, 220, 252, 282, 322, 348];

function hashCode(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash * 31 + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function avatarColor(seed: string): string {
  const hue = HUES[hashCode(seed) % HUES.length];
  return `hsl(${hue} 36% 58%)`;
}

export function avatarInitials(name: string): string {
  if (!name) return '·';
  const trimmed = name.trim();
  if (!trimmed) return '·';
  // For Chinese names, use the last character (most distinctive given Chinese
  // surnames cluster heavily). For Latin names, use the first letter.
  const isCjk = /[\u4e00-\u9fa5]/.test(trimmed);
  if (isCjk) {
    const chars = Array.from(trimmed);
    return chars[chars.length - 1];
  }
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0][0]!.toUpperCase();
  return (parts[0][0]! + parts[parts.length - 1][0]!).toUpperCase();
}
