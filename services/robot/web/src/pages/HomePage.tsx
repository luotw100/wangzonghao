import { Link } from 'react-router-dom';
import { LaborsterLogo } from '../components/Icons';

export function HomePage() {
  return (
    <div className="w-full h-dvh flex flex-col items-center justify-center bg-bg-primary tech-grid">
      <div className="flex flex-col items-center gap-8">
        <div className="w-20 h-20 rounded-full bg-bg-tertiary flex items-center justify-center laborster-empty-logo">
          <LaborsterLogo size={40} id="homeGrad" />
        </div>
        <h1 className="font-brand text-2xl tracking-wider text-accent">Laborster</h1>
        <p className="text-text-secondary text-sm">Robot 控制台</p>

        <Link
          to="/robot"
          className="group flex flex-col items-center gap-3 px-10 py-6 rounded-2xl border border-border-glow/30 bg-bg-secondary/60 hover:bg-bg-tertiary hover:border-accent/30 transition-all btn-neon mt-4"
        >
          <svg className="w-8 h-8 text-accent group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
          </svg>
          <span className="text-sm font-medium text-text-primary">进入控制台</span>
        </Link>
      </div>
    </div>
  );
}
