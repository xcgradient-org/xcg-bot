import { useEffect, useMemo, useRef } from "react";
import AppHeader from "../components/AppHeader.jsx";

function extract(html, pattern) {
  const match = html.match(pattern);
  return match ? match[1] : "";
}

export default function LegacyToolPage({ html, title, subtitle }) {
  const rootRef = useRef(null);
  const pieces = useMemo(() => {
    const style = extract(html, /<style>([\s\S]*?)<\/style>/i);
    const body = extract(html, /<body>([\s\S]*?)<script>/i);
    const script = extract(html, /<script>([\s\S]*?)<\/script>\s*<\/body>/i);
    return { style, body, script };
  }, [html]);

  useEffect(() => {
    document.title = title;
    const styleEl = document.createElement("style");
    styleEl.dataset.legacyToolStyle = title;
    styleEl.textContent = pieces.style;
    document.head.appendChild(styleEl);
    const documentListeners = [];
    const originalDocumentAdd = document.addEventListener.bind(document);
    document.addEventListener = (type, listener, options) => {
      documentListeners.push({ type, listener, options });
      return originalDocumentAdd(type, listener, options);
    };

    if (rootRef.current) {
      rootRef.current.innerHTML = pieces.body;
    }

    // Scripts are build-time ?raw imports (never user input); script-element
    // injection is the standard DOM pattern and avoids new Function / eval.
    try {
      const scriptEl = document.createElement("script");
      scriptEl.textContent = pieces.script;
      rootRef.current.appendChild(scriptEl);
    } finally {
      document.addEventListener = originalDocumentAdd;
    }

    return () => {
      documentListeners.forEach(({ type, listener, options }) => {
        document.removeEventListener(type, listener, options);
      });
      styleEl.remove();
      if (rootRef.current) rootRef.current.innerHTML = "";
      if (window.setPhase) delete window.setPhase;
    };
  }, [pieces, title]);

  return (
    <>
      <AppHeader subtitle={subtitle} />
      <div ref={rootRef} />
    </>
  );
}
