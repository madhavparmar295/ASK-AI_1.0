import { useState, useEffect } from 'react';

export default function SplashScreen({ onFinish, forceReplay = false }) {
  const [stage, setStage] = useState('initial'); // 'initial' | 'shockwave' | 'hidden' | 'unmounted'

  useEffect(() => {
    // Reset and trigger entrance animation
    setStage('initial');

    const shockwaveTimer = setTimeout(() => {
      setStage('shockwave');
    }, 1400);

    const hiddenTimer = setTimeout(() => {
      setStage('hidden');
    }, 1850);

    const unmountTimer = setTimeout(() => {
      setStage('unmounted');
      onFinish?.();
    }, 2550);

    return () => {
      clearTimeout(shockwaveTimer);
      clearTimeout(hiddenTimer);
      clearTimeout(unmountTimer);
    };
  }, [forceReplay]);

  if (stage === 'unmounted') return null;

  return (
    <div
      id="splash-screen"
      className={stage === 'hidden' ? 'hidden' : ''}
    >
      {/* Shockwave radial pulse */}
      <div
        className={`splash-shockwave ${
          stage === 'shockwave' || stage === 'hidden' ? 'trigger' : ''
        }`}
      />

      {/* SVG Animated Logo */}
      <div className="splash-logo-container">
        <svg viewBox="0 0 600 360" xmlns="http://www.w3.org/2000/svg">
          <defs>
            {/* Tangent-locked arrowhead (medium-balanced proportion) */}
            <marker
              id="micro-arrow-splash"
              viewBox="0 0 16 16"
              refX="11.2"
              refY="8"
              markerWidth="5.6"
              markerHeight="5.6"
              orient="auto"
            >
              <path d="M 2.5,3.2 L 13.5,8 L 2.5,12.8 L 4.2,8 Z" fill="#ffffff" />
            </marker>
          </defs>

          {/* Faint static guide track */}
          <path
            d="M 374,80 C 440,32 535,62 535,138 C 535,218 438,226 300,140 C 162,54 65,62 65,142 C 65,222 155,232 232,168"
            fill="none"
            stroke="#ffffff"
            strokeWidth="13"
            strokeLinecap="round"
            opacity="0.22"
            markerEnd="url(#micro-arrow-splash)"
          />

          {/* Animated racing beam */}
          <path
            className="splash-runner"
            d="M 374,80 C 440,32 535,62 535,138 C 535,218 438,226 300,140 C 162,54 65,62 65,142 C 65,222 155,232 232,168"
          />

          {/* Starting circular node dot */}
          <circle cx="374" cy="80" r="11" fill="#ffffff" />

          {/* ASK AI Brand Typography */}
          <text
            x="300"
            y="325"
            fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Arial Black', sans-serif"
            fontWeight="900"
            fontSize="52"
            letterSpacing="8"
            fill="#ffffff"
            textAnchor="middle"
          >
            ASK AI
          </text>
        </svg>
      </div>
    </div>
  );
}
