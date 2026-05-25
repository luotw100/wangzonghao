import { avatarColor, avatarInitials } from '../utils/color';

interface AvatarProps {
  name: string;
  seed?: string;
  size?: number;
  className?: string;
}

export default function Avatar({ name, seed, size = 40, className }: AvatarProps) {
  const bg = avatarColor(seed || name);
  return (
    <span
      className={className ? `avatar ${className}` : 'avatar'}
      style={{ width: size, height: size, background: bg, fontSize: Math.round(size * 0.4) }}
      aria-hidden="true"
    >
      {avatarInitials(name)}
    </span>
  );
}
