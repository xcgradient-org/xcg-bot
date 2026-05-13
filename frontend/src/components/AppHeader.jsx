import { useMemo } from "react";
import { ROUTES } from "../lib/routes.js";

export default function AppHeader({ subtitle }) {
  const path = useMemo(() => window.location.pathname, []);
  return (
    <header className="bar">
      <div className="bar-inner">
        <a className="wordmark" href="/">
          <span className="dot" />
          <span>XC&nbsp;Gradient</span>
          {subtitle && (
            <>
              <span className="sep">/</span>
              <span className="sub">{subtitle}</span>
            </>
          )}
        </a>
        <nav className="internal-home-nav" aria-label="Navigation">
          <a href="/" aria-label="Home" aria-current={path === "/" ? "page" : undefined}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
              <path d="M1 5.5L6 1l5 4.5V11H8V8H4v3H1V5.5z" />
            </svg>
          </a>
          <span className="nav-sep" aria-hidden="true" />
          {ROUTES.map(({ path: href, navLabel }) => (
            <a key={href} href={href} aria-current={path === href ? "page" : undefined}>
              {navLabel}
            </a>
          ))}
        </nav>
        <div />
      </div>
    </header>
  );
}
